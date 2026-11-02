using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;
using MusicBeePlugin;

namespace StarryKaraoke.Recorder
{
    /// <summary>
    /// StarryKaraoke.Recorder.exe --lrc lyrics.lrc --audio song.flac --out video.mp4 --settings s.xml
    ///     --title "Song — Artist" --duration 273066 [--dict IpaDicFolder] [--ffmpeg ffmpeg.exe]
    /// Renders the whole song, start to end, frame by frame (not a screen capture, so nothing on the
    /// screen or a slow frame can spoil it) and muxes the song's own audio.
    /// </summary>
    internal static class Program
    {
        [STAThread]
        private static int Main(string[] argv)
        {
            var args = ParseArgs(argv);
            var app = new Application { ShutdownMode = ShutdownMode.OnMainWindowClose };
            try
            {
                var job = Job.FromArgs(args);
                var window = new ProgressWindow(job);
                app.MainWindow = window;
                window.Show();
                return app.Run();
            }
            catch (Exception e)
            {
                MessageBox.Show(e.Message, "Starry Karaoke — record video", MessageBoxButton.OK, MessageBoxImage.Error);
                return 1;
            }
        }

        private static Dictionary<string, string> ParseArgs(string[] argv)
        {
            var d = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            for (var i = 0; i + 1 < argv.Length; i += 2)
                if (argv[i].StartsWith("--")) d[argv[i].Substring(2)] = argv[i + 1];
            return d;
        }
    }

    internal sealed class Job
    {
        public string Lrc, Audio, Out, Title, Dict, Ffmpeg;
        public Settings Settings;
        public double DurationMs;
        public int Width = 1920, Height = 1080, Fps = 30;

        public static Job FromArgs(Dictionary<string, string> a)
        {
            string Need(string k) => a.TryGetValue(k, out var v) && !string.IsNullOrEmpty(v) ? v : throw new ArgumentException("missing --" + k);
            var job = new Job
            {
                Lrc = Need("lrc"), Audio = Need("audio"), Out = Need("out"),
                Title = a.TryGetValue("title", out var t) ? t : "",
                Dict = a.TryGetValue("dict", out var dict) ? dict : null,
                DurationMs = double.Parse(Need("duration"), CultureInfo.InvariantCulture),
            };
            job.Settings = a.TryGetValue("settings", out var sp) && File.Exists(sp)
                ? Settings.Load(Path.GetDirectoryName(sp), Path.GetFileName(sp)) : new Settings();
            var res = (job.Settings.VideoResolution ?? "1920x1080").Split(new[] { 'x', 'X' });
            if (res.Length == 2 && int.TryParse(res[0], out var w) && int.TryParse(res[1], out var h) && w >= 320 && h >= 240)
            { job.Width = w & ~1; job.Height = h & ~1; }
            job.Fps = Math.Max(10, Math.Min(240, job.Settings.VideoFps));
            job.Ffmpeg = FindFfmpeg(a.TryGetValue("ffmpeg", out var f) ? f : job.Settings.FfmpegPath);
            if (!File.Exists(job.Audio)) throw new FileNotFoundException("Audio not found: " + job.Audio);
            if (job.DurationMs <= 0) throw new ArgumentException("Unknown song duration.");
            return job;
        }

        /// <summary>The given ffmpeg, else one next to this exe, else the first on PATH.</summary>
        private static string FindFfmpeg(string given)
        {
            if (!string.IsNullOrWhiteSpace(given) && File.Exists(given)) return given;
            var here = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "ffmpeg.exe");
            if (File.Exists(here)) return here;
            foreach (var dir in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'))
            {
                try
                {
                    var p = Path.Combine(dir.Trim('"'), "ffmpeg.exe");
                    if (File.Exists(p)) return p;
                }
                catch (ArgumentException) { }
            }
            var winget = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Microsoft", "WinGet", "Links", "ffmpeg.exe");
            if (File.Exists(winget)) return winget;
            throw new FileNotFoundException("ffmpeg.exe not found. Install ffmpeg (for example: winget install Gyan.FFmpeg) or set its path in the Starry Karaoke settings.");
        }
    }

    internal sealed class ProgressWindow : Window
    {
        private readonly ProgressBar _bar = new ProgressBar { Height = 18, Minimum = 0, Maximum = 1 };
        private readonly TextBlock _status = new TextBlock { Margin = new Thickness(0, 8, 0, 0) };
        private readonly Button _cancel = new Button { Content = "Cancel", Width = 96 };
        private readonly Button _open = new Button { Content = "Open folder", Width = 96, Margin = new Thickness(0, 0, 8, 0), Visibility = Visibility.Collapsed };
        private readonly Stopwatch _watch = Stopwatch.StartNew();
        private readonly Renderer _renderer;
        private bool _done;

        public ProgressWindow(Job job)
        {
            Title = "Starry Karaoke — recording video";
            Width = 460;
            SizeToContent = SizeToContent.Height;
            ResizeMode = ResizeMode.CanMinimize;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            var panel = new StackPanel { Margin = new Thickness(16) };
            panel.Children.Add(new TextBlock { Text = job.Title, FontWeight = FontWeights.SemiBold, TextTrimming = TextTrimming.CharacterEllipsis });
            panel.Children.Add(new TextBlock { Text = Path.GetFileName(job.Out), Foreground = Brushes.Gray, Margin = new Thickness(0, 2, 0, 10), TextTrimming = TextTrimming.CharacterEllipsis });
            panel.Children.Add(_bar);
            panel.Children.Add(_status);
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 12, 0, 0) };
            buttons.Children.Add(_open);
            buttons.Children.Add(_cancel);
            panel.Children.Add(buttons);
            Content = panel;
            _status.Text = $"Preparing ({job.Width}×{job.Height}, {job.Fps} fps)...";

            _renderer = new Renderer(job);
            var phase = "";
            _renderer.Status += text => Dispatcher.BeginInvoke((Action)(() => { phase = text; _status.Text = text; }));
            _renderer.Progress += (i, n) => Dispatcher.BeginInvoke((Action)(() =>
            {
                _bar.Value = (double)i / n;
                var el = _watch.Elapsed.TotalSeconds;
                var eta = i > 0 ? el / i * (n - i) : 0;
                _status.Text = $"{phase}\n{100.0 * i / n:0}%  ·  frame {i}/{n}  ·  {TimeSpan.FromSeconds(eta):m\\:ss}";
                TaskbarProgress(i, n);
            }));
            _renderer.Finished += e => Dispatcher.BeginInvoke((Action)(() =>
            {
                _done = true;
                _cancel.Content = "Close";
                if (e == null)
                {
                    _bar.Value = 1;
                    _status.Text = $"Done in {_watch.Elapsed:m\\:ss}.";
                    _open.Visibility = Visibility.Visible;
                }
                else if (e is OperationCanceledException) _status.Text = "Cancelled. No file was written.";
                else _status.Text = "Error: " + e.Message;
            }));
            _open.Click += (s, e) => Process.Start("explorer.exe", "/select,\"" + job.Out + "\"");
            _cancel.Click += (s, e) => { if (_done) Close(); else { _renderer.Cancel(); _cancel.IsEnabled = false; } };
            Closing += (s, e) => { if (!_done) { _renderer.Cancel(); } };
            Loaded += (s, e) => _renderer.Start();
            TaskbarItemInfo = new System.Windows.Shell.TaskbarItemInfo { ProgressState = System.Windows.Shell.TaskbarItemProgressState.Normal };
        }

        private void TaskbarProgress(int i, int n) => TaskbarItemInfo.ProgressValue = (double)i / n;
    }
}
