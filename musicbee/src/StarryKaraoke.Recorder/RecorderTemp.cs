using System;
using System.IO;

namespace StarryKaraoke.Recorder
{
    /// <summary>Per-run temporary storage and its cleanup (R4-13, RV1-05).
    ///
    /// Every run gets its own <c>%TEMP%\StarryKaraoke\rec-&lt;guid&gt;</c> folder. The Renderer deletes
    /// its own folder on every exit path; the plugin writes its lyrics and settings copies into a
    /// folder with the same prefix, so the startup sweep also covers a killed or crashed recorder.
    /// The sweep matches only this prefix and never touches anything else in the temp folder.</summary>
    internal static class RecorderTemp
    {
        public const string RootFolderName = "StarryKaraoke";
        public const string RunPrefix = "rec-";

        private static readonly object Sync = new object();
        private static string _activeRun;

        public static string Root => Path.Combine(Path.GetTempPath(), RootFolderName);

        public static string CreateRunFolder(string root = null)
        {
            var baseDir = root ?? Root;
            Directory.CreateDirectory(baseDir);
            var folder = Path.Combine(baseDir, RunPrefix + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            lock (Sync) _activeRun = folder;
            return folder;
        }

        public static void DeleteRunFolder(string folder)
        {
            if (string.IsNullOrEmpty(folder)) return;
            try { if (Directory.Exists(folder)) Directory.Delete(folder, true); }
            catch (Exception) { }
            lock (Sync) if (string.Equals(_activeRun, folder, StringComparison.OrdinalIgnoreCase)) _activeRun = null;
        }

        /// <summary>Called from a process-exit handler: the normal renderer path already deleted its
        /// own folder; this covers an abrupt shutdown.</summary>
        public static void DeleteActiveRunFolder()
        {
            string folder;
            lock (Sync) { folder = _activeRun; _activeRun = null; }
            DeleteRunFolder(folder);
        }

        /// <summary>Deletes stale run folders older than the given age. Only directories whose name
        /// starts with <see cref="RunPrefix"/> are considered, so unrelated files in the temp folder
        /// are never swept. The plugin's per-recording input copies share the prefix.</summary>
        public static int SweepStale(TimeSpan olderThan, string root = null)
        {
            var baseDir = root ?? Root;
            try
            {
                if (!Directory.Exists(baseDir)) return 0;
                var cutoff = DateTime.UtcNow - olderThan;
                var removed = 0;
                foreach (var folder in Directory.GetDirectories(baseDir, RunPrefix + "*"))
                {
                    try
                    {
                        if (Directory.GetLastWriteTimeUtc(folder) >= cutoff) continue;
                        Directory.Delete(folder, true);
                        removed++;
                    }
                    catch (Exception) { }
                }
                return removed;
            }
            catch (Exception) { return 0; }
        }

        /// <summary>Deletes the plugin's temporary input copy after the recorder has read it. Only
        /// files under the recorder's own temp root are deleted; a manually passed lyrics file or
        /// settings file elsewhere is left alone.</summary>
        public static void DeleteOwnedInputCopy(string path, string root = null)
        {
            if (string.IsNullOrWhiteSpace(path)) return;
            try
            {
                var baseDir = Path.GetFullPath(root ?? Root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
                var full = Path.GetFullPath(path);
                if (!full.StartsWith(baseDir, StringComparison.OrdinalIgnoreCase)) return;
                if (File.Exists(full)) File.Delete(full);
            }
            catch (Exception) { }
        }
    }
}
