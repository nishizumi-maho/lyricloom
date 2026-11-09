using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;

namespace MusicBeePlugin
{
    /// <summary>Settings, applied live while the window is open. Cancel puts the old ones back. Live
    /// previews are coalesced for 150 ms so dragging a slider does not rebuild the whole lyric layout
    /// on every mouse move.</summary>
    internal sealed class SettingsWindow : Window
    {
        private const int PreviewDelayMs = 150;

        private readonly Settings _original;
        private readonly Settings _edit;
        private readonly Action<Settings> _preview;
        private readonly Action<Exception> _log;
        private readonly Func<string> _diagnostics;
        private readonly StackPanel _panel = new StackPanel { Margin = new Thickness(16) };
        private readonly List<Action> _colorRows = new List<Action>();
        private readonly DispatcherTimer _previewTimer;
        private Settings _pendingPreview;
        private ComboBox _themeCombo;
        private CheckBox _randomThemeCheck;
        private bool _settingTheme;
        public Settings Result { get; private set; }

        public SettingsWindow(Settings current, Action<Settings> preview, Action<Exception> log = null,
                              Func<string> diagnostics = null)
        {
            _original = current.Clone();
            _edit = current.Clone();
            _preview = preview;
            _log = log;
            _diagnostics = diagnostics;
            _previewTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(PreviewDelayMs) };
            _previewTimer.Tick += (s, e) => Safe.Run(() =>
            {
                _previewTimer.Stop();
                var pending = _pendingPreview;
                _pendingPreview = null;
                if (pending != null) _preview(pending);
            }, _log);
            Title = "Starry Karaoke — Settings";
            Width = 560;
            SizeToContent = SizeToContent.Height;
            ResizeMode = ResizeMode.NoResize;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

            Section("Window");
            var auto = new ComboBox
            {
                ItemsSource = new[] { "Off", "When the song has word-timed lyrics", "When it has any synced lyrics" },
                SelectedIndex = Math.Max(0, Math.Min(2, (int)_edit.AutoOpenLyrics)),
                Width = 230
            };
            auto.SelectionChanged += (s, e) => Safe.Run(
                () => Set(x => x.AutoOpenLyrics = (AutoOpenLyrics)auto.SelectedIndex), _log);
            Row("Open automatically", auto);

            var unsupported = new ComboBox
            {
                ItemsSource = new[] { "Keep the window open", "Hide the window", "Close the window" },
                SelectedIndex = Math.Max(0, Math.Min(2, (int)_edit.OnUnsupportedSong)),
                Width = 230
            };
            unsupported.SelectionChanged += (s, e) => Safe.Run(
                () => Set(x => x.OnUnsupportedSong = (UnsupportedSongAction)unsupported.SelectedIndex), _log);
            Row("On an unsupported song", unsupported);
            Check("Bring the window to the front when it opens automatically", _edit.AutoOpenFocus,
                  v => Set(x => x.AutoOpenFocus = v));

            var displays = new List<DisplayChoice> { new DisplayChoice("", "Current monitor") };
            foreach (var screen in System.Windows.Forms.Screen.AllScreens)
                displays.Add(new DisplayChoice(screen.DeviceName, DisplayLabel(screen)));
            var display = new ComboBox { ItemsSource = displays, Width = 230 };
            display.SelectedItem = displays.Find(d =>
                string.Equals(d.DeviceName, _edit.FullscreenMonitor, StringComparison.OrdinalIgnoreCase)) ?? displays[0];
            display.SelectionChanged += (s, e) => Safe.Run(() =>
            {
                if (display.SelectedItem is DisplayChoice choice)
                    Set(x => x.FullscreenMonitor = choice.DeviceName);
            }, _log);
            Row("Fullscreen monitor", display);
            Check("Keep on top in fullscreen", _edit.FullscreenTopmost,
                  v => Set(x => x.FullscreenTopmost = v));

            Section("LyricLoom");
            var llPath = new TextBox { Text = _edit.LyricLoomPath, Width = 100, VerticalContentAlignment = VerticalAlignment.Center };
            llPath.TextChanged += (s, e) => Safe.Run(() => Set(x => x.LyricLoomPath = llPath.Text.Trim().Trim('"')), _log);
            var browse = new Button { Content = "Browse...", Width = 74, Margin = new Thickness(6, 0, 0, 0) };
            browse.Click += (s, e) => Safe.Run(() =>
            {
                var dlg = new Microsoft.Win32.OpenFileDialog
                {
                    Title = "LyricLoom.exe",
                    Filter = "LyricLoom (LyricLoom.exe)|LyricLoom.exe|Programs (*.exe)|*.exe|All files (*.*)|*.*"
                };
                if (dlg.ShowDialog(this) == true) llPath.Text = dlg.FileName;
            }, _log);
            var test = new Button { Content = "Test", Width = 54, Margin = new Thickness(6, 0, 0, 0) };
            test.Click += (s, e) => Safe.Run(() => TestLyricLoom(llPath.Text), _log);
            var llRow = new StackPanel { Orientation = Orientation.Horizontal };
            llRow.Children.Add(llPath);
            llRow.Children.Add(browse);
            llRow.Children.Add(test);
            Row("LyricLoom.exe (empty = automatic)", llRow);

            Section("Theme");
            var currentTheme = Themes.Get(_edit.Theme) != null ? _edit.Theme : Themes.Custom;
            _themeCombo = new ComboBox { ItemsSource = Themes.Names, SelectedItem = currentTheme };
            _themeCombo.SelectionChanged += (s, e) => Safe.Run(() =>
            {
                if (_settingTheme) return;
                var name = _themeCombo.SelectedItem as string ?? Themes.Custom;
                var palette = Themes.Get(name);
                Set(x =>
                {
                    x.Theme = name;
                    palette?.CopyTo(x);
                });
                if (_randomThemeCheck != null && _randomThemeCheck.IsChecked == true)
                    _randomThemeCheck.IsChecked = false;
                RefreshColors();
            }, _log);
            Row("Preset", _themeCombo);
            _randomThemeCheck = Check("Random theme for each song", _edit.RandomTheme, v => Set(x => x.RandomTheme = v));

            Section("Text");
            var fonts = Fonts.SystemFontFamilies.Select(f => f.Source).OrderBy(x => x).ToList();
            if (!fonts.Contains(_edit.FontFamily)) fonts.Insert(0, _edit.FontFamily);
            var font = new ComboBox { ItemsSource = fonts, SelectedItem = _edit.FontFamily, IsEditable = true };
            font.SelectionChanged += (s, e) => Safe.Run(() =>
            {
                if (font.SelectedItem is string f) Set(x => x.FontFamily = f);
            }, _log);
            font.LostFocus += (s, e) => Safe.Run(() => Set(x => x.FontFamily = font.Text), _log);
            Row("Font", font);
            Row("Text size", Slider(0.5, 2.0, _edit.TextScale, v => Set(x => x.TextScale = v)));

            var jp = new ComboBox
            {
                ItemsSource = new[] { "Romaji only", "Japanese + romaji below", "Japanese only" },
                SelectedIndex = Math.Max(0, Math.Min(2, (int)_edit.Japanese))
            };
            jp.SelectionChanged += (s, e) => Safe.Run(() => Set(x => x.Japanese = (JapaneseMode)jp.SelectedIndex), _log);
            Row("Japanese songs", jp);

            var offset = new TextBox { Text = _edit.LyricsOffsetMs.ToString(CultureInfo.InvariantCulture) };
            offset.TextChanged += (s, e) => Safe.Run(() =>
            {
                if (int.TryParse(offset.Text, out var v)) Set(x => x.LyricsOffsetMs = v);
            }, _log);
            Row("Lyrics delay (ms, base)", offset);

            Section("Colors");
            ColorRow("Lit", () => _edit.LitColor, v => _edit.LitColor = v);
            ColorRow("Glow head", () => _edit.HeadColor, v => _edit.HeadColor = v);
            ColorRow("Current line (unlit)", () => _edit.UnlitColor, v => _edit.UnlitColor = v);
            ColorRow("Other lines", () => _edit.DimColor, v => _edit.DimColor = v);
            ColorRow("Glow", () => _edit.GlowColor, v => _edit.GlowColor = v);
            ColorRow("Background (top)", () => _edit.BackgroundTop, v => _edit.BackgroundTop = v);
            ColorRow("Background (bottom)", () => _edit.BackgroundBottom, v => _edit.BackgroundBottom = v);
            ColorRow("Title", () => _edit.AccentColor, v => _edit.AccentColor = v);

            Section("Effects");
            Check("Stars", _edit.ShowStars, v => Set(x => x.ShowStars = v));
            Check("Comet passing by", _edit.ShowShootingStars, v => Set(x => x.ShowShootingStars = v));
            Row("Number of stars", Slider(0.25, 2.0, _edit.StarDensity, v => Set(x => x.StarDensity = v)));
            Check("Burst of stars at each line end", _edit.LineBursts, v => Set(x => x.LineBursts = v));
            Check("Glow on lit lyrics", _edit.Glow, v => Set(x => x.Glow = v));
            Check("Current line grows", _edit.GrowCurrentLine, v => Set(x => x.GrowCurrentLine = v));
            Row("Transition speed", Slider(0.5, 2.0, _edit.TransitionSpeed, v => Set(x => x.TransitionSpeed = v)));
            Check("Show title", _edit.ShowHeader, v => Set(x => x.ShowHeader = v));
            Check("Show progress bar", _edit.ShowProgress, v => Set(x => x.ShowProgress = v));
            Check("Fullscreen shows only the lyrics", _edit.FullscreenLyricsOnly, v => Set(x => x.FullscreenLyricsOnly = v));

            var fpsChoices = new List<string> { "Display refresh rate", "30", "60", "120" };
            if (_edit.WindowFps > 0 && _edit.WindowFps != 30 && _edit.WindowFps != 60 && _edit.WindowFps != 120)
                fpsChoices.Add(_edit.WindowFps.ToString(CultureInfo.InvariantCulture));
            var winFps = new ComboBox
            {
                ItemsSource = fpsChoices,
                SelectedIndex = _edit.WindowFps == 0 ? 0 : Math.Max(0, fpsChoices.IndexOf(_edit.WindowFps.ToString(CultureInfo.InvariantCulture)))
            };
            winFps.SelectionChanged += (s, e) => Safe.Run(() =>
            {
                Set(x => x.WindowFps = winFps.SelectedIndex <= 0
                    ? 0
                    : int.Parse((string)winFps.SelectedItem, CultureInfo.InvariantCulture));
            }, _log);
            Row("Window FPS", winFps);

            Section("Party mode");
            Check("Fullscreen on play, hide cursor, keep the display awake", _edit.PartyMode, v => Set(x => x.PartyMode = v));
            Check("Show the next song near the end", _edit.ShowNextSong, v => Set(x => x.ShowNextSong = v));
            var onStop = new ComboBox
            {
                ItemsSource = new[] { "Keep fullscreen", "Leave fullscreen", "Hide the window", "Close the window" },
                SelectedIndex = Math.Max(0, Math.Min(3, (int)_edit.PartyModeOnStop)),
                Width = 230
            };
            onStop.SelectionChanged += (s, e) => Safe.Run(
                () => Set(x => x.PartyModeOnStop = (PartyModeOnStop)onStop.SelectedIndex), _log);
            Row("When playback stops", onStop);

            Section("Instrumental intro");
            Check("Skip the intro automatically on playback", _edit.AutoSkipIntro, v => Set(x => x.AutoSkipIntro = v));
            Check("Recorded video starts right at the lyrics", _edit.VideoSkipIntro, v => Set(x => x.VideoSkipIntro = v));
            Row("Start how long before the lyrics (s)", Slider(0, 10, _edit.IntroLeadMs / 1000.0, v => Set(x => x.IntroLeadMs = (int)(v * 1000))));

            Section("Recorded video");
            var res = new ComboBox
            {
                ItemsSource = new[] { "1280x720", "1920x1080", "2560x1440", "3840x2160" },
                IsEditable = true, Text = _edit.VideoResolution
            };
            res.SelectionChanged += (s, e) => Safe.Run(() =>
            {
                if (res.SelectedItem is string r) Set(x => x.VideoResolution = r);
            }, _log);
            res.LostFocus += (s, e) => Safe.Run(() => Set(x => x.VideoResolution = res.Text), _log);
            Row("Resolution", res);
            var fps = new ComboBox { ItemsSource = new[] { 24, 25, 30, 50, 60, 120, 144, 240 }, SelectedItem = _edit.VideoFps };
            fps.SelectionChanged += (s, e) => Safe.Run(() =>
            {
                if (fps.SelectedItem is int f) Set(x => x.VideoFps = f);
            }, _log);
            Row("Video FPS (higher = slower)", fps);
            var ff = new TextBox { Text = _edit.FfmpegPath, Width = 210, VerticalContentAlignment = VerticalAlignment.Center };
            ff.TextChanged += (s, e) => Safe.Run(() => Set(x => x.FfmpegPath = ff.Text.Trim().Trim('"')), _log);
            var ffBrowse = new Button { Content = "Browse...", Width = 74, Margin = new Thickness(6, 0, 0, 0) };
            ffBrowse.Click += (s, e) => Safe.Run(() =>
            {
                var dlg = new Microsoft.Win32.OpenFileDialog
                {
                    Title = "ffmpeg.exe",
                    Filter = "ffmpeg (ffmpeg.exe)|ffmpeg.exe|Programs (*.exe)|*.exe|All files (*.*)|*.*"
                };
                if (dlg.ShowDialog(this) == true) ff.Text = dlg.FileName;
            }, _log);
            var ffTest = new Button { Content = "Test", Width = 54, Margin = new Thickness(6, 0, 0, 0) };
            ffTest.Click += (s, e) => Safe.Run(() => TestFfmpeg(ff.Text), _log);
            var ffRow = new StackPanel { Orientation = Orientation.Horizontal };
            ffRow.Children.Add(ff);
            ffRow.Children.Add(ffBrowse);
            ffRow.Children.Add(ffTest);
            Row("ffmpeg.exe (empty = automatic)", ffRow);

            Section("Diagnostics");
            string diagnosticsReportText = null;
            try { diagnosticsReportText = _diagnostics?.Invoke(); }
            catch (Exception e) { _log?.Invoke(e); }
            var diagnosticsText = new TextBox
            {
                Text = diagnosticsReportText ?? "Diagnostics are not available in this window.",
                IsReadOnly = true,
                AcceptsReturn = true,
                TextWrapping = TextWrapping.Wrap,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                MinHeight = 105,
                MaxHeight = 160
            };
            var diagnosticsButtons = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 4, 0, 0) };
            var copyDiagnostics = new Button { Content = "Copy", Width = 84, Margin = new Thickness(0, 0, 8, 0) };
            copyDiagnostics.Click += (s, e) => Safe.Run(() =>
            {
                Clipboard.SetText(diagnosticsText.Text);
                copyDiagnostics.Content = "Copied";
            }, _log);
            var openLog = new Button { Content = "Open log folder", Width = 120 };
            openLog.Click += (s, e) => Safe.Run(() => DiagnosticsReport.OpenLogFolder(LogPathFromDiagnostics(diagnosticsText.Text)), _log);
            diagnosticsButtons.Children.Add(copyDiagnostics);
            diagnosticsButtons.Children.Add(openLog);
            _panel.Children.Add(diagnosticsText);
            _panel.Children.Add(diagnosticsButtons);

            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 16, 0, 0) };
            var reset = new Button { Content = "Defaults", Width = 84, Margin = new Thickness(0, 0, 8, 0) };
            reset.Click += (s, e) => Safe.Run(() => { Result = Keep(new Settings()); Close(); }, _log);
            var ok = new Button { Content = "OK", Width = 84, IsDefault = true, Margin = new Thickness(0, 0, 8, 0) };
            ok.Click += (s, e) => Safe.Run(() =>
            {
                _edit.Validate();
                Result = _edit;
                Close();
            }, _log);
            var cancel = new Button { Content = "Cancel", Width = 84, IsCancel = true };
            buttons.Children.Add(reset);
            buttons.Children.Add(ok);
            buttons.Children.Add(cancel);
            _panel.Children.Add(buttons);

            Content = new ScrollViewer { Content = _panel, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, MaxHeight = SystemParameters.WorkArea.Height * 0.9 };
            Closed += (s, e) => Safe.Run(() =>
            {
                _previewTimer.Stop();
                _pendingPreview = null;
                if (Result == null) _preview(_original);
            }, _log);
        }

        private void TestFfmpeg(string configured)
        {
            var exe = FfmpegLocator.Resolve(configured, _edit.LyricLoomPath);
            if (string.IsNullOrEmpty(exe))
            {
                MessageBox.Show(this,
                    "ffmpeg was not found.\n\nInstall it with \"winget install Gyan.FFmpeg\", or use Browse... to pick ffmpeg.exe.",
                    "Starry Karaoke", MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }
            var version = FfmpegInfo.VersionLine(exe);
            MessageBox.Show(this,
                "ffmpeg found:\n" + exe + (version.Length > 0 ? "\n\n" + version : "\n\nThe file did not report a version."),
                "Starry Karaoke", MessageBoxButton.OK, MessageBoxImage.Information);
        }

        private void TestLyricLoom(string configured)
        {
            var found = LyricLoomLocator.Default.Find(configured);
            if (string.IsNullOrEmpty(found))
            {
                MessageBox.Show(this,
                    "LyricLoom was not found.\n\nDownload it from " + LyricLoomLauncher.DownloadUrl,
                    "Starry Karaoke", MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }
            var version = "";
            try
            {
                var info = FileVersionInfo.GetVersionInfo(found);
                if (!string.IsNullOrEmpty(info.FileVersion)) version = "\nVersion " + info.FileVersion;
            }
            catch (Exception) { }
            MessageBox.Show(this, "LyricLoom found:\n" + found + version,
                "Starry Karaoke", MessageBoxButton.OK, MessageBoxImage.Information);
        }

        /// <summary>Defaults, but keeping where the window is.</summary>
        private Settings Keep(Settings d)
        {
            d.WindowLeft = _original.WindowLeft; d.WindowTop = _original.WindowTop;
            d.WindowWidth = _original.WindowWidth; d.WindowHeight = _original.WindowHeight;
            d.WindowMonitor = _original.WindowMonitor;
            d.FullscreenMonitor = _original.FullscreenMonitor;
            d.Fullscreen = _original.Fullscreen; d.WindowOpen = _original.WindowOpen;
            return d;
        }

        /// <summary>Applies a change to the edited copy and schedules one preview after the debounce
        /// interval; a slider drag therefore rebuilds the scene once, not once per tick.</summary>
        private void Set(Action<Settings> change)
        {
            Safe.Run(() =>
            {
                change(_edit);
                _pendingPreview = _edit.Clone();
                _previewTimer.Stop();
                _previewTimer.Start();
            }, _log);
        }

        /// <summary>Lets the window-control tests verify the debounce without pumping a dispatcher.</summary>
        internal void ChangeForTest(Action<Settings> change) => Set(change);

        internal bool HasPendingPreview => _previewTimer.IsEnabled;

        private sealed class DisplayChoice
        {
            public string DeviceName { get; }
            private string Label { get; }
            public DisplayChoice(string deviceName, string label) { DeviceName = deviceName; Label = label; }
            public override string ToString() => Label;
        }

        private static string DisplayLabel(System.Windows.Forms.Screen screen)
        {
            var bounds = screen.Bounds;
            return $"{screen.DeviceName}  ({bounds.Width}×{bounds.Height}{(screen.Primary ? ", primary" : "")})";
        }

        private static string LogPathFromDiagnostics(string text)
        {
            foreach (var line in (text ?? "").Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
                if (line.StartsWith("Log: ", StringComparison.Ordinal)) return line.Substring(5).Trim();
            return "";
        }

        private void RefreshColors()
        {
            foreach (var refresh in _colorRows) Safe.Run(refresh, _log);
        }

        private void Section(string title) =>
            _panel.Children.Add(new TextBlock { Text = title, FontWeight = FontWeights.SemiBold, FontSize = 14, Margin = new Thickness(0, _panel.Children.Count == 0 ? 0 : 14, 0, 6) });

        private void Row(string label, FrameworkElement control)
        {
            var g = new Grid { Margin = new Thickness(0, 3, 0, 3) };
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(190) });
            g.ColumnDefinitions.Add(new ColumnDefinition());
            var l = new TextBlock { Text = label, VerticalAlignment = VerticalAlignment.Center };
            Grid.SetColumn(control, 1);
            g.Children.Add(l);
            g.Children.Add(control);
            _panel.Children.Add(g);
        }

        private CheckBox Check(string label, bool value, Action<bool> changed)
        {
            var c = new CheckBox { Content = label, IsChecked = value, Margin = new Thickness(0, 3, 0, 3) };
            c.Checked += (s, e) => Safe.Run(() => changed(true), _log);
            c.Unchecked += (s, e) => Safe.Run(() => changed(false), _log);
            _panel.Children.Add(c);
            return c;
        }

        private Slider Slider(double min, double max, double value, Action<double> changed)
        {
            var safeValue = double.IsNaN(value) || double.IsInfinity(value) ? min : Math.Max(min, Math.Min(max, value));
            var s = new Slider { Minimum = min, Maximum = max, Value = safeValue, VerticalAlignment = VerticalAlignment.Center };
            s.ValueChanged += (o, e) => Safe.Run(() => changed(e.NewValue), _log);
            return s;
        }

        private void ColorRow(string label, Func<string> get, Action<string> set)
        {
            var swatch = new Border { Width = 46, Height = 20, BorderBrush = Brushes.Gray, BorderThickness = new Thickness(1), Margin = new Thickness(0, 0, 8, 0) };
            var hex = new TextBox { Text = get(), Width = 90, VerticalContentAlignment = VerticalAlignment.Center };
            var updating = false;
            void Show()
            {
                updating = true;
                hex.Text = get();
                updating = false;
                swatch.Background = new SolidColorBrush(Settings.ParseColor(get(), Colors.Transparent));
            }
            Show();
            var pick = new Button { Content = "...", Width = 30, Margin = new Thickness(8, 0, 0, 0) };
            pick.Click += (s, e) => Safe.Run(() =>
            {
                var c = Settings.ParseColor(get(), Colors.White);
                using (var dlg = new System.Windows.Forms.ColorDialog { FullOpen = true, Color = System.Drawing.Color.FromArgb(c.R, c.G, c.B) })
                    if (dlg.ShowDialog() == System.Windows.Forms.DialogResult.OK)
                        hex.Text = Settings.ToHex(Color.FromRgb(dlg.Color.R, dlg.Color.G, dlg.Color.B));
            }, _log);
            hex.TextChanged += (s, e) => Safe.Run(() =>
            {
                if (updating) return;
                try { ColorConverter.ConvertFromString(hex.Text); } catch (Exception) { return; }
                Set(x => { set(hex.Text); x.Theme = Themes.Custom; x.RandomTheme = false; });
                if (_randomThemeCheck != null && _randomThemeCheck.IsChecked == true)
                    _randomThemeCheck.IsChecked = false;
                if (_themeCombo != null && !_settingTheme)
                {
                    _settingTheme = true;
                    _themeCombo.SelectedItem = Themes.Custom;
                    _settingTheme = false;
                }
                Show();
            }, _log);
            _colorRows.Add(() => Safe.Run(Show, _log));
            var row = new StackPanel { Orientation = Orientation.Horizontal };
            row.Children.Add(swatch);
            row.Children.Add(hex);
            row.Children.Add(pick);
            Row(label, row);
        }
    }
}
