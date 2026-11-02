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
        private readonly double _dpi = 1.0;

        // animation
        private double _scroll, _scrollVel;
        private bool _scrollReady;
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

        public KaraokeScene(Settings s) { Apply(s); }

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
        }

        public void SetSong(List<KaraokeLine> lines, string title, double songMs)
        {
            _lines = lines ?? new List<KaraokeLine>();
            _title = title ?? "";
            _songMs = songMs;
            _emph = new double[_lines.Count];
            _blocks = null;
            _scrollReady = false;
            _nextSong = "";
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

        private void EnsureLayout(Size size)
        {
            if (_blocks != null && size == _size) return;
            // The star positions are normalised, so they do not need to be regenerated for a resize:
            // reshuffling the whole sky every time the user drags the window edge looks like a glitch.
            if (_stars.Length == 0) MakeStars(size);
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
        }

        private static double Margin(Size size) => Math.Max(24, size.Width * 0.05);

        private FormattedText Text(string s, double px, double maxWidth = double.PositiveInfinity)
        {
            var ft = new FormattedText(s, CultureInfo.CurrentUICulture, FlowDirection.LeftToRight, _face, px, Brushes.White, _dpi);
            if (!double.IsInfinity(maxWidth) && maxWidth > 0)
            {
                ft.MaxTextWidth = maxWidth;
                ft.Trimming = TextTrimming.CharacterEllipsis;
            }
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

        /// <summary>Advances springs and fades by dt seconds for song time t (ms).</summary>
        public void Update(double dt, double t, Size size)
        {
            _wallSec += dt;
            EnsureLayout(size);
            if (_blocks.Count == 0) return;
            var speed = Math.Max(0.3, Math.Min(3, _s.TransitionSpeed));
            var cur = Timeline.CurrentIndex(_lines, t);

            // scroll: critically damped spring towards the current line's centre
            var focus = cur < 0 ? 0 : cur;
            var target = _blocks[focus].Top + _blocks[focus].Height / 2;
            if (cur < 0) target -= _basePx * 1.5;   // intro: first line a little below the middle
            if (!_scrollReady || dt > 0.5) { _scroll = target; _scrollVel = 0; _scrollReady = true; }
            else
            {
                var w = 2 * Math.PI / (0.75 / speed);
                var acc = w * w * (target - _scroll) - 2 * w * _scrollVel;
                _scrollVel += acc * dt;
                _scroll += _scrollVel * dt;
            }

            // emphasis: 1 for the current line (until the next starts), easing in and out
            var k = 1 - Math.Exp(-dt * 7 * speed);
            for (var i = 0; i < _emph.Length; i++)
            {
                var on = i == cur ? 1.0 : 0.0;
                _emph[i] += (on - _emph[i]) * k;
            }
        }

        // ---------------------------------------------------------------- drawing

        public void Render(Layer layer, DrawingContext dc, Size size, double t)
        {
            if (size.Width < 2 || size.Height < 2) return;
            EnsureLayout(size);
            if (layer == Layer.Sky) { DrawSky(dc, size); return; }

            if (_s.ShowProgress && !LyricsOnly && !HideProgress) DrawProgress(dc, size, t, layer);
            if (_blocks.Count == 0)
            {
                if (layer == Layer.Text) DrawCentered(dc, size, _songMs < 0 ? "" : "no synced lyrics", _basePx * 0.6, _dim, size.Height / 2);
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
                var scale = _s.GrowCurrentLine ? 1 + 0.08 * Smooth(e) : 1;
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
            // the lit fill fades in and out with the line's emphasis
            var litAlpha = Smooth(e) * alpha;
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
            else
            {
                // one gradient does it all: gold, brightening towards the sweep, then fading out over the
                // feather (the soft edge), transparent beyond it
                var g = new LinearGradientBrush
                {
                    MappingMode = BrushMappingMode.Absolute,
                    StartPoint = new Point(litX - feather * 5, 0),
                    EndPoint = new Point(litX + feather * 0.6, 0)
                };
                var span = feather * 5.6;
                g.GradientStops.Add(new GradientStop(Fade(body, alpha), 0));
                g.GradientStops.Add(new GradientStop(Fade(tip, alpha), (feather * 4) / span));
                g.GradientStops.Add(new GradientStop(Fade(tip, 0), 1));
                g.Freeze();
                fill = g;
            }
            dc.DrawGeometry(fill, null, r.Geo);
            dc.Pop();
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
                if (age < 0 || age > 0.8) continue;
                var b = _blocks[i];
                var cx = size.Width / 2;
                var cy = mid + b.Top + b.Height / 2 - _scroll;
                var progress = age / 0.8;
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

        private void DrawLoopBadge(DrawingContext dc, Size size)
        {
            if (double.IsNaN(LoopStart)) return;
            var px = Math.Max(11, _basePx * 0.28);
            var ft = Text("⟲  loop", px);
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
            var ft = Text("A seguir: " + _nextSong, px, size.Width - 2 * Margin(size));
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
            DrawCentered(dc, size, "✦  thanks for singing  ✦", px, Mix(_accent, _head, 0.35 + 0.5 * pulse),
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
            var msg = left > 3 ? "·  ·  ·" : Math.Ceiling(Math.Max(0.01, left)).ToString(CultureInfo.InvariantCulture);
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

        private static string Clock(double ms)
        {
            var s = (int)Math.Max(0, ms / 1000);
            return $"{s / 60}:{s % 60:00}";
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
