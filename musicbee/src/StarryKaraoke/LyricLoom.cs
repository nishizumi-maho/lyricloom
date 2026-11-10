using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using Microsoft.Win32;

namespace MusicBeePlugin
{
    /// <summary>
    /// Finds LyricLoom.exe. The order is the one the installer promises: an explicit setting, the
    /// per-user registry value, the per-user Programs folder, then Program Files. The registry and
    /// file-system lookups are injected so the order can be tested without touching the real machine.
    /// </summary>
    internal sealed class LyricLoomLocator
    {
        private readonly Func<string> _registryExecutable;
        private readonly Func<string, bool> _fileExists;
        private readonly Func<string> _localAppData;
        private readonly Func<string> _programFiles;

        public LyricLoomLocator(Func<string> registryExecutable, Func<string, bool> fileExists,
                                Func<string> localAppData, Func<string> programFiles)
        {
            _registryExecutable = registryExecutable;
            _fileExists = fileExists;
            _localAppData = localAppData;
            _programFiles = programFiles;
        }

        public static LyricLoomLocator Default { get; } =
            new LyricLoomLocator(ReadRegistryExecutable, File.Exists,
                                 () => Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                 () => Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles));

        public string Find(string configured)
        {
            var own = Normalize(configured);
            if (own != null && _fileExists(own)) return own;

            var registry = Normalize(_registryExecutable?.Invoke());
            if (registry != null && _fileExists(registry)) return registry;

            var local = Path.Combine(_localAppData?.Invoke() ?? "", "Programs", "LyricLoom", "LyricLoom.exe");
            if (_fileExists(local)) return local;

            var programFiles = Path.Combine(_programFiles?.Invoke() ?? "", "LyricLoom", "LyricLoom.exe");
            if (_fileExists(programFiles)) return programFiles;

            return null;
        }

        private static string Normalize(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) return null;
            var value = Environment.ExpandEnvironmentVariables(path.Trim().Trim('"'));
            return value.Length == 0 ? null : value;
        }

        private static string ReadRegistryExecutable()
        {
            try
            {
                using (var key = Registry.CurrentUser.OpenSubKey(@"Software\LyricLoom"))
                {
                    var executable = key?.GetValue("Executable") as string;
                    if (!string.IsNullOrWhiteSpace(executable)) return executable;
                    var installPath = key?.GetValue("InstallPath") as string;
                    if (!string.IsNullOrWhiteSpace(installPath)) return Path.Combine(installPath, "LyricLoom.exe");
                }
            }
            catch (Exception) { }
            return null;
        }
    }

    /// <summary>Starts LyricLoom for one audio file. No shell and no network request: the command line
    /// contains only the file path, quoted.</summary>
    internal static class LyricLoomLauncher
    {
        public const string DownloadUrl = "https://github.com/nishizumi-maho/lyricloom/releases/latest";

        public static string ArgumentsFor(string audioFile)
        {
            if (string.IsNullOrEmpty(audioFile)) throw new ArgumentException("No audio file.", nameof(audioFile));
            if (audioFile.IndexOf('"') >= 0) throw new ArgumentException("The file path contains a quote.", nameof(audioFile));
            return "--process \"" + audioFile + "\"";
        }

        public static Process Start(string executable, string audioFile)
        {
            var info = new ProcessStartInfo
            {
                FileName = executable,
                Arguments = ArgumentsFor(audioFile),
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = Path.GetDirectoryName(executable) ?? ""
            };
            return Process.Start(info);
        }
    }

    /// <summary>Suppresses a second LyricLoom launch for the same song within ten seconds. Kept free
    /// of WPF and MusicBee so the rule can be tested with a controlled clock.</summary>
    internal sealed class LyricLoomRequestGuard
    {
        public static readonly TimeSpan RelaunchDelay = TimeSpan.FromSeconds(10);
        private static readonly TimeSpan ForgetAfter = TimeSpan.FromMinutes(10);

        private readonly Dictionary<string, DateTime> _lastLaunchUtc =
            new Dictionary<string, DateTime>(StringComparer.OrdinalIgnoreCase);

        /// <summary>True when a launch for this song is allowed; marks it as begun. False while the
        /// previous attempt for the same song is less than ten seconds old.</summary>
        public bool TryBegin(string audioPath, DateTime nowUtc)
        {
            if (string.IsNullOrEmpty(audioPath)) return false;
            lock (_lastLaunchUtc)
            {
                Prune(nowUtc);
                if (_lastLaunchUtc.TryGetValue(audioPath, out var last) &&
                    nowUtc - last < RelaunchDelay)
                    return false;
                _lastLaunchUtc[audioPath] = nowUtc;
                return true;
            }
        }

        /// <summary>Allows an immediate retry after a launch failed.</summary>
        public void Forget(string audioPath)
        {
            if (string.IsNullOrEmpty(audioPath)) return;
            lock (_lastLaunchUtc) _lastLaunchUtc.Remove(audioPath);
        }

        private void Prune(DateTime nowUtc)
        {
            if (_lastLaunchUtc.Count < 32) return;
            var cutoff = nowUtc - ForgetAfter;
            var old = new List<string>();
            foreach (var pair in _lastLaunchUtc)
                if (pair.Value < cutoff) old.Add(pair.Key);
            foreach (var key in old) _lastLaunchUtc.Remove(key);
        }
    }
}
