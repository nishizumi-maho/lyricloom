using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.RegularExpressions;
using System.Threading.Tasks;

namespace StarryKaraoke.Recorder
{
    /// <summary>FR-C-02: reads the real duration of the audio file. ffprobe is used when it sits
    /// next to ffmpeg; otherwise ffmpeg's own input banner carries the same "Duration:" line. The
    /// probe runs in the recorder process, never on MusicBee's UI thread.</summary>
    internal static class AudioProbe
    {
        private const int TimeoutMs = 10000;
        private static readonly Regex DurationLine =
            new Regex(@"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", RegexOptions.Compiled);

        public static double ProbeMilliseconds(string ffmpeg, string audio, Action<Process> started = null)
        {
            if (string.IsNullOrWhiteSpace(ffmpeg) || string.IsNullOrWhiteSpace(audio)) return 0;
            try
            {
                var ffprobe = FfprobeNextTo(ffmpeg);
                if (ffprobe != null)
                {
                    var seconds = Run(ffprobe,
                        "-v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 " + Quote(audio), started);
                    if (TryParseSeconds(seconds, out var value)) return value * 1000.0;
                }
                return ParseDurationMilliseconds(Run(ffmpeg, "-hide_banner -i " + Quote(audio), started));
            }
            catch (Exception)
            {
                return 0;
            }
        }

        /// <summary>Parses ffmpeg's "Duration: HH:MM:SS.ss" input line. "N/A" and unknown formats
        /// yield 0 so the caller keeps MusicBee's estimate.</summary>
        internal static double ParseDurationMilliseconds(string output)
        {
            if (string.IsNullOrEmpty(output)) return 0;
            var match = DurationLine.Match(output);
            if (!match.Success) return 0;
            if (!double.TryParse(match.Groups[3].Value.Replace(',', '.'), NumberStyles.Float,
                                 CultureInfo.InvariantCulture, out var seconds)) return 0;
            var hours = int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture);
            var minutes = int.Parse(match.Groups[2].Value, CultureInfo.InvariantCulture);
            return ((hours * 60.0 + minutes) * 60.0 + seconds) * 1000.0;
        }

        internal static bool TryParseSeconds(string text, out double seconds)
        {
            seconds = 0;
            if (string.IsNullOrWhiteSpace(text)) return false;
            var value = text.Trim();
            if (!double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out seconds)) return false;
            return seconds > 0;
        }

        private static string FfprobeNextTo(string ffmpeg)
        {
            string folder;
            try { folder = Path.GetDirectoryName(ffmpeg) ?? ""; }
            catch (Exception) { return null; }
            if (folder.Length == 0) return null;
            var candidate = Path.Combine(folder, "ffprobe.exe");
            try { return File.Exists(candidate) ? candidate : null; }
            catch (Exception) { return null; }
        }

        private static string Quote(string path) => "\"" + path.Replace("\"", "\\\"") + "\"";

        private static string Run(string executable, string arguments, Action<Process> started)
        {
            var info = new ProcessStartInfo(executable, arguments)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                WorkingDirectory = Path.GetDirectoryName(executable) ?? ""
            };
            using (var process = Process.Start(info))
            {
                if (process == null) return "";
                started?.Invoke(process);
                var stdout = process.StandardOutput.ReadToEndAsync();
                var stderr = process.StandardError.ReadToEndAsync();
                if (!process.WaitForExit(TimeoutMs))
                {
                    try { process.Kill(); } catch (Exception) { }
                    return "";
                }
                process.WaitForExit();
                try { Task.WaitAll(new Task[] { stdout, stderr }, 1000); } catch (Exception) { }
                return (stdout.Status == TaskStatus.RanToCompletion ? stdout.Result : "") + "\n" +
                       (stderr.Status == TaskStatus.RanToCompletion ? stderr.Result : "");
            }
        }
    }
}
