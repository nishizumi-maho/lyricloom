using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Media;

namespace MusicBeePlugin
{
    /// <summary>What the karaoke window draws, in three layers: the night sky, the glow (blurred by the
    /// window) and the text. Holds the animation state: scroll spring, each line's emphasis, stars.</summary>
    internal sealed class KaraokeScene
    {
        public enum Layer { Sky, Glow, Text }

        private Settings _s;
        private List<KaraokeLine> _lines = new List<KaraokeLine>();
        private string _title = "";
        private double _songMs;

        // layout
        private Size _size;
        private List<Block> _blocks;
        private double _basePx;
        private Typeface _face;
        private double _dpi = 1.0;

        // Caches rebuilt only when the text, size, theme or DPI changes. FormattedText construction and
        // gradient brush construction were the scene's two per-frame allocation hotspots.
        private readonly Dictionary<TextKey, FormattedText> _texts = new Dictionary<TextKey, FormattedText>();
        private readonly Dictionary<GradientKey, Brush> _gradients = new Dictionary<GradientKey, Brush>();
        private int _clockSecond = int.MinValue;
        private string _clock = "";
        private readonly Dictionary<int, string> _clocks = new Dictionary<int, string>();

        // animation
        private ScrollPath _scrollPath;
        private double _scroll, _scrollVel;
        private bool _scrollReady;
        private double _scrollResidual, _scrollResidualVel, _scrollResidualAt;
        private double _animSec;
        private double _lastT;
        private bool _haveT;
        private double[] _emph = new double[0];
        private Star[] _stars = new Star[0];
        private double _wallSec;
        private string _nextSong = "";

        // colours
        private Color _lit, _head, _unlit, _dim, _glow, _accent;
        private Brush _sky;

        private sealed class Row
        {
            public Geometry Geo;
            public int From, Len;
            public double Width, Y, Px;
            public double[] Edges;   // right edge of char k
        }

        private sealed class Block
        {
            public List<Row> Main = new List<Row>(), Sub = new List<Row>();
            public double Top, Height;
            public bool IsBreak;
        }

        private struct Star
        {
            public double X, Y, Phase, Speed, Size;
            public bool Sparkle;
        }

        private struct TextKey : IEquatable<TextKey>
        {
            private readonly string _text;
            private readonly double _px, _maxWidth;

            public TextKey(string text, double px, double maxWidth)
            {
                _text = text ?? "";
                _px = px;
                _maxWidth = maxWidth;
            }

            public bool Equals(TextKey other) =>
                string.Equals(_text, other._text, StringComparison.Ordinal) &&
                _px.Equals(other._px) && _maxWidth.Equals(other._maxWidth);

            public string Text => _text;

            public override bool Equals(object obj) => obj is TextKey other && Equals(other);
            public override int GetHashCode() { unchecked { return ((_text?.GetHashCode() ?? 0) * 397 ^ _px.GetHashCode()) * 397 ^ _maxWidth.GetHashCode(); } }
        }

        private struct GradientKey : IEquatable<GradientKey>
        {
            private readonly int _litX, _feather, _alpha;   // quantised to keep the cache small
            private readonly uint _body, _tip;

            public GradientKey(double litX, double feather, double alpha, Color body, Color tip)
            {
                _litX = KaraokeScene.LitBucket(litX);
                _feather = (int)Math.Round(feather * 10);
                _alpha = (int)Math.Round(Math.Max(0, Math.Min(1, alpha)) * 255);
                _body = ToUint(body);
                _tip = ToUint(tip);
            }

            private static uint ToUint(Color c) => ((uint)c.A << 24) | ((uint)c.R << 16) | ((uint)c.G << 8) | c.B;

            public bool Equals(GradientKey other) =>
                _litX == other._litX && _feather == other._feather && _alpha == other._alpha &&
                _body == other._body && _tip == other._tip;

            public override bool Equals(object obj) => obj is GradientKey other && Equals(other);
            public override int GetHashCode() { unchecked { return (((_litX * 397 ^ _feather) * 397 ^ _alpha) * 397 ^ (int)_body) * 397 ^ (int)_tip; } }
        }

        public KaraokeScene(Settings s) { Apply(s); }

        /// <summary>Pixels per device-independent pixel of the render target. The window passes
        /// <c>VisualTreeHelper.GetDpi(this).PixelsPerDip</c>; the offscreen recorder and Preview use 1.0.</summary>
        public double PixelsPerDip
        {
            get => _dpi;
            set
            {
                if (double.IsNaN(value) || double.IsInfinity(value) || value <= 0) return;
                if (Math.Abs(value - _dpi) < 1e-9) return;
                _dpi = value;
                _blocks = null;       // glyph widths and edges were measured at the old DPI
                ClearCaches();
            }
        }

        public void Apply(Settings s)
        {
            _s = s;
            // A random theme overrides the colour fields for this song. Otherwise a named preset is used
            // directly; picking one in the settings window also copies its colours into the fields so
            // the colour rows show it, and editing a colour switches the preset label to "Custom".
            var theme = s.RandomTheme ? Themes.ForSong(_title) : Themes.Get(s.Theme);
            _lit = Settings.ParseColor(theme?.Lit ?? s.LitColor, Color.FromRgb(255, 206, 92));
            _head = Settings.ParseColor(theme?.Head ?? s.HeadColor, Color.FromRgb(255, 255, 235));
            _unlit = Settings.ParseColor(theme?.Unlit ?? s.UnlitColor, Color.FromRgb(148, 150, 178));
            _dim = Settings.ParseColor(theme?.Dim ?? s.DimColor, Color.FromRgb(78, 80, 104));
            _glow = Settings.ParseColor(theme?.Glow ?? s.GlowColor, Color.FromRgb(255, 180, 60));
            _accent = Settings.ParseColor(theme?.Accent ?? s.AccentColor, Color.FromRgb(140, 120, 255));
            _sky = new LinearGradientBrush(Settings.ParseColor(theme?.BackgroundTop ?? s.BackgroundTop, Color.FromRgb(10, 10, 24)),
                                           Settings.ParseColor(theme?.BackgroundBottom ?? s.BackgroundBottom, Color.FromRgb(22, 16, 44)), 90);
            _sky.Freeze();
            _face = new Typeface(new FontFamily(string.IsNullOrWhiteSpace(s.FontFamily) ? "Segoe UI" : s.FontFamily),
                                 FontStyles.Normal, FontWeights.Normal, FontStretches.Normal);
            _blocks = null;
            _stars = new Star[0];
            ClearCaches();
            _brushes.Clear();
        }

        private void ClearCaches()
        {
            _texts.Clear();
            _gradients.Clear();
            _clocks.Clear();
            _clock = "";
            _clockSecond = int.MinValue;
        }

        public void SetSong(List<KaraokeLine> lines, string title, double songMs)
        {
            _lines = lines ?? new List<KaraokeLine>();
            _title = title ?? "";
            _songMs = songMs;
            _emph = new double[_lines.Count];
            _blocks = null;
            _scrollPath = null;
            _haveT = false;
            _nextSong = "";
            _texts.Clear();
            _clock = "";
            _clockSecond = int.MinValue;
            if (_s.RandomTheme) Apply(_s);
        }

        public void SetNextSong(string next) => _nextSong = next ?? "";

        /// <summary>Loop range in lyric time, drawn as a small badge; NaN means no loop.</summary>
        public double LoopStart = double.NaN, LoopEnd = double.NaN;

        public Color Accent => _accent;

        public bool HasLines => _lines.Count > 0;

        /// <summary>Clock of the twinkling and pulsing, in seconds. The recorder ties it to the song time so
        /// video segments rendered in parallel join without a jump.</summary>
        public double WallSeconds { get => _wallSec; set => _wallSec = value; }

        /// <summary>Hides the title and progress bar (fullscreen "lyrics only").</summary>
        public bool LyricsOnly { get; set; }

        /// <summary>The window's transport bar is showing its own seek bar in that place.</summary>
        public bool HideProgress { get; set; }

        // ---------------------------------------------------------------- layout

        /// <summary>Rebuilds the wrapped rows when the text, size, theme or DPI changed. Returns true
        /// when it did, so the scroll can absorb the new layout without jumping.</summary>
        private bool EnsureLayout(Size size)
        {
            if (_blocks != null && size == _size) return false;
            // The star positions are normalised, so they do not need to be regenerated for a resize:
            // reshuffling the whole sky every time the user drags the window edge looks like a glitch.
            if (_stars.Length == 0) MakeStars(size);
            if (size != _size) ClearCaches();
            _size = size;
            _basePx = Math.Max(18, Math.Min(110, size.Height / 13)) * Math.Max(0.4, Math.Min(2.5, _s.TextScale));
            var width = Math.Max(80, (size.Width - 2 * Margin(size)) / 1.09);   // room for the current line growing
            _blocks = new List<Block>();
            double top = 0;
            foreach (var line in _lines)
            {
                var b = new Block { Top = top, IsBreak = line.IsBreak };
                double y = 0;
                var mainText = line.IsBreak ? "♪   ♪   ♪" : line.Main.Text;
                foreach (var r in Wrap(mainText, _basePx, width)) { r.Y = y; y += r.Px * 1.32; b.Main.Add(r); }
                if (line.Sub != null && line.Sub.Text.Length > 0)
                    foreach (var r in Wrap(line.Sub.Text, _basePx * 0.55, width)) { r.Y = y; y += r.Px * 1.4; b.Sub.Add(r); }
                b.Height = y;
                top += y + _basePx * 0.6;
                _blocks.Add(b);
            }
            BuildScrollPath();
            return true;
        }

        /// <summary>One allocation per layout change: the pure scroll path reads centres and start
        /// times from this object every frame.</summary>
        private void BuildScrollPath()
        {
            if (_blocks == null || _blocks.Count == 0 || _lines.Count == 0)
            {
                _scrollPath = null;
                return;
            }
            var n = Math.Min(_blocks.Count, _lines.Count);
            var centers = new double[n];
            var starts = new double[n];
            for (var i = 0; i < n; i++)
            {
                centers[i] = _blocks[i].Top + _blocks[i].Height / 2;
                starts[i] = _lines[i].StartMs;
            }
            _scrollPath = new ScrollPath(centers, starts, _s.TransitionSpeed, _basePx * 1.5);
        }

        private static double Margin(Size size) => Math.Max(24, size.Width * 0.05);

        private FormattedText Text(string s, double px, double maxWidth = double.PositiveInfinity)
        {
            var key = new TextKey(s, px, maxWidth);
            if (_texts.TryGetValue(key, out var ft)) return ft;
            ft = new FormattedText(key.Text, CultureInfo.CurrentUICulture, FlowDirection.LeftToRight, _face, px, Brushes.White, _dpi);
            if (!double.IsInfinity(maxWidth) && maxWidth > 0)
            {
                ft.MaxTextWidth = maxWidth;
                ft.Trimming = TextTrimming.CharacterEllipsis;
            }
            if (_texts.Count > 1024) _texts.Clear();
            _texts[key] = ft;
            return ft;
        }

        /// <summary>Greedy wrap on spaces (or between characters for text without spaces).</summary>
        private List<Row> Wrap(string text, double px, double width)
        {
            var rows = new List<Row>();
            var start = 0;
            while (start < text.Length)
            {
                var end = text.Length;
                if (Text(text.Substring(start), px).WidthIncludingTrailingWhitespace > width)
                {
                    // longest prefix that fits, preferring to cut at a space
                    int lo = start + 1, hi = text.Length;
                    while (lo < hi)
                    {
                        var mid = (lo + hi + 1) / 2;
                        if (Text(text.Substring(start, mid - start), px).Width <= width) lo = mid; else hi = mid - 1;
                    }
                    end = lo;
                    var space = text.LastIndexOf(' ', end - 1, end - start);
                    if (space > start) end = space;
                }
                rows.Add(MakeRow(text, start, end - start, px));
                start = end;
                while (start < text.Length && text[start] == ' ') start++;
            }
            if (rows.Count == 0) rows.Add(MakeRow("", 0, 0, px));
            return rows;
        }

        private Row MakeRow(string text, int from, int len, double px)
        {
            var s = text.Substring(from, len);
            var ft = Text(s, px);
            var row = new Row { From = from, Len = len, Px = px, Width = ft.Width, Edges = new double[len] };
            row.Geo = ft.BuildGeometry(new Point(0, 0));
            row.Geo.Freeze();
            for (var k = 0; k < len; k++)
            {
                var g = ft.BuildHighlightGeometry(new Point(0, 0), 0, k + 1);
                row.Edges[k] = g == null ? (k > 0 ? row.Edges[k - 1] : 0) : g.Bounds.Right;
            }
            return row;
        }

        private void MakeStars(Size size)
        {
            var rnd = new Random(7);
            var n = (int)(size.Width * size.Height / 9000 * Math.Max(0.25, Math.Min(2, _s.StarDensity)));
            _stars = Enumerable.Range(0, Math.Max(0, Math.Min(900, n))).Select(_ => new Star
            {
                X = rnd.NextDouble(), Y = rnd.NextDouble(), Phase = rnd.NextDouble() * 6.28,
                Speed = 0.6 + rnd.NextDouble() * 1.8, Size = 0.6 + rnd.NextDouble() * 1.4,
                Sparkle = rnd.NextDouble() < 0.18
            }).ToArray();
        }

        // ---------------------------------------------------------------- animation

        /// <summary>Advances the wall clock for the stars, and evaluates the time-driven scroll and
        /// emphasis for song time t (ms). dt is the real time since the previous frame; it only
        /// drives the residual spring and the twinkling, never the path.</summary>
        public void Update(double dt, double t, Size size)
        {
            if (dt < 0) dt = 0;
            _wallSec += dt;
            _animSec += dt;
            var layoutChanged = EnsureLayout(size);
            if (_blocks == null || _blocks.Count == 0 || _scrollPath == null || _lines.Count == 0) return;

            var phase = _scrollPath.PhaseAt(t);
            var oldScroll = _scroll;
            var oldVelocity = _scrollVel;
            var discontinuity = false;
            if (!_scrollReady)
            {
                _scroll = phase.Position;
                _scrollVel = 0;
                _scrollResidual = 0;
                _scrollResidualVel = 0;
                _scrollReady = true;
            }
            else
            {
                discontinuity = layoutChanged || IsSongTimeJump(t, dt);
                if (discontinuity)
                {
                    // Preserve both the shown position and its velocity: the residual starts at the
                    // difference and lets the critically damped spring absorb it without a cut.
                    _scrollResidual = oldScroll - phase.Position;
                    _scrollResidualVel = ScrollPath.ClampResidualVelocity(
                        _scrollResidual, oldVelocity - _scrollPath.VelocityAt(t));
                    _scrollResidualAt = _animSec;
                }
                var residual = _scrollResidual == 0 && _scrollResidualVel == 0
                    ? 0
                    : ScrollPath.ResidualAt(_scrollResidual, _scrollResidualVel, _animSec - _scrollResidualAt);
                if (Math.Abs(residual) < 0.001 && Math.Abs(_scrollResidualVel) < 0.001)
                {
                    residual = 0;
                    _scrollResidual = 0;
                    _scrollResidualVel = 0;
                }
                _scroll = phase.Position + residual;
            }

            if (discontinuity)
                _scrollVel = oldVelocity;       // the residual starts with exactly that velocity
            else if (dt > 0.000001)
                _scrollVel = (_scroll - oldScroll) / dt;
            _lastT = t;
            _haveT = true;

            // Emphasis follows the same eased u as the scroll: the incoming line grows while it
            // glides in, and the outgoing one dims over the same interval.
            Array.Clear(_emph, 0, _emph.Length);
            if (phase.IsTransition)
            {
                var eased = ScrollPath.Smootherstep(phase.U);
                if (phase.From < 0)
                {
                    if (_emph.Length > 0) _emph[0] = eased;
                }
                else
                {
                    if (phase.From < _emph.Length) _emph[phase.From] = 1 - eased;
                    if (phase.From + 1 < _emph.Length) _emph[phase.From + 1] = eased;
                }
            }
            else
            {
                var current = Timeline.CurrentIndex(_lines, t);
                if (current >= 0 && current < _emph.Length) _emph[current] = 1;
            }
        }

        /// <summary>A seek (or a stall long enough that the clock had to snap) changes song time by
        /// more than the frame's own interval. Paused frames keep t still, which is not a jump.</summary>
        private bool IsSongTimeJump(double t, double dt)
        {
            if (!_haveT) return false;
            if (t < _lastT - 0.001) return true;
            // A paused frame keeps t still while real time advances; that is not a jump.
            if (Math.Abs(t - _lastT) < 0.001) return false;
            var expected = _lastT + dt * 1000.0;
            return Math.Abs(t - expected) > 30.0;
        }

        // ---------------------------------------------------------------- drawing

        /// <summary>The scroll offset used by the last Update (for tests and the frame-series harness).</summary>
        internal double ScrollOffset => _scroll;

        /// <summary>How far the shown scroll still is from the pure path (for the settle check).</summary>
        internal double ScrollResidual => _scrollPath == null ? 0 : _scroll - _scrollPath.PositionAt(_lastT);

        /// <summary>The path's peak speed, in pixels per second (for continuity bounds).</summary>
        internal double ScrollPeakVelocity => _scrollPath?.PeakVelocity ?? 0;

        /// <summary>The path's peak acceleration, in pixels per second squared.</summary>
        internal double ScrollPeakAcceleration => _scrollPath?.PeakAcceleration ?? 0;

        /// <summary>The scale the given line is drawn with (for the frame-series harness).</summary>
        internal double LineScale(int index) =>
            _s.GrowCurrentLine && index >= 0 && index < _emph.Length ? 1 + 0.08 * _emph[index] : 1;

        public void Render(Layer layer, DrawingContext dc, Size size, double t)
        {
            if (size.Width < 2 || size.Height < 2) return;
            EnsureLayout(size);
            if (layer == Layer.Sky) { DrawSky(dc, size); return; }

            if (_s.ShowProgress && !LyricsOnly && !HideProgress) DrawProgress(dc, size, t, layer);
            if (_blocks.Count == 0)
            {
                if (layer == Layer.Text) DrawCentered(dc, size, _songMs < 0 ? "" : Strings.NoSyncedLyrics, _basePx * 0.6, _dim, size.Height / 2);
                return;
            }

            var mid = size.Height / 2;
            var cur = Timeline.CurrentIndex(_lines, t);
            if (cur < 0 && layer == Layer.Text) DrawCountdown(dc, size, t, mid);

            var headerBottom = _s.ShowHeader && !LyricsOnly ? Math.Min(size.Height * 0.22, 180) : 0;
            for (var i = 0; i < _blocks.Count; i++)
            {
                var b = _blocks[i];
                var top = mid + b.Top - _scroll;
                if (top > size.Height || top + b.Height < 0) continue;
                var center = top + b.Height / 2;
                var near = Math.Max(0, 1 - Math.Abs(center - mid) / (size.Height * 0.5));
                var fade = Smooth(Math.Min(1, near * 2.2));      // fade out towards the edges
                if (headerBottom > 0 && center < headerBottom)
                    fade *= Smooth(Math.Max(0, Math.Min(1, (center - headerBottom * 0.35) / (headerBottom * 0.65))));
                if (fade <= 0.01) continue;
                var e = _emph.Length > i ? _emph[i] : 0;
                var scale = _s.GrowCurrentLine ? 1 + 0.08 * e : 1;
                dc.PushTransform(new ScaleTransform(scale, scale, size.Width / 2, center));
                DrawBlock(dc, layer, size, b, _lines[i], top, near, e, t, i == cur, fade);
                dc.Pop();
            }

            if (_s.LineBursts && _s.ShowStars) DrawLineBursts(dc, layer, size, t, mid);
            if (layer == Layer.Text)
            {
                DrawNextSong(dc, size, t);
                DrawEnding(dc, size, t);
                if (_s.ShowHeader && !LyricsOnly) DrawHeader(dc, size);
                DrawLoopBadge(dc, size);
            }
        }

        // Transparency goes into the brush colours rather than PushOpacity/PushOpacityMask: those make WPF
        // draw into an extra layer, which the recorder's software rendering pays for on every frame.
        private void DrawBlock(DrawingContext dc, Layer layer, Size size, Block b, KaraokeLine line, double top,
                               double near, double e, double t, bool isCurrent, double alpha)
        {
            var baseColor = Fade(Mix(Mix(_dim, _unlit, near * 0.55), _unlit, e), alpha);
            if (b.IsBreak)
            {
                if (layer != Layer.Text) return;
                var pulse = isCurrent ? (Math.Sin(_wallSec * 3) + 1) / 2 : 0;
                foreach (var r in b.Main) DrawRow(dc, r, top, size, Mix(baseColor, Fade(_lit, alpha), pulse * e));
                return;
            }
            if (layer == Layer.Text)
            {
                foreach (var r in b.Main) DrawRow(dc, r, top, size, baseColor);
                foreach (var r in b.Sub) DrawRow(dc, r, top, size, Mix(baseColor, Fade(_dim, alpha), 0.25));
            }
            if (e < 0.01) return;
            // the lit fill fades in and out with the line's emphasis (already eased by the path)
            var litAlpha = e * alpha;
            var lit = line.Main.LitChars(t);
            foreach (var r in b.Main) DrawLit(dc, layer, r, top, size, lit, litAlpha);
            if (line.Sub != null)
            {
                var lit2 = line.Sub.LitChars(t);
                foreach (var r in b.Sub) DrawLit(dc, layer, r, top, size, lit2, litAlpha);
            }
        }

        private static Color Fade(Color c, double alpha) =>
            Color.FromArgb((byte)Math.Round(c.A * Math.Max(0, Math.Min(1, alpha))), c.R, c.G, c.B);

        private void DrawRow(DrawingContext dc, Row r, double top, Size size, Color c)
        {
            dc.PushTransform(new TranslateTransform((size.Width - r.Width) / 2, top + r.Y));
            dc.DrawGeometry(Solid(c), null, r.Geo);
            dc.Pop();
        }

        /// <summary>The lit part of a row: gold fading to a bright head at the sweep, with a soft edge.</summary>
        private void DrawLit(DrawingContext dc, Layer layer, Row r, double top, Size size, double lit, double alpha)
        {
            if (layer == Layer.Glow && !_s.Glow) return;
            var n = Math.Max(0, Math.Min(r.Len, lit - r.From));
            if (n <= 0 || r.Len == 0) return;
            var x0 = (size.Width - r.Width) / 2;
            var k = (int)Math.Floor(n);
            var left = k == 0 ? 0 : r.Edges[Math.Min(k, r.Len) - 1];
            var right = k < r.Len ? r.Edges[k] : left;
            var litX = left + (n - k) * (right - left);
            var feather = r.Px * 0.45;
            var done = n >= r.Len;

            dc.PushTransform(new TranslateTransform(x0, top + r.Y));
            Brush fill;
            var body = layer == Layer.Glow ? _glow : _lit;
            var tip = layer == Layer.Glow ? _glow : _head;
            if (done) fill = Solid(Fade(body, alpha));
            else fill = LitFill(litX, feather, alpha, body, tip);
            dc.DrawGeometry(fill, null, r.Geo);
            dc.Pop();
        }

        /// <summary>The sweep's gold-to-transparent gradient, cached by its quantised position and alpha.
        /// The edge moves in quarter-pixel buckets (at most 0.25 px per step, never more than 0.125 px
        /// from the mathematical position): a sub-pixel change still looks continuous at any refresh
        /// rate, and the cache stays small.</summary>
        private Brush LitFill(double litX, double feather, double alpha, Color body, Color tip)
        {
            var key = new GradientKey(litX, feather, alpha, body, tip);
            if (_gradients.TryGetValue(key, out var cached)) return cached;
            var snapped = LitBucket(litX) / 4.0;

            // one gradient does it all: gold, brightening towards the sweep, then fading out over the
            // feather (the soft edge), transparent beyond it
            var g = new LinearGradientBrush
            {
                MappingMode = BrushMappingMode.Absolute,
                StartPoint = new Point(snapped - feather * 5, 0),
                EndPoint = new Point(snapped + feather * 0.6, 0)
            };
            var span = feather * 5.6;
            g.GradientStops.Add(new GradientStop(Fade(body, alpha), 0));
            g.GradientStops.Add(new GradientStop(Fade(tip, alpha), (feather * 4) / span));
            g.GradientStops.Add(new GradientStop(Fade(tip, 0), 1));
            g.Freeze();
            if (_gradients.Count > 2048) _gradients.Clear();
            _gradients[key] = g;
            return g;
        }

        private void DrawSky(DrawingContext dc, Size size)
        {
            dc.DrawRectangle(_sky, null, new Rect(size));
            if (!_s.ShowStars) return;
            DrawStars(dc, size, _wallSec);
            if (_s.ShowShootingStars) DrawShootingStars(dc, size, _wallSec);
        }

        private void DrawStars(DrawingContext dc, Size size, double t)
        {
            var starColor = Mix(Color.FromRgb(170, 172, 220), _accent, 0.22);
            foreach (var st in _stars)
            {
                var b = (Math.Sin(t * st.Speed + st.Phase) + 1) / 2;
                var brush = Solid(Fade(starColor, 0.12 + 0.75 * b * b));
                var p = new Point(st.X * size.Width, st.Y * size.Height);
                if (st.Sparkle) DrawSparkle(dc, brush, p, 2.2 + st.Size * 2.4 * (0.7 + 0.3 * b));
                else dc.DrawEllipse(brush, null, p, st.Size, st.Size);
            }
        }

        private void DrawShootingStars(DrawingContext dc, Size size, double t)
        {
            const double period = 17.0;
            var index = (int)Math.Floor(t / period);
            var local = t - index * period;
            if (local > 1.1) return;
            var h1 = Hash(index * 17 + 3);
            var h2 = Hash(index * 17 + 9);
            var h3 = Hash(index * 17 + 15);
            var startX = 0.12 + h1 * 0.7;
            var startY = 0.05 + h2 * 0.25;
            var len = 0.07 + h3 * 0.09;
            var fade = Math.Sin(Math.PI * Math.Min(1, local / 1.1));
            var p0 = new Point((startX - len) * size.Width, (startY - len * 0.36) * size.Height);
            var p1 = new Point((startX + local * 0.45) * size.Width, (startY + local * 0.16) * size.Height);
            var brush = Solid(Fade(Color.FromRgb(255, 255, 236), fade * 0.85));
            dc.DrawLine(new Pen(brush, Math.Max(1.2, size.Height / 540.0)), p0, p1);
            dc.DrawEllipse(brush, null, p1, Math.Max(1.2, size.Height / 480.0), Math.Max(1.2, size.Height / 480.0));
        }

        private static double Hash(int n)
        {
            var x = Math.Sin(n * 12.9898) * 43758.5453;
            return x - Math.Floor(x);
        }

        /// <summary>Four-point star of radius 1 at the origin, shared by every sparkle.</summary>
        private static readonly Geometry UnitSparkle = MakeUnitSparkle();

        private static Geometry MakeUnitSparkle()
        {
            var g = new StreamGeometry();
            using (var ctx = g.Open())
            {
                const double w = 0.22;
                ctx.BeginFigure(new Point(0, -1), true, true);
                ctx.LineTo(new Point(w, -w), false, false);
                ctx.LineTo(new Point(1, 0), false, false);
                ctx.LineTo(new Point(w, w), false, false);
                ctx.LineTo(new Point(0, 1), false, false);
                ctx.LineTo(new Point(-w, w), false, false);
                ctx.LineTo(new Point(-1, 0), false, false);
                ctx.LineTo(new Point(-w, -w), false, false);
            }
            g.Freeze();
            return g;
        }

        private static void DrawSparkle(DrawingContext dc, Brush brush, Point c, double r)
        {
            dc.PushTransform(new MatrixTransform(r, 0, 0, r, c.X, c.Y));
            dc.DrawGeometry(brush, null, UnitSparkle);
            dc.Pop();
        }

        private void DrawLineBursts(DrawingContext dc, Layer layer, Size size, double t, double mid)
        {
            if (_blocks == null) return;
            var glow = layer == Layer.Glow;
            var color = glow ? _glow : _head;
            for (var i = 0; i < _lines.Count; i++)
            {
                var line = _lines[i];
                if (line.IsBreak || line.EndMs <= line.StartMs || i >= _blocks.Count) continue;
                var age = t - line.EndMs;
                var burst = BurstProgress(age);
                if (burst == null) continue;
                var b = _blocks[i];
                var cx = size.Width / 2;
                var cy = mid + b.Top + b.Height / 2 - _scroll;
                var progress = burst.Value;
                var alpha = 1 - progress;
                var count = glow ? 6 : 11;
                for (var k = 0; k < count; k++)
                {
                    var angle = k * 2.399963 + i * 0.73;
                    var dist = (8 + _basePx * 1.4 * Smooth(progress)) * (0.55 + 0.45 * Hash(i * 37 + k));
                    var p = new Point(cx + Math.Cos(angle) * dist, cy + Math.Sin(angle) * dist);
                    var r = Math.Max(1, _basePx * 0.035 * (1 - progress * 0.45));
                    dc.DrawEllipse(Solid(Fade(color, alpha * (glow ? 0.55 : 0.85))), null, p, r, r);
                }
            }
        }

        /// <summary>Where a line-end burst is in its 0.8 second life: 0 at the line end, 1 when it is gone.
        /// Both the time and the line's end are in milliseconds; the window is in seconds.</summary>
        internal static double? BurstProgress(double ageMs)
        {
            var ageSec = ageMs / 1000.0;
            if (ageSec < 0 || ageSec > 0.8) return null;
            return ageSec / 0.8;
        }

        private void DrawLoopBadge(DrawingContext dc, Size size)
        {
            if (double.IsNaN(LoopStart)) return;
            var px = Math.Max(11, _basePx * 0.28);
            var ft = Text(Strings.LoopBadge, px);
            ft.SetForegroundBrush(Solid(Fade(_accent, 0.8)));
            var x = size.Width - Margin(size) - ft.Width;
            var y = Math.Max(10, size.Height * 0.045);
            dc.DrawText(ft, new Point(x, y));
        }

        private void DrawNextSong(DrawingContext dc, Size size, double t)
        {
            if (!_s.PartyMode || !_s.ShowNextSong || string.IsNullOrEmpty(_nextSong) || _songMs <= 0) return;
            if (t < _songMs - 15000) return;
            var px = Math.Max(11, _basePx * 0.3);
            var ft = Text(Strings.NextSongLabel(_nextSong), px, size.Width - 2 * Margin(size));
            ft.SetForegroundBrush(Solid(Fade(_unlit, 0.78)));
            var y = size.Height - Math.Max(38, size.Height * 0.1) - ft.Height;
            dc.DrawText(ft, new Point((size.Width - ft.Width) / 2, y));
        }

        private void DrawEnding(DrawingContext dc, Size size, double t)
        {
            if (!_s.PartyMode || _songMs <= 0 || !string.IsNullOrEmpty(_nextSong)) return;
            if (t < _songMs - 2500) return;
            var px = Math.Max(12, _basePx * 0.38);
            var pulse = (Math.Sin(_wallSec * 3) + 1) / 2;
            DrawCentered(dc, size, Strings.ThanksForSinging, px, Mix(_accent, _head, 0.35 + 0.5 * pulse),
                         size.Height - Math.Max(44, size.Height * 0.12));
        }

        private void DrawHeader(DrawingContext dc, Size size)
        {
            if (string.IsNullOrEmpty(_title)) return;
            var px = Math.Max(13, _basePx * 0.42);
            var c = Mix(_accent, _head, (Math.Sin(_wallSec * 1.3) + 1) / 4);
            var y = Math.Max(10, size.Height * 0.045);
            var ft = Text(_title, px, size.Width - 2 * Margin(size) - px * 3);
            ft.SetForegroundBrush(Solid(c));
            var x = (size.Width - ft.Width) / 2;
            dc.DrawText(ft, new Point(x, y));
            var cy = y + ft.Height / 2;
            var gap = px * 1.4;
            DrawSparkle(dc, Solid(c), new Point(x - gap, cy), px * 0.42);
            DrawSparkle(dc, Solid(c), new Point(x + ft.Width + gap, cy), px * 0.42);
        }

        private void DrawProgress(DrawingContext dc, Size size, double t, Layer layer)
        {
            if (_songMs <= 0) return;
            var px = Math.Max(11, _basePx * 0.3);
            var y = size.Height - Math.Max(18, size.Height * 0.055);
            var left = Margin(size) + px * 3.5;
            var right = size.Width - Margin(size) - px * 3.5;
            if (right - left < 40) return;
            var frac = Math.Max(0, Math.Min(1, t / _songMs));
            var fx = left + (right - left) * frac;
            var thick = Math.Max(2, px * 0.18);
            if (layer == Layer.Glow)
            {
                if (_s.Glow) dc.DrawRectangle(Solid(_glow), null, new Rect(left, y - thick, fx - left, thick * 2));
                return;
            }
            dc.DrawRectangle(Solid(_dim), null, new Rect(left, y - 0.5, right - left, 1));
            dc.DrawRectangle(Solid(_lit), null, new Rect(left, y - thick / 2, fx - left, thick));
            dc.DrawEllipse(Solid(_head), null, new Point(fx, y), thick * 1.3, thick * 1.3);
            var a = Text(Clock(t), px); a.SetForegroundBrush(Solid(_unlit));
            var b = Text(Clock(_songMs), px); b.SetForegroundBrush(Solid(_unlit));
            dc.DrawText(a, new Point(left - a.Width - px, y - a.Height / 2));
            dc.DrawText(b, new Point(right + px, y - b.Height / 2));
        }

        private void DrawCountdown(DrawingContext dc, Size size, double t, double mid)
        {
            if (_lines.Count == 0) return;
            var left = (_lines[0].StartMs - t) / 1000;
            if (left > 60) return;
            var msg = left > 3 ? Strings.CountdownDots : Math.Ceiling(Math.Max(0.01, left)).ToString(CultureInfo.InvariantCulture);
            var pulse = 1 - (left - Math.Floor(left));
            DrawCentered(dc, size, msg, _basePx * 0.8, Mix(_dim, _lit, left > 3 ? 0.3 : pulse), mid - _basePx * 2.4);
        }

        private void DrawCentered(DrawingContext dc, Size size, string s, double px, Color c, double cy)
        {
            if (string.IsNullOrEmpty(s)) return;
            var ft = Text(s, px);
            ft.SetForegroundBrush(Solid(c));
            dc.DrawText(ft, new Point((size.Width - ft.Width) / 2, cy - ft.Height / 2));
        }

        // ---------------------------------------------------------------- interaction

        /// <summary>The line under a point in the window, or -1. Used for click-to-seek.</summary>
        public int LineAt(Point p, Size size, double t)
        {
            EnsureLayout(size);
            if (_blocks == null) return -1;
            var mid = size.Height / 2;
            for (var i = 0; i < _blocks.Count; i++)
            {
                var top = mid + _blocks[i].Top - _scroll;
                if (p.Y >= top && p.Y <= top + _blocks[i].Height) return i;
            }
            return -1;
        }

        public int CurrentLine(double t) => Timeline.CurrentIndex(_lines, t);

        public double LineStart(int index) =>
            index >= 0 && index < _lines.Count ? _lines[index].StartMs : double.NaN;

        /// <summary>Start and end of a line, or of a short run of lines (for a practice loop).</summary>
        public (double Start, double End) LineRange(int index, int count)
        {
            if (index < 0 || index >= _lines.Count) return (double.NaN, double.NaN);
            count = Math.Max(1, count);
            var start = _lines[index].StartMs;
            var end = _lines[index].EndMs;
            var taken = 1;
            for (var k = index + 1; k < _lines.Count && taken < count; k++)
            {
                if (_lines[k].IsBreak) break;
                end = Math.Max(end, _lines[k].EndMs);
                taken++;
            }
            if (_lines[index].IsBreak && index + 1 < _lines.Count)
                end = Math.Max(end, _lines[index + 1].StartMs);
            if (end <= start) end = start + 1500;
            return (start, end);
        }

        // ---------------------------------------------------------------- helpers

        /// <summary>The lit edge quantised to a quarter of a device-independent pixel (the
        /// GradientKey stores times four).</summary>
        internal static int LitBucket(double litX) => (int)Math.Round(litX * 4);

        private string Clock(double ms)
        {
            var s = (int)Math.Max(0, ms / 1000);
            if (s == _clockSecond) return _clock;
            if (!_clocks.TryGetValue(s, out var text))
            {
                text = $"{s / 60}:{s % 60:00}";
                if (_clocks.Count > 4096) _clocks.Clear();
                _clocks[s] = text;
            }
            _clockSecond = s;
            _clock = text;
            return text;
        }

        private static double Smooth(double x)
        {
            x = Math.Max(0, Math.Min(1, x));
            return x * x * (3 - 2 * x);
        }

        private static Color Mix(Color a, Color b, double t)
        {
            t = Math.Max(0, Math.Min(1, t));
            return Color.FromArgb((byte)(a.A + (b.A - a.A) * t), (byte)(a.R + (b.R - a.R) * t),
                                  (byte)(a.G + (b.G - a.G) * t), (byte)(a.B + (b.B - a.B) * t));
        }

        private readonly Dictionary<Color, SolidColorBrush> _brushes = new Dictionary<Color, SolidColorBrush>();

        /// <summary>Frozen brush per colour. Animated colours are rounded to steps of 4 so the cache stays
        /// small (MusicBee is a 32-bit process with little memory to spare).</summary>
        private Brush Solid(Color c)
        {
            c = Color.FromArgb((byte)(c.A & 0xFC), (byte)(c.R & 0xFC), (byte)(c.G & 0xFC), (byte)(c.B & 0xFC));
            if (_brushes.TryGetValue(c, out var b)) return b;
            if (_brushes.Count > 512) _brushes.Clear();
            b = new SolidColorBrush(c);
            b.Freeze();
            _brushes[c] = b;
            return b;
        }
    }
}
