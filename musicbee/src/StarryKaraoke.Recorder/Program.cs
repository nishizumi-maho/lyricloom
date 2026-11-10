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
using System.Windows.Threading;
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
                RecorderTemp.SweepStale(TimeSpan.FromHours(24));
                AppDomain.CurrentDomain.ProcessExit += (s, e) => RecorderTemp.DeleteActiveRunFolder();
                var job = Job.FromArgs(args);
                var window = new ProgressWindow(job);
                app.MainWindow = window;
                window.Show();
                return app.Run();
            }
            catch (Exception e)
            {
                // Even a refused or failed start must not leave the plugin's private copies in %TEMP%.
                RecorderTemp.DeleteOwnedInputCopy(args.TryGetValue("lrc", out var lrc) ? lrc : null);
                RecorderTemp.DeleteOwnedInputCopy(args.TryGetValue("settings", out var settings) ? settings : null);
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
        public string Lrc, Audio, Out, Title, Dict, Ffmpeg, Lyrics, SettingsPath;
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
            job.SettingsPath = a.TryGetValue("settings", out var sp) && File.Exists(sp) ? sp : null;
            job.Settings = job.SettingsPath != null
                ? Settings.Load(Path.GetDirectoryName(job.SettingsPath), Path.GetFileName(job.SettingsPath)) : new Settings();
            var res = (job.Settings.VideoResolution ?? "1920x1080").Split(new[] { 'x', 'X' });
            if (res.Length == 2 && int.TryParse(res[0], out var w) && int.TryParse(res[1], out var h) && w >= 320 && h >= 240)
            { job.Width = w & ~1; job.Height = h & ~1; }
            job.Fps = Math.Max(10, Math.Min(240, job.Settings.VideoFps));
            job.Ffmpeg = FindFfmpeg(a.TryGetValue("ffmpeg", out var f) ? f : job.Settings.FfmpegPath);
            if (!File.Exists(job.Audio)) throw new FileNotFoundException("Audio not found: " + job.Audio);
            if (!File.Exists(job.Lrc)) throw new FileNotFoundException("Lyrics not found: " + job.Lrc);
            if (job.DurationMs <= 0) throw new ArgumentException("Unknown song duration.");

            // R4-01: refuse before doing any work. Compare canonical paths (symlinks/junctions and
            // relative paths included), not just the strings the caller typed.
            OutputSafety.ValidateOutput(job.Out, job.Audio, job.Lrc, job.SettingsPath, job.Ffmpeg);

            job.Lyrics = File.ReadAllText(job.Lrc);
            // The plugin writes copies of the lyrics and settings under our own temp root (in a
            // rec-* folder). They have been read into memory now; do not leave personal data behind
            // (R4-13). If this process dies first, the startup sweep removes the folder after 24 h.
            RecorderTemp.DeleteOwnedInputCopy(job.Lrc);
            RecorderTemp.DeleteOwnedInputCopy(job.SettingsPath);
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
        private bool _closeRequested;
        private bool _cancelRequested;
        private DispatcherTimer _forceTimer;

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
                StopForceTimer();
                _cancel.IsEnabled = true;
                _cancel.Content = "Close";
                if (e == null)
                {
                    _bar.Value = 1;
                    _status.Text = $"Done in {_watch.Elapsed:m\\:ss}.";
                    _open.Visibility = Visibility.Visible;
                }
                else if (e is OperationCanceledException) _status.Text = "Cancelled. No file was written.";
                else _status.Text = "Error: " + e.Message;
                // The user asked to close while we were still stopping; finish the close only now
                // that the renderer has deleted its work folder and the job object is closed.
                if (_closeRequested) Close();
            }));
            _open.Click += (s, e) => Process.Start("explorer.exe", "/select,\"" + job.Out + "\"");
            _cancel.Click += (s, e) => { if (_done) Close(); else BeginCancel(); };
            Closing += (s, e) =>
            {
                if (_done) return;
                // Do not let OnMainWindowClose kill the render thread while ffmpeg is still running.
                e.Cancel = true;
                _closeRequested = true;
                BeginCancel();
            };
            Loaded += (s, e) => _renderer.Start();
            TaskbarItemInfo = new System.Windows.Shell.TaskbarItemInfo { ProgressState = System.Windows.Shell.TaskbarItemProgressState.Normal };
        }

        private void BeginCancel()
        {
            if (_cancelRequested) return;
            _cancelRequested = true;
            _renderer.Cancel();
            _cancel.IsEnabled = false;
            _cancel.Content = "Stopping...";
            _status.Text = "Stopping...";

            // Cancellation is cooperative for ffmpeg's final join. If it is still running after five
            // seconds, terminate the job object's processes; if the render thread then cannot finish,
            // close anyway after three more seconds.
            _forceTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(5) };
            _forceTimer.Tick += (s, e) =>
            {
                StopForceTimer();
                _renderer.Kill();
                _status.Text = "Stopping ffmpeg...";
                _forceTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(3) };
                _forceTimer.Tick += (s2, e2) =>
                {
                    StopForceTimer();
                    _done = true;
                    Close();
                };
                _forceTimer.Start();
            };
            _forceTimer.Start();
        }

        private void StopForceTimer()
        {
            if (_forceTimer == null) return;
            _forceTimer.Stop();
            _forceTimer = null;
        }

        private void TaskbarProgress(int i, int n) => TaskbarItemInfo.ProgressValue = (double)i / n;
    }
}
