using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;

namespace MusicBeePlugin
{
    /// <summary>
    /// Finds ffmpeg in the order the settings promise: the explicit setting, then the binary bundled
    /// with an installed LyricLoom (the PyInstaller build keeps it in
    /// "_internal\imageio_ffmpeg\binaries\ffmpeg-&lt;version&gt;.exe"), then PATH. The file-system
    /// operations are injected so the order can be tested without touching the real machine.
    /// </summary>
    internal sealed class FfmpegLocator
    {
        private readonly Func<string> _lyricLoomExecutable;
        private readonly Func<string, bool> _fileExists;
        private readonly Func<string, string[]> _filesIn;
        private readonly Func<string> _pathVariable;

        public FfmpegLocator(Func<string> lyricLoomExecutable, Func<string, bool> fileExists,
                             Func<string, string[]> filesIn, Func<string> pathVariable)
        {
            _lyricLoomExecutable = lyricLoomExecutable;
            _fileExists = fileExists;
            _filesIn = filesIn;
            _pathVariable = pathVariable;
        }

        public static FfmpegLocator Default(string lyricLoomSetting) =>
            new FfmpegLocator(
                () => LyricLoomLocator.Default.Find(lyricLoomSetting),
                File.Exists,
                ListFfmpegFiles,
                () => Environment.GetEnvironmentVariable("PATH"));

        public static string Resolve(string configured, string lyricLoomSetting) =>
            Default(lyricLoomSetting).Find(configured);

        public string Find(string configured)
        {
            var own = Normalize(configured);
            if (own != null && _fileExists(own))
            {
                try { return Path.GetFullPath(own); }
                catch (Exception) { return own; }
            }

            var lyricLoom = Normalize(_lyricLoomExecutable?.Invoke());
            if (lyricLoom != null)
            {
                var install = Path.GetDirectoryName(lyricLoom);
                foreach (var folder in BundledFolders(install))
                {
                    foreach (var file in Sorted(_filesIn(folder)))
                        if (_fileExists(file)) return file;
                }
            }

            foreach (var folder in PathFolders(_pathVariable?.Invoke()))
            {
                try
                {
                    var file = Path.Combine(folder, "ffmpeg.exe");
                    if (_fileExists(file)) return file;
                }
                catch (ArgumentException) { }
            }
            return null;
        }

        /// <summary>PyInstaller puts the friendlier name in _internal; a plain install may keep the
        /// package folder at the top level. Both are searched for ffmpeg*.exe, whatever the version.</summary>
        private static IEnumerable<string> BundledFolders(string install)
        {
            if (string.IsNullOrEmpty(install)) yield break;
            yield return Path.Combine(install, "_internal", "imageio_ffmpeg", "binaries");
            yield return Path.Combine(install, "imageio_ffmpeg", "binaries");
        }

        private static string[] ListFfmpegFiles(string folder)
        {
            try
            {
                if (string.IsNullOrEmpty(folder) || !Directory.Exists(folder)) return new string[0];
                return Directory.GetFiles(folder, "ffmpeg*.exe");
            }
            catch (Exception)
            {
                return new string[0];
            }
        }

        private static string[] Sorted(string[] files)
        {
            if (files == null || files.Length == 0) return new string[0];
            var copy = (string[])files.Clone();
            Array.Sort(copy, StringComparer.OrdinalIgnoreCase);
            return copy;
        }

        private static IEnumerable<string> PathFolders(string value)
        {
            foreach (var raw in (value ?? "").Split(new[] { ';' }, StringSplitOptions.RemoveEmptyEntries))
            {
                var folder = raw.Trim().Trim('"');
                if (folder.Length > 0) yield return folder;
            }
        }

        private static string Normalize(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) return null;
            var value = Environment.ExpandEnvironmentVariables(path.Trim().Trim('"'));
            return value.Length == 0 ? null : value;
        }
    }

    /// <summary>Runs ffmpeg for a user-requested check (Settings > Test, Diagnostics). No shell and
    /// no window; only the first line of `ffmpeg -version` is needed.</summary>
    internal static class FfmpegInfo
    {
        public static string VersionLine(string executable, int timeoutMs = 3000)
        {
            if (string.IsNullOrWhiteSpace(executable) || !File.Exists(executable)) return "";
            try
            {
                var info = new ProcessStartInfo(executable, "-version")
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
                    var output = new StringBuilder();
                    var error = new StringBuilder();
                    process.OutputDataReceived += (s, e) =>
                    {
                        if (e.Data == null) return;
                        lock (output) output.AppendLine(e.Data);
                    };
                    process.ErrorDataReceived += (s, e) =>
                    {
                        if (e.Data == null) return;
                        lock (error) error.AppendLine(e.Data);
                    };
                    process.BeginOutputReadLine();
                    process.BeginErrorReadLine();
                    if (!process.WaitForExit(timeoutMs))
                    {
                        try { process.Kill(); } catch (Exception) { }
                        return "";
                    }
                    process.WaitForExit();   // let the asynchronous readers finish
                    string text;
                    lock (output) text = output.ToString();
                    if (FirstLine(text).Length == 0)
                    {
                        lock (error) text = error.ToString();
                    }
                    return FirstLine(text);
                }
            }
            catch (Exception)
            {
                return "";
            }
        }

        private static string FirstLine(string text)
        {
            if (string.IsNullOrEmpty(text)) return "";
            var index = text.IndexOfAny(new[] { '\r', '\n' });
            return (index < 0 ? text : text.Substring(0, index)).Trim();
        }
    }
}
