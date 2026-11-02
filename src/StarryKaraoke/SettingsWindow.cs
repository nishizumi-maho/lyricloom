using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace MusicBeePlugin
{
    /// <summary>Settings, applied live while the window is open. Cancel puts the old ones back.</summary>
    internal sealed class SettingsWindow : Window
    {
        private readonly Settings _original;
        private readonly Settings _edit;
        private readonly Action<Settings> _preview;
        private readonly StackPanel _panel = new StackPanel { Margin = new Thickness(16) };
        private readonly List<Action> _colorRows = new List<Action>();
        private ComboBox _themeCombo;
        private CheckBox _randomThemeCheck;
        private bool _settingTheme;
        public Settings Result { get; private set; }

        public SettingsWindow(Settings current, Action<Settings> preview)
        {
            _original = current.Clone();
            _edit = current.Clone();
            _preview = preview;
            Title = "Starry Karaoke — Settings";
            Width = 460;
            SizeToContent = SizeToContent.Height;
            ResizeMode = ResizeMode.NoResize;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

            Section("Theme");
            var currentTheme = Themes.Get(_edit.Theme) != null ? _edit.Theme : Themes.Custom;
            _themeCombo = new ComboBox { ItemsSource = Themes.Names, SelectedItem = currentTheme };
            _themeCombo.SelectionChanged += (s, e) =>
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
            };
            Row("Preset", _themeCombo);
            _randomThemeCheck = Check("Random theme for each song", _edit.RandomTheme, v => Set(x => x.RandomTheme = v));

            Section("Text");
            var fonts = Fonts.SystemFontFamilies.Select(f => f.Source).OrderBy(x => x).ToList();
            if (!fonts.Contains(_edit.FontFamily)) fonts.Insert(0, _edit.FontFamily);
            var font = new ComboBox { ItemsSource = fonts, SelectedItem = _edit.FontFamily, IsEditable = true };
            font.SelectionChanged += (s, e) => { if (font.SelectedItem is string f) Set(x => x.FontFamily = f); };
            font.LostFocus += (s, e) => Set(x => x.FontFamily = font.Text);
            Row("Font", font);
            Row("Text size", Slider(0.5, 2.0, _edit.TextScale, v => Set(x => x.TextScale = v)));

            var jp = new ComboBox { ItemsSource = new[] { "Romaji only", "Japanese + romaji below", "Japanese only" }, SelectedIndex = (int)_edit.Japanese };
            jp.SelectionChanged += (s, e) => Set(x => x.Japanese = (JapaneseMode)jp.SelectedIndex);
            Row("Japanese songs", jp);

            var offset = new TextBox { Text = _edit.LyricsOffsetMs.ToString(CultureInfo.InvariantCulture) };
            offset.TextChanged += (s, e) => { if (int.TryParse(offset.Text, out var v)) Set(x => x.LyricsOffsetMs = v); };
            Row("Lyrics delay (ms, + = later)", offset);

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

            var monitorHz = KaraokeWindow.MonitorRefreshRate();
            var winFps = new ComboBox
            {
                ItemsSource = new[] { $"Monitor ({monitorHz} Hz)", "30", "60", "120", "144", "240" },
                SelectedIndex = 0
            };
            if (_edit.WindowFps > 0) winFps.SelectedItem = _edit.WindowFps.ToString(CultureInfo.InvariantCulture);
            winFps.SelectionChanged += (s, e) => Set(x => x.WindowFps = winFps.SelectedIndex <= 0 ? 0 : int.Parse((string)winFps.SelectedItem, CultureInfo.InvariantCulture));
            Row("Window FPS", winFps);

            Section("Party mode");
            Check("Fullscreen on play, hide cursor, keep the display awake", _edit.PartyMode, v => Set(x => x.PartyMode = v));
            Check("Show the next song near the end", _edit.ShowNextSong, v => Set(x => x.ShowNextSong = v));

            Section("Instrumental intro");
            Check("Skip the intro automatically on playback", _edit.AutoSkipIntro, v => Set(x => x.AutoSkipIntro = v));
            Check("Recorded video starts right at the lyrics", _edit.VideoSkipIntro, v => Set(x => x.VideoSkipIntro = v));
            Row("Start how long before the lyrics (s)", Slider(0, 10, _edit.IntroLeadMs / 1000.0, v => Set(x => x.IntroLeadMs = (int)(v * 1000))));

            Section("Recorded video");
            var res = new ComboBox { ItemsSource = new[] { "1280x720", "1920x1080", "2560x1440", "3840x2160" }, IsEditable = true, Text = _edit.VideoResolution };
            res.SelectionChanged += (s, e) => { if (res.SelectedItem is string r) Set(x => x.VideoResolution = r); };
            res.LostFocus += (s, e) => Set(x => x.VideoResolution = res.Text);
            Row("Resolution", res);
            var fps = new ComboBox { ItemsSource = new[] { 24, 25, 30, 50, 60, 120, 144, 240 }, SelectedItem = _edit.VideoFps };
            fps.SelectionChanged += (s, e) => { if (fps.SelectedItem is int f) Set(x => x.VideoFps = f); };
            Row("Video FPS (higher = slower)", fps);
            var ff = new TextBox { Text = _edit.FfmpegPath };
            ff.TextChanged += (s, e) => Set(x => x.FfmpegPath = ff.Text.Trim().Trim('"'));
            Row("ffmpeg.exe (empty = automatic)", ff);

            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 16, 0, 0) };
            var reset = new Button { Content = "Defaults", Width = 84, Margin = new Thickness(0, 0, 8, 0) };
            reset.Click += (s, e) => { Result = Keep(new Settings()); Close(); };
            var ok = new Button { Content = "OK", Width = 84, IsDefault = true, Margin = new Thickness(0, 0, 8, 0) };
            ok.Click += (s, e) => { Result = _edit; Close(); };
            var cancel = new Button { Content = "Cancel", Width = 84, IsCancel = true };
            buttons.Children.Add(reset);
            buttons.Children.Add(ok);
            buttons.Children.Add(cancel);
            _panel.Children.Add(buttons);

            Content = new ScrollViewer { Content = _panel, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, MaxHeight = SystemParameters.WorkArea.Height * 0.9 };
            Closed += (s, e) => { if (Result == null) _preview(_original); };
        }

        /// <summary>Defaults, but keeping where the window is.</summary>
        private Settings Keep(Settings d)
        {
            d.WindowLeft = _original.WindowLeft; d.WindowTop = _original.WindowTop;
            d.WindowWidth = _original.WindowWidth; d.WindowHeight = _original.WindowHeight;
            d.Fullscreen = _original.Fullscreen; d.WindowOpen = _original.WindowOpen;
            return d;
        }

        private void Set(Action<Settings> change)
        {
            change(_edit);
            _preview(_edit.Clone());
        }

        private void RefreshColors()
        {
            foreach (var refresh in _colorRows) refresh();
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
            c.Checked += (s, e) => changed(true);
            c.Unchecked += (s, e) => changed(false);
            _panel.Children.Add(c);
            return c;
        }

        private static Slider Slider(double min, double max, double value, Action<double> changed)
        {
            var s = new Slider { Minimum = min, Maximum = max, Value = Math.Max(min, Math.Min(max, value)), VerticalAlignment = VerticalAlignment.Center };
            s.ValueChanged += (o, e) => changed(e.NewValue);
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
            pick.Click += (s, e) =>
            {
                var c = Settings.ParseColor(get(), Colors.White);
                using (var dlg = new System.Windows.Forms.ColorDialog { FullOpen = true, Color = System.Drawing.Color.FromArgb(c.R, c.G, c.B) })
                    if (dlg.ShowDialog() == System.Windows.Forms.DialogResult.OK)
                        hex.Text = Settings.ToHex(Color.FromRgb(dlg.Color.R, dlg.Color.G, dlg.Color.B));
            };
            hex.TextChanged += (s, e) =>
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
            };
            _colorRows.Add(Show);
            var row = new StackPanel { Orientation = Orientation.Horizontal };
            row.Children.Add(swatch);
            row.Children.Add(hex);
            row.Children.Add(pick);
            Row(label, row);
        }
    }
}
