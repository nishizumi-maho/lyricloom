using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace MusicBeePlugin
{
    /// <summary>Song position between polls: runs on a stopwatch and eases towards each new reading, so
    /// small jitter in the player position never makes the sweep jump.</summary>
    internal sealed class PlaybackClock
    {
        private readonly Stopwatch _watch = Stopwatch.StartNew();
        private double _basePos, _baseAt;
        public bool Playing { get; private set; }

        public double NowMs() => Playing ? _basePos + (_watch.Elapsed.TotalMilliseconds - _baseAt) : _basePos;

        public void Sync(double positionMs, bool playing)
        {
            var now = _watch.Elapsed.TotalMilliseconds;
            var predicted = NowMs();
            var drift = positionMs - predicted;
            _basePos = playing && Playing && Math.Abs(drift) < 250 ? predicted + drift * 0.15 : positionMs;
            _baseAt = now;
            Playing = playing;
        }
    }

    /// <summary>The karaoke window. F11 or a double-click toggles fullscreen, Esc leaves it, right-click
    /// opens the menu. In fullscreen the cursor hides after a moment, and Party Mode keeps the display
    /// awake while the song plays.</summary>
    internal sealed class KaraokeWindow : Window
    {
        private sealed class SceneLayer : FrameworkElement
        {
            private readonly KaraokeWindow _owner;
            private readonly KaraokeScene.Layer _layer;
            public SceneLayer(KaraokeWindow owner, KaraokeScene.Layer layer) { _owner = owner; _layer = layer; IsHitTestVisible = false; }
            protected override void OnRender(DrawingContext dc) => _owner._scene.Render(_layer, dc, RenderSize, _owner._songTime);
        }

        [DllImport("kernel32.dll")]
        private static extern uint SetThreadExecutionState(uint esFlags);
        private const uint ES_CONTINUOUS = 0x80000000, ES_SYSTEM_REQUIRED = 0x1, ES_DISPLAY_REQUIRED = 0x2;

        private readonly KaraokeScene _scene;
        private readonly PlaybackClock _clock = new PlaybackClock();
        private readonly SceneLayer _sky, _glow, _text;
        private readonly BlurEffect _blur = new BlurEffect { KernelType = KernelType.Gaussian, RenderingBias = RenderingBias.Performance };
        private readonly Func<(double PositionMs, bool Playing, float Volume, bool Mute)> _poll;
        private readonly Stopwatch _frameWatch = Stopwatch.StartNew();
        private readonly Grid _root;
        private readonly Border _toast;
        private readonly TextBlock _toastText;
        private readonly DispatcherTimer _cursorTimer;
        private readonly DispatcherTimer _toastTimer;
        private double _lastFrame, _lastPoll = -1e9;
        private double _songTime;
        private Settings _settings;
        private bool _fullscreen;
        private bool _awake;
        private Rect _restore;
        private readonly Action<Exception> _log;
        private readonly Border _hint;
        private readonly TextBlock _hintText;
        private MenuItem _lyricLoomItem;
        private bool _hintDismissed;
        private bool _lyricLoomEnabled;
        private string _songKey;
        private bool _closeForShutdown;
        private bool _closeForTrackChange;

        /// <summary>The commands the window's buttons and keys use (for tests).</summary>
        internal PlayerControls Controls => _controls;

        public event EventHandler SettingsRequested;
        public event EventHandler RecordRequested;
        public event EventHandler SkipIntroRequested;
        public event EventHandler LyricLoomRequested;
        /// <summary>Raised when the user closed the window themselves (not a shutdown or a track change).</summary>
        public event EventHandler UserClosed;
        public event Action<JapaneseMode> JapaneseModeChosen;
        /// <summary>The user nudged the lyric delay with [ or ]; the plugin saves it.</summary>
        public event Action<int> OffsetChanged;

        private readonly TransportBar _transport;
        private readonly PlayerControls _controls;
        private double _songMs;
        private bool _playing;
        private float _volume = 1f;
        private bool _mute;
        private Point _lastMouse;
        private bool _clickStarted;
        private Point _clickStart;
        private double _suppressDoubleClick;
        private double _loopStart = double.NaN, _loopEnd = double.NaN;
        private double _loopHoldUntil;

        public KaraokeWindow(Settings settings, Func<(double PositionMs, bool Playing, float Volume, bool Mute)> poll, PlayerControls controls,
                             bool showActivated = true, Action<Exception> log = null)
        {
            _log = log;
            ShowActivated = showActivated;
            RaiseFrameRate();
            // after any player command, read the position on the next frame instead of up to 200 ms later.
            // `player` is its own variable: the lambdas must call the plugin's commands, never this wrapper
            // (capturing a variable that later points at the wrapper made every seek call itself forever).
            var player = controls;
            _controls = new PlayerControls
            {
                PlayPause = () => { player.PlayPause?.Invoke(); _lastPoll = -1e9; },
                Previous = () => { player.Previous?.Invoke(); _lastPoll = -1e9; },
                Next = () => { player.Next?.Invoke(); _lastPoll = -1e9; },
                Seek = ms => { player.Seek?.Invoke(ms); _lastPoll = -1e9; },
                SetVolume = v => { player.SetVolume?.Invoke(v); _lastPoll = -1e9; },
                SetMute = m => { player.SetMute?.Invoke(m); _lastPoll = -1e9; }
            };
            _settings = settings;
            _poll = poll;
            _scene = new KaraokeScene(settings);
            Title = "Starry Karaoke";
            Background = Brushes.Black;
            MinWidth = 360;
            MinHeight = 240;
            Width = settings.WindowWidth > 100 ? settings.WindowWidth : 1100;
            Height = settings.WindowHeight > 100 ? settings.WindowHeight : 680;
            if (!double.IsNaN(settings.WindowLeft) && OnSomeScreen(settings.WindowLeft, settings.WindowTop, Width, Height))
            {
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = settings.WindowLeft;
                Top = settings.WindowTop;
            }
            else if (!PlaceOnSavedMonitor(settings.WindowMonitor))
                WindowStartupLocation = WindowStartupLocation.CenterScreen;

            _sky = new SceneLayer(this, KaraokeScene.Layer.Sky);
            _glow = new SceneLayer(this, KaraokeScene.Layer.Glow) { Effect = _blur, Opacity = 0.85 };
            _text = new SceneLayer(this, KaraokeScene.Layer.Text);
            _root = new Grid { Background = Brushes.Transparent, ClipToBounds = true };
            _root.Children.Add(_sky);
            _root.Children.Add(_glow);
            _root.Children.Add(_text);
            _transport = new TransportBar(_controls, _scene.Accent, _log);
            _root.Children.Add(_transport);

            _toastText = new TextBlock
            {
                Foreground = Brushes.White, FontSize = 14, TextAlignment = TextAlignment.Center,
                FontFamily = new FontFamily("Segoe UI, Yu Gothic UI")
            };
            _toast = new Border
            {
                Child = _toastText, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(0, 26, 0, 0), Padding = new Thickness(14, 7, 14, 7),
                CornerRadius = new CornerRadius(9), BorderThickness = new Thickness(0), Opacity = 0,
                IsHitTestVisible = false, Background = new SolidColorBrush(Color.FromArgb(205, 8, 8, 20))
            };
            _root.Children.Add(_toast);

            _hintText = new TextBlock
            {
                Text = "No word timing for this song. Make word-timed lyrics with LyricLoom.",
                Foreground = Brushes.White, FontSize = 13, VerticalAlignment = VerticalAlignment.Center,
                FontFamily = new FontFamily("Segoe UI, Yu Gothic UI")
            };
            var makeLyrics = new Button
            {
                Content = "Make with LyricLoom...", Margin = new Thickness(10, 0, 4, 0),
                Padding = new Thickness(8, 3, 8, 3), FontSize = 12,
                Background = new SolidColorBrush(Color.FromArgb(35, 255, 255, 255)),
                Foreground = Brushes.White, BorderBrush = new SolidColorBrush(Color.FromArgb(90, 255, 255, 255))
            };
            makeLyrics.Click += (s, e) => Safe.Run(() => LyricLoomRequested?.Invoke(this, EventArgs.Empty), _log);
            var dismissHint = new Button
            {
                Content = "\u00D7", Width = 24, Height = 22, Padding = new Thickness(0), FontSize = 13,
                Background = Brushes.Transparent, Foreground = Brushes.White, BorderThickness = new Thickness(0),
                ToolTip = "Dismiss"
            };
            dismissHint.Click += (s, e) => Safe.Run(() =>
            {
                _hintDismissed = true;
                _hint.Visibility = Visibility.Collapsed;
            }, _log);
            var hintRow = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            hintRow.Children.Add(_hintText);
            hintRow.Children.Add(makeLyrics);
            hintRow.Children.Add(dismissHint);
            _hint = new Border
            {
                Child = hintRow, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Bottom,
                Margin = new Thickness(0, 0, 0, 86), Padding = new Thickness(12, 5, 6, 5),
                CornerRadius = new CornerRadius(8), Background = new SolidColorBrush(Color.FromArgb(220, 12, 12, 30)),
                Visibility = Visibility.Collapsed
            };
            _root.Children.Add(_hint);

            _toastTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1.7) };
            _toastTimer.Tick += (s, e) => Safe.Run(() =>
            {
                _toastTimer.Stop();
                _toast.BeginAnimation(OpacityProperty, new DoubleAnimation(0, TimeSpan.FromMilliseconds(300))
                { EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseOut } });
            }, _log);
            _cursorTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1.5) };
            _cursorTimer.Tick += (s, e) => Safe.Run(() =>
            {
                _cursorTimer.Stop();
                if (_transport.IsMouseOver) { _cursorTimer.Start(); return; }
                if (_fullscreen) Mouse.OverrideCursor = Cursors.None;
            }, _log);

            MouseMove += (s, e) => Safe.Run(() =>
            {
                var p = e.GetPosition(this);
                if ((p - _lastMouse).Length < 2) return;   // ignore the jitter of a still mouse
                _lastMouse = p;
                _transport.OnWindowMouseMove(p, ActualHeight);
                OnMouseActivity();
            }, _log);
            MouseLeave += (s, e) => Safe.Run(() => _transport.Show(false), _log);
            MouseLeftButtonDown += OnMouseDown;
            MouseLeftButtonUp += OnMouseUp;
            MouseDoubleClick += OnDoubleClick;
            Content = _root;
            TextOptions.SetTextRenderingMode(this, TextRenderingMode.Grayscale);
            RenderOptions.SetEdgeMode(_sky, EdgeMode.Unspecified);

            ContextMenu = BuildMenu();
            PreviewKeyDown += OnKey;   // preview: arrows and space reach us before any control can take them
            Loaded += (s, e) => Safe.Run(() => { if (settings.Fullscreen) SetFullscreen(true); }, _log);
            CompositionTarget.Rendering += OnFrame;
            Closed += (s, e) => Safe.Run(() =>
            {
                CompositionTarget.Rendering -= OnFrame;
                _cursorTimer.Stop();
                _toastTimer.Stop();
                Mouse.OverrideCursor = null;
                KeepAwake(false);
            }, _log);
            Deactivated += (s, e) => Safe.Run(() => Mouse.OverrideCursor = null, _log);
            ApplyBlur();
        }

        private static bool OnSomeScreen(double l, double t, double w, double h)
        {
            var r = new Rect(l, t, w, h);
            var v = new Rect(SystemParameters.VirtualScreenLeft, SystemParameters.VirtualScreenTop,
                             SystemParameters.VirtualScreenWidth, SystemParameters.VirtualScreenHeight);
            return r.IntersectsWith(v) && r.Left < v.Right - 60 && r.Top < v.Bottom - 60;
        }

        /// <summary>When the saved position is no longer on any screen, open on the monitor the window
        /// was last on, centred and inside its work area.</summary>
        private bool PlaceOnSavedMonitor(string device)
        {
            if (string.IsNullOrEmpty(device)) return false;
            var screen = System.Windows.Forms.Screen.AllScreens.FirstOrDefault(s =>
                string.Equals(s.DeviceName, device, StringComparison.OrdinalIgnoreCase));
            if (screen == null) return false;
            try
            {
                var scale = VisualTreeHelper.GetDpi(this).DpiScaleX;
                if (scale <= 0.1) scale = 1.0;
                var dip = 1.0 / scale;
                var a = screen.WorkingArea;
                var area = new Rect(a.Left * dip, a.Top * dip, a.Width * dip, a.Height * dip);
                Left = area.Left + Math.Max(0, (area.Width - Width) / 2);
                Top = area.Top + Math.Max(0, (area.Height - Height) / 2);
                WindowStartupLocation = WindowStartupLocation.Manual;
                return OnSomeScreen(Left, Top, Width, Height);
            }
            catch (Exception e)
            {
                _log?.Invoke(e);
                return false;
            }
        }

        protected override void OnClosing(CancelEventArgs e)
        {
            try
            {
                var appShuttingDown = Application.Current != null &&
                                      Application.Current.Dispatcher.HasShutdownStarted;
                if (!_closeForShutdown && !_closeForTrackChange && !appShuttingDown)
                    UserClosed?.Invoke(this, EventArgs.Empty);
            }
            catch (Exception ex)
            {
                _log?.Invoke(ex);
            }
            base.OnClosing(e);
        }

        /// <summary>Closes the window because MusicBee is shutting down; not a user dismissal.</summary>
        internal void CloseForShutdown()
        {
            _closeForShutdown = true;
            Close();
        }

        /// <summary>Closes the window because the next song has no supported lyrics; not a user dismissal.</summary>
        internal void CloseForTrackChange()
        {
            _closeForTrackChange = true;
            Close();
        }

        public void ShowMessage(string text) => ShowToast(text);

        public void SetSong(List<KaraokeLine> lines, string title, double songMs, string songKey = null)
        {
            if (songKey != null && !string.Equals(songKey, _songKey, StringComparison.OrdinalIgnoreCase))
            {
                _songKey = songKey;
                _hintDismissed = false;
            }
            _scene.SetSong(lines, title, songMs);
            _songMs = songMs;
            _lastPoll = -1e9;
            _loopStart = _loopEnd = double.NaN;
            _scene.LoopStart = _scene.LoopEnd = double.NaN;
            _transport.SetAccent(_scene.Accent);
        }

        /// <summary>Shows the LyricLoom hint for a song without word timing. The hint is dismissible and
        /// returns for the next song.</summary>
        public void SetWordTimingAvailable(bool hasWordTiming, bool canCreateLyrics)
        {
            _lyricLoomEnabled = canCreateLyrics;
            UpdateLyricLoomMenu();
            _hint.Visibility = canCreateLyrics && !hasWordTiming && !_hintDismissed
                ? Visibility.Visible : Visibility.Collapsed;
        }

        /// <summary>Enables the LyricLoom menu item only while a song is playing.</summary>
        public void SetLyricLoomEnabled(bool enabled)
        {
            _lyricLoomEnabled = enabled;
            UpdateLyricLoomMenu();
        }

        private void UpdateLyricLoomMenu()
        {
            if (_lyricLoomItem != null) _lyricLoomItem.IsEnabled = _lyricLoomEnabled;
        }

        public void SetNextSong(string next) => _scene.SetNextSong(next);

        public void ApplySettings(Settings s)
        {
            _settings = s;
            _scene.Apply(s);
            _scene.LyricsOnly = _fullscreen && s.FullscreenLyricsOnly;
            _transport.SetAccent(_scene.Accent);
            ApplyBlur();
            if (!s.PartyMode) KeepAwake(false);
        }

        /// <summary>Rebuilds the right-click menu after a change that affects its check marks (the
        /// Japanese mode). Colour and slider previews do not need this.</summary>
        public void RefreshMenu() => ContextMenu = BuildMenu();

        private void ApplyBlur() => _glow.Visibility = _settings.Glow ? Visibility.Visible : Visibility.Collapsed;

        /// <summary>Window bounds as they should be saved (the normal ones while fullscreen).</summary>
        public void StoreBounds(Settings s)
        {
            var b = _fullscreen ? _restore : (WindowState == WindowState.Normal ? new Rect(Left, Top, Width, Height) : RestoreBounds);
            if (b.Width > 0 && b.Height > 0)
            {
                s.WindowLeft = b.Left; s.WindowTop = b.Top; s.WindowWidth = b.Width; s.WindowHeight = b.Height;
            }
            s.WindowMonitor = CurrentMonitor();
            s.Fullscreen = _fullscreen;
        }

        private string CurrentMonitor()
        {
            try
            {
                var handle = new WindowInteropHelper(this).Handle;
                if (handle != IntPtr.Zero) return System.Windows.Forms.Screen.FromHandle(handle).DeviceName;
            }
            catch (Exception) { }
            try { return System.Windows.Forms.Screen.FromPoint(new System.Drawing.Point((int)Left, (int)Top)).DeviceName; }
            catch (Exception) { return ""; }
        }

        // ---- frame rate: WPF paints at most at its desired frame rate (60 unless raised), so raise it to
        // the monitor's refresh rate; a fixed WindowFps below that skips frames instead.

        [System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
        private static extern bool EnumDisplaySettings(string device, int mode, ref DevMode devMode);

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential, CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
        private struct DevMode
        {
            [System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
            public short SpecVersion, DriverVersion, Size, DriverExtra;
            public int Fields, PositionX, PositionY, DisplayOrientation, DisplayFixedOutput;
            public short Color, Duplex, YResolution, TTOption, Collate;
            [System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.ByValTStr, SizeConst = 32)] public string FormName;
            public short LogPixels;
            public int BitsPerPel, PelsWidth, PelsHeight, DisplayFlags, DisplayFrequency;
        }

        /// <summary>Highest refresh rate among the monitors (60 if unknown).</summary>
        public static int MonitorRefreshRate()
        {
            var best = 0;
            foreach (var screen in System.Windows.Forms.Screen.AllScreens)
            {
                var dm = new DevMode { Size = (short)System.Runtime.InteropServices.Marshal.SizeOf(typeof(DevMode)) };
                if (EnumDisplaySettings(screen.DeviceName, -1, ref dm) && dm.DisplayFrequency > 1) best = Math.Max(best, dm.DisplayFrequency);
            }
            return best > 0 ? best : 60;
        }

        private static bool _frameRateRaised;

        private static void RaiseFrameRate()
        {
            if (_frameRateRaised) return;
            _frameRateRaised = true;
            try
            {
                System.Windows.Media.Animation.Timeline.DesiredFrameRateProperty.OverrideMetadata(
                    typeof(System.Windows.Media.Animation.Timeline),
                    new FrameworkPropertyMetadata { DefaultValue = MonitorRefreshRate() });
            }
            catch (Exception) { }   // already set in this process
        }

        private void OnFrame(object sender, EventArgs e)
        {
            Safe.Run(() =>
            {
                if (WindowState == WindowState.Minimized || !IsVisible) return;
                var now = _frameWatch.Elapsed.TotalSeconds;
                if (_settings.WindowFps > 0 && now - _lastFrame < 1.0 / _settings.WindowFps - 0.0015) return;
                var dt = Math.Min(0.25, now - _lastFrame);
                _lastFrame = now;
                if (now - _lastPoll > 0.2)
                {
                    _lastPoll = now;
                    try
                    {
                        var (pos, playing, volume, mute) = _poll();
                        _clock.Sync(pos, playing);
                        _playing = playing;
                        _volume = volume;
                        _mute = mute;
                    }
                    catch (Exception) { }
                }
                _songTime = _clock.NowMs() - _settings.LyricsOffsetMs;
                KeepAwake(_settings.PartyMode && _playing);
                CheckLoop(now);

                var size = _text.RenderSize;
                _blur.Radius = Math.Max(8, Math.Min(40, size.Height / 26));
                _scene.Update(dt, _songTime, size);
                _sky.InvalidateVisual();
                _glow.InvalidateVisual();
                _text.InvalidateVisual();
                _transport.Update(_clock.NowMs(), _songMs, _playing, _volume, _mute);
                _scene.HideProgress = _transport.IsShown;
            }, _log);
        }

        private void CheckLoop(double now)
        {
            if (double.IsNaN(_loopStart) || double.IsNaN(_loopEnd)) return;
            if (_songTime < _loopEnd + 120 || now < _loopHoldUntil) return;
            var target = Math.Max(0, _loopStart + _settings.LyricsOffsetMs);
            if (_songMs > 0) target = Math.Min(target, Math.Max(0, _songMs - 200));
            _controls.Seek?.Invoke(target);
            _loopHoldUntil = now + 0.65;
        }

        private void KeepAwake(bool on)
        {
            if (on == _awake) return;
            _awake = on;
            try
            {
                SetThreadExecutionState(on ? ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED : ES_CONTINUOUS);
            }
            catch (Exception) { }
        }

        private void OnKey(object sender, KeyEventArgs e)
        {
            Safe.Run(() =>
            {
                if (e.Key == Key.F11) SetFullscreen(!_fullscreen);
                else if (e.Key == Key.Escape && _fullscreen) SetFullscreen(false);
                else if (e.Key == Key.P) SkipIntroRequested?.Invoke(this, EventArgs.Empty);
                else if (e.Key == Key.Space) { _controls.PlayPause?.Invoke(); _transport.Show(true); }
                else if (e.Key == Key.Left) { _transport.Jump(-10000); _transport.Show(true); }
                else if (e.Key == Key.Right) { _transport.Jump(10000); _transport.Show(true); }
                else if (e.Key == Key.L) ToggleLoop(Keyboard.Modifiers.HasFlag(ModifierKeys.Shift));
                else if (e.Key == Key.OemOpenBrackets) NudgeOffset(-100);
                else if (e.Key == Key.OemCloseBrackets) NudgeOffset(100);
                else if ((e.Key == Key.D0 || e.Key == Key.NumPad0) && Keyboard.Modifiers.HasFlag(ModifierKeys.Control)) NudgeOffset(-_settings.LyricsOffsetMs);
                else if (e.Key == Key.M) ToggleMute();
                else if (e.Key == Key.F12) SaveScreenshot();
                else return;
                e.Handled = true;
            }, _log);
        }

        private void NudgeOffset(int delta)
        {
            var value = Math.Max(-10000, Math.Min(10000, _settings.LyricsOffsetMs + delta));
            _settings.LyricsOffsetMs = value;
            OffsetChanged?.Invoke(value);
            ShowToast(value == 0 ? "Lyrics delay reset" : $"Lyrics delay {value:+0;-0;0} ms");
        }

        private void ToggleMute()
        {
            _mute = !_mute;
            _controls.SetMute?.Invoke(_mute);
            ShowToast(_mute ? "Muted" : "Sound on");
        }

        private void ToggleLoop(bool section)
        {
            if (!double.IsNaN(_loopStart))
            {
                _loopStart = _loopEnd = double.NaN;
                _scene.LoopStart = _scene.LoopEnd = double.NaN;
                ShowToast("Loop off");
                RefreshMenu();
                return;
            }
            var index = _scene.CurrentLine(_songTime);
            if (index < 0) index = 0;
            var (start, end) = _scene.LineRange(index, section ? 4 : 1);
            if (double.IsNaN(start) || double.IsNaN(end)) { ShowToast("No lyrics to loop"); return; }
            if (_songMs > 0) end = Math.Min(end, _songMs);
            _loopStart = start;
            _loopEnd = end;
            _scene.LoopStart = start;
            _scene.LoopEnd = end;
            ShowToast(section ? "Looping this section" : "Looping this line");
            _controls.Seek?.Invoke(Math.Max(0, start + _settings.LyricsOffsetMs));
            _loopHoldUntil = _frameWatch.Elapsed.TotalSeconds + 0.7;
            RefreshMenu();
        }

        private void SaveScreenshot()
        {
            try
            {
                var w = (int)Math.Round(ActualWidth);
                var h = (int)Math.Round(ActualHeight);
                if (w < 2 || h < 2) return;
                _toast.BeginAnimation(OpacityProperty, null);
                _toast.Opacity = 0;
                var bmp = new RenderTargetBitmap(w, h, 96, 96, PixelFormats.Pbgra32);
                bmp.Render(_root);
                var dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyPictures), "Starry Karaoke");
                Directory.CreateDirectory(dir);
                var path = Path.Combine(dir, $"Starry Karaoke {DateTime.Now:yyyy-MM-dd HH-mm-ss}.png");
                var enc = new PngBitmapEncoder();
                enc.Frames.Add(BitmapFrame.Create(bmp));
                using (var f = File.Create(path)) enc.Save(f);
                try { Clipboard.SetImage(bmp); } catch (Exception) { }
                ShowToast("Screenshot saved");
            }
            catch (Exception)
            {
                ShowToast("Could not save the screenshot");
            }
        }

        private void ShowToast(string text)
        {
            _toastText.Text = text;
            _toast.BeginAnimation(OpacityProperty, null);
            _toast.Opacity = 1;
            _toastTimer.Stop();
            _toastTimer.Start();
        }

        private void OnMouseActivity()
        {
            Mouse.OverrideCursor = null;
            _cursorTimer.Stop();
            if (_fullscreen) _cursorTimer.Start();
        }

        private void OnMouseDown(object sender, MouseButtonEventArgs e)
        {
            Safe.Run(() =>
            {
                if (e.ChangedButton != MouseButton.Left || _transport.IsMouseOver) return;
                _clickStarted = true;
                _clickStart = e.GetPosition(this);
            }, _log);
        }

        private void OnMouseUp(object sender, MouseButtonEventArgs e)
        {
            Safe.Run(() =>
            {
                if (!_clickStarted || e.ChangedButton != MouseButton.Left) { _clickStarted = false; return; }
                _clickStarted = false;
                if (_transport.IsMouseOver) return;
                var p = e.GetPosition(this);
                if ((p - _clickStart).Length > 5) return;   // a drag, not a click
                var index = _scene.LineAt(p, _text.RenderSize, _songTime);
                if (index < 0) return;
                var start = _scene.LineStart(index);
                if (double.IsNaN(start)) return;
                _suppressDoubleClick = _frameWatch.Elapsed.TotalSeconds + 0.45;
                _controls.Seek?.Invoke(Math.Max(0, start + _settings.LyricsOffsetMs));
                ShowToast("Jumped to line");
                e.Handled = true;
            }, _log);
        }

        private void OnDoubleClick(object sender, MouseButtonEventArgs e)
        {
            Safe.Run(() =>
            {
                if (e.ChangedButton != MouseButton.Left || _transport.IsMouseOver) return;
                if (_frameWatch.Elapsed.TotalSeconds < _suppressDoubleClick) return;
                SetFullscreen(!_fullscreen);
            }, _log);
        }

        internal void SetFullscreen(bool on)
        {
            if (on == _fullscreen) return;
            if (on)
            {
                _restore = WindowState == WindowState.Normal ? new Rect(Left, Top, Width, Height) : RestoreBounds;
                WindowState = WindowState.Normal;
                WindowStyle = WindowStyle.None;
                ResizeMode = ResizeMode.NoResize;
                WindowState = WindowState.Maximized;
                _cursorTimer.Stop();
                _cursorTimer.Start();
            }
            else
            {
                WindowState = WindowState.Normal;
                WindowStyle = WindowStyle.SingleBorderWindow;
                ResizeMode = ResizeMode.CanResize;
                if (_restore.Width > 0) { Left = _restore.Left; Top = _restore.Top; Width = _restore.Width; Height = _restore.Height; }
                _cursorTimer.Stop();
                Mouse.OverrideCursor = null;
            }
            _fullscreen = on;
            _scene.LyricsOnly = on && _settings.FullscreenLyricsOnly;
            ContextMenu = BuildMenu();
        }

        private ContextMenu BuildMenu()
        {
            var menu = new ContextMenu();
            var full = new MenuItem { Header = _fullscreen ? "Exit fullscreen (Esc)" : "Fullscreen (F11)" };
            full.Click += (s, e) => Safe.Run(() => SetFullscreen(!_fullscreen), _log);
            menu.Items.Add(full);
            var skip = new MenuItem { Header = "Skip intro (P)" };
            skip.Click += (s, e) => Safe.Run(() => SkipIntroRequested?.Invoke(this, EventArgs.Empty), _log);
            menu.Items.Add(skip);

            var loop = new MenuItem { Header = "Loop current line (L)", IsCheckable = true, IsChecked = !double.IsNaN(_loopStart) };
            loop.Click += (s, e) => Safe.Run(() => ToggleLoop(false), _log);
            menu.Items.Add(loop);
            var section = new MenuItem { Header = "Loop this section (Shift+L)" };
            section.Click += (s, e) => Safe.Run(() => ToggleLoop(true), _log);
            menu.Items.Add(section);
            var shot = new MenuItem { Header = "Save screenshot (F12)" };
            shot.Click += (s, e) => Safe.Run(SaveScreenshot, _log);
            menu.Items.Add(shot);

            var jp = new MenuItem { Header = "Japanese" };
            foreach (var (mode, label) in new[] { (JapaneseMode.RomajiOnly, "Romaji only"),
                                                  (JapaneseMode.JapaneseAndRomaji, "Japanese + romaji"),
                                                  (JapaneseMode.JapaneseOnly, "Japanese only") })
            {
                var item = new MenuItem { Header = label, IsCheckable = true, IsChecked = _settings.Japanese == mode };
                item.Click += (s, e) => Safe.Run(() => JapaneseModeChosen?.Invoke(mode), _log);
                jp.Items.Add(item);
            }
            menu.Items.Add(jp);

            _lyricLoomItem = new MenuItem
            {
                Header = "Make word-timed lyrics with LyricLoom...",
                IsEnabled = _lyricLoomEnabled
            };
            _lyricLoomItem.Click += (s, e) => Safe.Run(() => LyricLoomRequested?.Invoke(this, EventArgs.Empty), _log);
            menu.Items.Add(_lyricLoomItem);

            var record = new MenuItem { Header = "Record song video..." };
            record.Click += (s, e) => Safe.Run(() => RecordRequested?.Invoke(this, EventArgs.Empty), _log);
            menu.Items.Add(record);

            var settings = new MenuItem { Header = "Settings..." };
            settings.Click += (s, e) => Safe.Run(() => SettingsRequested?.Invoke(this, EventArgs.Empty), _log);
            menu.Items.Add(settings);
            menu.Items.Add(new Separator());
            var close = new MenuItem { Header = "Close" };
            close.Click += (s, e) => Safe.Run(Close, _log);
            menu.Items.Add(close);
            return menu;
        }
    }
}
