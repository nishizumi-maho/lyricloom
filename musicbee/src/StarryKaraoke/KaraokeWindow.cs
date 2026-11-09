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
        private double _lastFrame, _lastPoll = -1e9, _lastOcclusionCheck = -1e9;
        private double _songTime;
        private int _songOffsetMs;
        private Settings _settings;
        private bool _fullscreen;
        private bool _awake;
        private bool _framesSubscribed;
        private bool _renderSuspended;
        private bool? _pollingNotified;
        private int _monitorHz;
        private Rect _restore;
        private WindowState _restoreState = WindowState.Normal;
        private readonly Action<Exception> _log;
        private readonly Border _hint;
        private readonly TextBlock _hintText;
        private readonly Border _lyricLoomStatus;
        private readonly TextBlock _lyricLoomStatusText;
        private MenuItem _lyricLoomItem;
        private bool _hintDismissed;
        private bool _lyricLoomPending;
        private bool _hasWordTiming;
        private bool _lyricLoomEnabled;
        private string _songKey;
        private bool _closeForShutdown;
        private bool _closeForTrackChange;

        /// <summary>The commands the window's buttons and keys use (for tests).</summary>
        internal PlayerControls Controls => _controls;

        /// <summary>The DPI the scene uses for text layout (for tests).</summary>
        internal double ScenePixelsPerDip => _scene.PixelsPerDip;

        /// <summary>Whether the LyricLoom waiting status is showing (for tests).</summary>
        internal bool IsLyricLoomStatusVisible => _lyricLoomStatus.Visibility == Visibility.Visible;

        /// <summary>Whether the word-timing hint is showing (for tests).</summary>
        internal bool IsHintVisible => _hint.Visibility == Visibility.Visible;

        public event EventHandler SettingsRequested;
        public event EventHandler RecordRequested;
        public event EventHandler SkipIntroRequested;
        public event EventHandler LyricLoomRequested;
        public event EventHandler DiagnosticsRequested;
        /// <summary>Raised when the user closed the window themselves (not a shutdown or a track change).</summary>
        public event EventHandler UserClosed;
        public event Action<JapaneseMode> JapaneseModeChosen;
        /// <summary>The user nudged this song's delay with [ or ]; the plugin saves it.</summary>
        public event Action<int> SongOffsetChanged;
        public event Action<string> FullscreenMonitorChosen;
        public event Action<bool> FullscreenTopmostChanged;
        /// <summary>False while the window is minimised, hidden or fully covered by another window;
        /// the plugin stops its player poll timer then.</summary>
        public event Action<bool> PollingNeeded;

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
        private LoopMode _loopMode = LoopMode.Off;
        private double _loopHoldUntil;

        public KaraokeWindow(Settings settings, Func<(double PositionMs, bool Playing, float Volume, bool Mute)> poll, PlayerControls controls,
                             bool showActivated = true, Action<Exception> log = null)
        {
            _log = log;
            ShowActivated = showActivated;
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
            _monitorHz = FrameRatePolicy.DefaultFps;
            _scene = new KaraokeScene(settings);
            UpdateTextDpi();
            Title = Strings.WindowTitle;
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
                Text = Strings.NoWordTimingHint,
                Foreground = Brushes.White, FontSize = 13, VerticalAlignment = VerticalAlignment.Center,
                FontFamily = new FontFamily("Segoe UI, Yu Gothic UI")
            };
            var makeLyrics = new Button
            {
                Content = Strings.MakeWithLyricLoom, Margin = new Thickness(10, 0, 4, 0),
                Padding = new Thickness(8, 3, 8, 3), FontSize = 12,
                Background = new SolidColorBrush(Color.FromArgb(35, 255, 255, 255)),
                Foreground = Brushes.White, BorderBrush = new SolidColorBrush(Color.FromArgb(90, 255, 255, 255))
            };
            makeLyrics.Click += (s, e) => Safe.Run(() => LyricLoomRequested?.Invoke(this, EventArgs.Empty), _log);
            var dismissHint = new Button
            {
                Content = "\u00D7", Width = 24, Height = 22, Padding = new Thickness(0), FontSize = 13,
                Background = Brushes.Transparent, Foreground = Brushes.White, BorderThickness = new Thickness(0),
                ToolTip = Strings.Dismiss
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

            _lyricLoomStatusText = new TextBlock
            {
                Text = Strings.LyricLoomPending, Foreground = Brushes.White, FontSize = 13,
                TextAlignment = TextAlignment.Center,
                FontFamily = new FontFamily("Segoe UI, Yu Gothic UI")
            };
            _lyricLoomStatus = new Border
            {
                Child = _lyricLoomStatusText, HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Bottom, Margin = new Thickness(0, 0, 0, 86),
                Padding = new Thickness(14, 6, 14, 6), CornerRadius = new CornerRadius(8),
                Background = new SolidColorBrush(Color.FromArgb(220, 12, 12, 30)),
                Visibility = Visibility.Collapsed
            };
            _root.Children.Add(_lyricLoomStatus);

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
            Loaded += (s, e) => Safe.Run(() =>
            {
                UpdateTextDpi();
                if (settings.Fullscreen) SetFullscreen(true);
                UpdateRenderState();
            }, _log);
            Closed += (s, e) => Safe.Run(() =>
            {
                StopFrames();
                NotifyPolling(false);
                _cursorTimer.Stop();
                _toastTimer.Stop();
                Mouse.OverrideCursor = null;
                KeepAwake(false);
            }, _log);
            IsVisibleChanged += (s, e) => Safe.Run(UpdateRenderState, _log);
            StateChanged += (s, e) => Safe.Run(UpdateRenderState, _log);
            LocationChanged += (s, e) => Safe.Run(() =>
            {
                UpdateTextDpi();
                if (_settings.WindowFps == 0) _monitorHz = MonitorRefreshRate(CurrentScreen());
            }, _log);
            DpiChanged += (s, e) => Safe.Run(() =>
            {
                UpdateTextDpi();
                if (_fullscreen) ApplyFullscreenBounds();
            }, _log);
            Activated += (s, e) => Safe.Run(UpdateRenderState, _log);
            Deactivated += (s, e) => Safe.Run(() =>
            {
                Mouse.OverrideCursor = null;
                UpdateRenderState();
            }, _log);
            ApplyBlur();
        }

        private static bool OnSomeScreen(double l, double t, double w, double h)
        {
            var r = new Rect(l, t, w, h);
            var v = new Rect(SystemParameters.VirtualScreenLeft, SystemParameters.VirtualScreenTop,
                             SystemParameters.VirtualScreenWidth, SystemParameters.VirtualScreenHeight);
            return r.IntersectsWith(v) && r.Left < v.Right - 60 && r.Top < v.Bottom - 60;
        }

        /// <summary>FormattedText measured at 96 DPI is blurry on a scaled display. The window follows
        /// its current monitor's DPI; the offscreen recorder and the Preview tool keep 1.0.</summary>
        private void UpdateTextDpi()
        {
            try { _scene.PixelsPerDip = VisualTreeHelper.GetDpi(this).PixelsPerDip; }
            catch (Exception e) { _log?.Invoke(e); }
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

        public void SetSong(List<KaraokeLine> lines, string title, double songMs, string songKey = null,
                            int songOffsetMs = 0)
        {
            if (songKey != null && !string.Equals(songKey, _songKey, StringComparison.OrdinalIgnoreCase))
            {
                _songKey = songKey;
                _hintDismissed = false;
                ClearLyricLoomPending();
            }
            _scene.SetSong(lines, title, songMs);
            _songMs = songMs;
            SetSongOffset(songOffsetMs);
            _lastPoll = -1e9;
            ClearLoop();
            _transport.SetAccent(_scene.Accent);
        }

        /// <summary>This song's delay. The global Settings.LyricsOffsetMs remains the base added to it.</summary>
        public int SongOffsetMs => _songOffsetMs;

        private int EffectiveOffsetMs => _settings.LyricsOffsetMs + _songOffsetMs;

        public void SetSongOffset(int offsetMs)
        {
            _songOffsetMs = Math.Max(-10000, Math.Min(10000, offsetMs));
            _transport.SetSongOffset(_songOffsetMs);
        }

        /// <summary>Shows the LyricLoom hint for a song without word timing. The hint is dismissible and
        /// returns for the next song.</summary>
        public void SetWordTimingAvailable(bool hasWordTiming, bool canCreateLyrics)
        {
            _lyricLoomEnabled = canCreateLyrics;
            _hasWordTiming = hasWordTiming;
            UpdateLyricLoomMenu();
            UpdateHintVisibility();
        }

        /// <summary>After the song was sent to LyricLoom: a small status stays up until the sidecar
        /// arrives (the plugin clears it) or the song changes.</summary>
        internal void ShowLyricLoomPending()
        {
            _lyricLoomPending = true;
            _lyricLoomStatusText.Text = Strings.LyricLoomPending;
            _lyricLoomStatus.Visibility = Visibility.Visible;
            UpdateHintVisibility();
        }

        internal void ClearLyricLoomPending()
        {
            _lyricLoomPending = false;
            _lyricLoomStatus.Visibility = Visibility.Collapsed;
            UpdateHintVisibility();
        }

        private void UpdateHintVisibility()
        {
            _hint.Visibility = _lyricLoomEnabled && !_hasWordTiming && !_hintDismissed && !_lyricLoomPending
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
            var monitorChanged = !string.Equals(_settings.FullscreenMonitor, s.FullscreenMonitor,
                                                StringComparison.OrdinalIgnoreCase);
            _settings = s;
            _scene.Apply(s);
            _scene.LyricsOnly = _fullscreen && s.FullscreenLyricsOnly;
            _transport.SetAccent(_scene.Accent);
            if (s.WindowFps == 0) _monitorHz = MonitorRefreshRate(CurrentScreen());
            ApplyBlur();
            if (_fullscreen)
            {
                Topmost = s.FullscreenTopmost;
                if (monitorChanged) ApplyFullscreenBounds();
            }
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
            if (!_fullscreen) s.WindowMonitor = CurrentMonitor();
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

        // ---- frame rate: the scene is gated by FrameRatePolicy. Nothing here touches
        // Timeline.DesiredFrameRateProperty, which is process-wide and would also change other WPF
        // plugins in MusicBee.

        [System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
        private static extern bool EnumDisplaySettings(string device, int mode, ref DevMode devMode);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern IntPtr GetWindow(IntPtr hWnd, uint command);
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool GetWindowRect(IntPtr hWnd, out NativeRect rect);
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hWnd);
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool IsIconic(IntPtr hWnd);
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool SetWindowPos(IntPtr hWnd, IntPtr insertAfter, int x, int y, int cx, int cy, uint flags);

        private const uint GW_HWNDPREV = 3;
        private const uint SWP_NOSIZE = 0x0001, SWP_NOMOVE = 0x0002, SWP_NOZORDER = 0x0004, SWP_FRAMECHANGED = 0x0020;

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        private struct NativeRect
        {
            public int Left, Top, Right, Bottom;
        }

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

        /// <summary>Refresh rate of the monitor the window is on (60 if unknown). "Display" uses this
        /// monitor only, never the highest rate among all attached screens.</summary>
        public static int MonitorRefreshRate(System.Windows.Forms.Screen screen)
        {
            if (screen == null) return FrameRatePolicy.DefaultFps;
            try
            {
                var dm = new DevMode { Size = (short)System.Runtime.InteropServices.Marshal.SizeOf(typeof(DevMode)) };
                if (EnumDisplaySettings(screen.DeviceName, -1, ref dm) && dm.DisplayFrequency > 1)
                    return dm.DisplayFrequency;
            }
            catch (Exception) { }
            return FrameRatePolicy.DefaultFps;
        }

        private System.Windows.Forms.Screen CurrentScreen()
        {
            try
            {
                var handle = new WindowInteropHelper(this).Handle;
                if (handle != IntPtr.Zero) return System.Windows.Forms.Screen.FromHandle(handle);
            }
            catch (Exception) { }
            try
            {
                return System.Windows.Forms.Screen.FromPoint(
                    new System.Drawing.Point((int)Math.Round(Left), (int)Math.Round(Top)));
            }
            catch (Exception) { return System.Windows.Forms.Screen.PrimaryScreen; }
        }

        /// <summary>Starts or stops repainting and tells the plugin whether polling is worth doing.
        /// Minimised/hidden unsubscribes; a fully covered window keeps the cheap rendering callback
        /// (so it notices when the other window moves) but does no scene work and stops polling.</summary>
        private void UpdateRenderState()
        {
            if (!IsVisible || WindowState == WindowState.Minimized)
            {
                StopFrames();
                NotifyPolling(false);
                KeepAwake(false);
                return;
            }
            _monitorHz = MonitorRefreshRate(CurrentScreen());
            _renderSuspended = IsFullyCovered();
            if (_renderSuspended) KeepAwake(false);
            StartFrames();
            NotifyPolling(!_renderSuspended);
        }

        private void StartFrames()
        {
            if (_framesSubscribed) return;
            CompositionTarget.Rendering += OnFrame;
            _framesSubscribed = true;
        }

        private void StopFrames()
        {
            if (!_framesSubscribed) return;
            CompositionTarget.Rendering -= OnFrame;
            _framesSubscribed = false;
        }

        private void NotifyPolling(bool allowed)
        {
            if (_pollingNotified == allowed) return;
            _pollingNotified = allowed;
            try { PollingNeeded?.Invoke(allowed); }
            catch (Exception e) { _log?.Invoke(e); }
        }

        /// <summary>True when another visible top-level window covers this window's whole rectangle.
        /// This is what makes rendering stop behind a maximised browser or a game.</summary>
        private bool IsFullyCovered()
        {
            try
            {
                var handle = new WindowInteropHelper(this).Handle;
                if (handle == IntPtr.Zero) return false;
                NativeRect mine;
                if (!GetWindowRect(handle, out mine)) return false;
                var previous = GetWindow(handle, GW_HWNDPREV);
                for (var guard = 0; previous != IntPtr.Zero && guard < 256; guard++)
                {
                    if (IsWindowVisible(previous) && !IsIconic(previous))
                    {
                        NativeRect other;
                        if (GetWindowRect(previous, out other) &&
                            other.Left <= mine.Left + 2 && other.Top <= mine.Top + 2 &&
                            other.Right >= mine.Right - 2 && other.Bottom >= mine.Bottom - 2)
                            return true;
                    }
                    previous = GetWindow(previous, GW_HWNDPREV);
                }
            }
            catch (Exception) { }
            return false;
        }

        private void OnFrame(object sender, EventArgs e)
        {
            Safe.Run(() =>
            {
                if (WindowState == WindowState.Minimized || !IsVisible)
                {
                    StopFrames();
                    NotifyPolling(false);
                    return;
                }
                var now = _frameWatch.Elapsed.TotalSeconds;
                if (now - _lastOcclusionCheck > 0.5)
                {
                    _lastOcclusionCheck = now;
                    var covered = IsFullyCovered();
                    if (covered != _renderSuspended)
                    {
                        _renderSuspended = covered;
                        if (covered) KeepAwake(false);
                        NotifyPolling(!covered);
                    }
                }
                if (_renderSuspended) return;
                var fps = FrameRatePolicy.EffectiveFps(_settings.WindowFps, _monitorHz, _playing,
                                                        false, false, false);
                if (fps <= 0) return;
                if (now - _lastFrame < 1.0 / fps - 0.0015) return;
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
                _songTime = _clock.NowMs() - EffectiveOffsetMs;
                KeepAwake(_settings.PartyMode && _playing);
                CheckLoop(now);

                var size = _text.RenderSize;
                _blur.Radius = Math.Max(8, Math.Min(40, size.Height / 26));
                _scene.Update(dt, _songTime, size);
                _sky.InvalidateVisual();
                _glow.InvalidateVisual();
                _text.InvalidateVisual();
                _transport.Update(_clock.NowMs(), _songMs, _playing, _volume, _mute, _songOffsetMs);
                _scene.HideProgress = _transport.IsShown;
            }, _log);
        }

        private void CheckLoop(double now)
        {
            if (double.IsNaN(_loopStart) || double.IsNaN(_loopEnd)) return;
            if (_songTime < _loopEnd + 120 || now < _loopHoldUntil) return;
            var target = Math.Max(0, _loopStart + EffectiveOffsetMs);
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
                else if ((e.Key == Key.D0 || e.Key == Key.NumPad0) &&
                         Keyboard.Modifiers.HasFlag(ModifierKeys.Control)) ResetOffset();
                else if (e.Key == Key.M) ToggleMute();
                else if (e.Key == Key.F12) SaveScreenshot();
                else return;
                e.Handled = true;
            }, _log);
        }

        /// <summary>[ and ] change this song's own delay; the global Settings.LyricsOffsetMs stays
        /// the base, and the user's .lrc is never touched.</summary>
        internal void NudgeOffset(int delta)
        {
            var value = Math.Max(-10000, Math.Min(10000, _songOffsetMs + delta));
            if (value == _songOffsetMs)
            {
                ShowToast(_songOffsetMs == 0 ? Strings.SongDelayReset : Strings.SongDelayLabel(_songOffsetMs));
                return;
            }
            _songOffsetMs = value;
            _transport.SetSongOffset(value);
            SongOffsetChanged?.Invoke(value);
            ShowToast(value == 0 ? Strings.SongDelayReset : Strings.SongDelayLabel(value));
        }

        internal void ResetOffset() => NudgeOffset(-_songOffsetMs);

        private void ToggleMute()
        {
            _mute = !_mute;
            _controls.SetMute?.Invoke(_mute);
            ShowToast(_mute ? Strings.Muted : Strings.SoundOn);
        }

        /// <summary>`L` and Shift+L toggle; pressing the same range again turns the loop off, a
        /// different range switches to it.</summary>
        private void ToggleLoop(bool section) =>
            ApplyLoop(LoopRules.Toggle(_loopMode, section ? LoopMode.Section : LoopMode.Line));

        /// <summary>The menu/hotkey command "loop this section" always switches to that range,
        /// even while a line loop is active (R4-28).</summary>
        internal void SetLoop(bool section) =>
            ApplyLoop(LoopRules.Set(_loopMode, section ? LoopMode.Section : LoopMode.Line));

        internal void LoopOff() => ApplyLoop(LoopMode.Off);

        private void ApplyLoop(LoopMode requested)
        {
            if (requested == LoopMode.Off)
            {
                ClearLoop();
                ShowToast(Strings.LoopOff);
                RefreshMenu();
                return;
            }
            var index = _scene.CurrentLine(_songTime);
            if (index < 0) index = 0;
            var (start, end) = _scene.LineRange(index, requested == LoopMode.Section ? 4 : 1);
            if (double.IsNaN(start) || double.IsNaN(end)) { ShowToast(Strings.NoLyricsToLoop); return; }
            if (_songMs > 0) end = Math.Min(end, _songMs);
            _loopMode = requested;
            _loopStart = start;
            _loopEnd = end;
            _scene.LoopStart = start;
            _scene.LoopEnd = end;
            ShowToast(requested == LoopMode.Section ? Strings.LoopingSection : Strings.LoopingLine);
            _controls.Seek?.Invoke(Math.Max(0, start + EffectiveOffsetMs));
            _loopHoldUntil = _frameWatch.Elapsed.TotalSeconds + 0.7;
            RefreshMenu();
        }

        private void ClearLoop()
        {
            _loopMode = LoopMode.Off;
            _loopStart = _loopEnd = double.NaN;
            _scene.LoopStart = _scene.LoopEnd = double.NaN;
        }

        private void SaveScreenshot()
        {
            try
            {
                var dpi = VisualTreeHelper.GetDpi(this);
                var w = (int)Math.Round(ActualWidth * dpi.DpiScaleX);
                var h = (int)Math.Round(ActualHeight * dpi.DpiScaleY);
                if (w < 2 || h < 2) return;
                _toast.BeginAnimation(OpacityProperty, null);
                _toast.Opacity = 0;
                var bmp = new RenderTargetBitmap(w, h, 96 * dpi.DpiScaleX, 96 * dpi.DpiScaleY, PixelFormats.Pbgra32);
                bmp.Render(_root);
                var dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyPictures), Strings.ScreenshotFolder);
                Directory.CreateDirectory(dir);
                var path = Path.Combine(dir, Strings.ScreenshotFilePrefix + $"{DateTime.Now:yyyy-MM-dd HH-mm-ss}.png");
                var enc = new PngBitmapEncoder();
                enc.Frames.Add(BitmapFrame.Create(bmp));
                using (var f = File.Create(path)) enc.Save(f);
                try { Clipboard.SetImage(bmp); } catch (Exception) { }
                ShowToast(Strings.ScreenshotSaved);
            }
            catch (Exception)
            {
                ShowToast(Strings.ScreenshotFailed);
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
                _controls.Seek?.Invoke(Math.Max(0, start + EffectiveOffsetMs));
                ShowToast(Strings.JumpedToLine);
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

        internal bool IsFullscreen => _fullscreen;

        internal void SetFullscreen(bool on)
        {
            if (on == _fullscreen)
            {
                if (on) Topmost = _settings.FullscreenTopmost;
                return;
            }
            if (on)
            {
                _restore = WindowState == WindowState.Normal ? new Rect(Left, Top, Width, Height) : RestoreBounds;
                _restoreState = WindowState == WindowState.Minimized ? WindowState.Normal : WindowState;
                WindowStyle = WindowStyle.None;
                ResizeMode = ResizeMode.NoResize;
                _fullscreen = true;
                ApplyFullscreenBounds();
                _cursorTimer.Stop();
                _cursorTimer.Start();
            }
            else
            {
                _fullscreen = false;
                Topmost = false;
                WindowState = WindowState.Normal;
                WindowStyle = WindowStyle.SingleBorderWindow;
                ResizeMode = ResizeMode.CanResize;
                if (_restore.Width > 0)
                {
                    Left = _restore.Left; Top = _restore.Top; Width = _restore.Width; Height = _restore.Height;
                }
                if (_restoreState == WindowState.Maximized) WindowState = WindowState.Maximized;
                _cursorTimer.Stop();
                Mouse.OverrideCursor = null;
            }
            _scene.LyricsOnly = on && _settings.FullscreenLyricsOnly;
            ContextMenu = BuildMenu();
        }

        /// <summary>Fills exactly one monitor's device bounds, including the taskbar area. Maximizing
        /// would stop at the work area, so the window is a normal borderless window with those bounds.</summary>
        private void ApplyFullscreenBounds()
        {
            try
            {
                var screen = FullscreenScreen();
                Rect bounds;
                var source = PresentationSource.FromVisual(this);
                if (source?.CompositionTarget != null)
                {
                    // TransformFromDevice maps device pixels to DIPs (it already contains the
                    // reciprocal of the DPI scale); transform the corners instead of guessing M11.
                    var transform = source.CompositionTarget.TransformFromDevice;
                    var topLeft = transform.Transform(new Point(screen.Bounds.Left, screen.Bounds.Top));
                    var bottomRight = transform.Transform(new Point(screen.Bounds.Right, screen.Bounds.Bottom));
                    bounds = new Rect(topLeft, bottomRight);
                }
                else
                {
                    bounds = FullscreenLayout.FromDevice(screen.Bounds, 1.0, 1.0);
                }
                if (bounds.IsEmpty) return;
                WindowState = WindowState.Normal;
                Left = bounds.Left;
                Top = bounds.Top;
                Width = bounds.Width;
                Height = bounds.Height;
                Topmost = _settings.FullscreenTopmost;
                var handle = new WindowInteropHelper(this).Handle;
                if (handle != IntPtr.Zero)
                    SetWindowPos(handle, IntPtr.Zero, 0, 0, 0, 0,
                                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED);
            }
            catch (Exception e)
            {
                _log?.Invoke(e);
            }
        }

        private System.Windows.Forms.Screen FullscreenScreen()
        {
            if (!string.IsNullOrEmpty(_settings.FullscreenMonitor))
            {
                var saved = System.Windows.Forms.Screen.AllScreens.FirstOrDefault(s =>
                    string.Equals(s.DeviceName, _settings.FullscreenMonitor, StringComparison.OrdinalIgnoreCase));
                if (saved != null) return saved;
            }
            return CurrentScreen() ?? System.Windows.Forms.Screen.PrimaryScreen;
        }

        /// <summary>Applies a different fullscreen monitor immediately and tells the plugin to save it.</summary>
        internal void ChooseFullscreenMonitor(string deviceName)
        {
            _settings.FullscreenMonitor = deviceName ?? "";
            if (_fullscreen) ApplyFullscreenBounds();
            FullscreenMonitorChosen?.Invoke(_settings.FullscreenMonitor);
            ContextMenu = BuildMenu();
        }

        internal void SetFullscreenTopmost(bool topmost)
        {
            _settings.FullscreenTopmost = topmost;
            Topmost = _fullscreen && topmost;
            FullscreenTopmostChanged?.Invoke(topmost);
            ContextMenu = BuildMenu();
        }

        private ContextMenu BuildMenu()
        {
            var menu = new ContextMenu();
            var full = new MenuItem { Header = _fullscreen ? Strings.ExitFullscreen : Strings.EnterFullscreen };
            full.Click += (s, e) => Safe.Run(() => SetFullscreen(!_fullscreen), _log);
            menu.Items.Add(full);
            var topmost = new MenuItem
            {
                Header = Strings.KeepOnTop,
                IsCheckable = true,
                IsChecked = _settings.FullscreenTopmost
            };
            topmost.Click += (s, e) => Safe.Run(() => SetFullscreenTopmost(!_settings.FullscreenTopmost), _log);
            menu.Items.Add(topmost);
            var display = new MenuItem { Header = Strings.FullscreenMonitor };
            var current = CurrentMonitor();
            foreach (var screen in System.Windows.Forms.Screen.AllScreens)
            {
                var item = new MenuItem
                {
                    Header = screen.DeviceName + (screen.Primary ? Strings.PrimaryMonitorSuffix : ""),
                    IsCheckable = true,
                    IsChecked = string.Equals(screen.DeviceName, _settings.FullscreenMonitor,
                                             StringComparison.OrdinalIgnoreCase) ||
                                (string.IsNullOrEmpty(_settings.FullscreenMonitor) &&
                                 string.Equals(screen.DeviceName, current, StringComparison.OrdinalIgnoreCase))
                };
                var device = screen.DeviceName;
                item.Click += (s, e) => Safe.Run(() => ChooseFullscreenMonitor(device), _log);
                display.Items.Add(item);
            }
            display.Items.Add(new Separator());
            var currentItem = new MenuItem { Header = Strings.CurrentMonitor, IsCheckable = true };
            currentItem.IsChecked = string.IsNullOrEmpty(_settings.FullscreenMonitor);
            currentItem.Click += (s, e) => Safe.Run(() => ChooseFullscreenMonitor(""), _log);
            display.Items.Add(currentItem);
            menu.Items.Add(display);

            var skip = new MenuItem { Header = Strings.SkipIntro };
            skip.Click += (s, e) => Safe.Run(() => SkipIntroRequested?.Invoke(this, EventArgs.Empty), _log);
            menu.Items.Add(skip);

            var loop = new MenuItem
            {
                Header = Strings.LoopCurrentLine,
                IsCheckable = true,
                IsChecked = _loopMode == LoopMode.Line
            };
            loop.Click += (s, e) => Safe.Run(() => ToggleLoop(false), _log);
            menu.Items.Add(loop);
            var section = new MenuItem
            {
                Header = Strings.LoopThisSection,
                IsCheckable = true,
                IsChecked = _loopMode == LoopMode.Section
            };
            section.Click += (s, e) => Safe.Run(() => SetLoop(true), _log);
            menu.Items.Add(section);
            var loopOff = new MenuItem { Header = Strings.LoopOffItem, IsEnabled = _loopMode != LoopMode.Off };
            loopOff.Click += (s, e) => Safe.Run(LoopOff, _log);
            menu.Items.Add(loopOff);
            var shot = new MenuItem { Header = Strings.SaveScreenshot };
            shot.Click += (s, e) => Safe.Run(SaveScreenshot, _log);
            menu.Items.Add(shot);

            var jp = new MenuItem { Header = Strings.Japanese };
            foreach (var (mode, label) in new[] { (JapaneseMode.RomajiOnly, Strings.RomajiOnly),
                                                  (JapaneseMode.JapaneseAndRomaji, Strings.JapaneseAndRomaji),
                                                  (JapaneseMode.JapaneseOnly, Strings.JapaneseOnly) })
            {
                var item = new MenuItem { Header = label, IsCheckable = true, IsChecked = _settings.Japanese == mode };
                item.Click += (s, e) => Safe.Run(() => JapaneseModeChosen?.Invoke(mode), _log);
                jp.Items.Add(item);
            }
            menu.Items.Add(jp);

            _lyricLoomItem = new MenuItem
            {
                Header = Strings.MakeLyricsWithLyricLoom,
                IsEnabled = _lyricLoomEnabled
            };
            _lyricLoomItem.Click += (s, e) => Safe.Run(() => LyricLoomRequested?.Invoke(this, EventArgs.Empty), _log);
            menu.Items.Add(_lyricLoomItem);

            var record = new MenuItem { Header = Strings.RecordSongVideo };
            record.Click += (s, e) => Safe.Run(() => RecordRequested?.Invoke(this, EventArgs.Empty), _log);
            menu.Items.Add(record);

            var settings = new MenuItem { Header = Strings.Settings };
            settings.Click += (s, e) => Safe.Run(() => SettingsRequested?.Invoke(this, EventArgs.Empty), _log);
            menu.Items.Add(settings);
            var diagnostics = new MenuItem { Header = Strings.Diagnostics };
            diagnostics.Click += (s, e) => Safe.Run(() => DiagnosticsRequested?.Invoke(this, EventArgs.Empty), _log);
            menu.Items.Add(diagnostics);
            menu.Items.Add(new Separator());
            var close = new MenuItem { Header = Strings.Close };
            close.Click += (s, e) => Safe.Run(Close, _log);
            menu.Items.Add(close);
            return menu;
        }
    }
}
