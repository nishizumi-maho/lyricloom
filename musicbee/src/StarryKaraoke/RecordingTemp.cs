using System;
using System.IO;

namespace MusicBeePlugin
{
    /// <summary>Per-recording input copies and their cleanup (RV1-05).
    ///
    /// The plugin writes its lyrics and settings copies into
    /// <c>%TEMP%\StarryKaraoke\rec-&lt;guid&gt;</c>, the same prefix the recorder's own sweep
    /// recognises. The recorder deletes the copies after reading them; a crash is covered by the
    /// startup sweep below (older than 24 hours), which only matches this prefix and never touches
    /// anything else in the temp folder. This mirrors the recorder's internal RecorderTemp class,
    /// which the plugin assembly cannot reference.</summary>
    internal static class RecordingTemp
    {
        public const string RootFolderName = "StarryKaraoke";
        public const string RunPrefix = "rec-";
        public const string LyricsFileName = "lyrics.lrc";
        public const string SettingsFileName = "settings.xml";
        public static readonly TimeSpan StaleAfter = TimeSpan.FromHours(24);

        public static string Root => Path.Combine(Path.GetTempPath(), RootFolderName);

        public static string CreateRunFolder(string root = null)
        {
            var baseDir = root ?? Root;
            Directory.CreateDirectory(baseDir);
            var folder = Path.Combine(baseDir, RunPrefix + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            return folder;
        }

        public static void DeleteRunFolder(string folder)
        {
            if (string.IsNullOrEmpty(folder)) return;
            try { if (Directory.Exists(folder)) Directory.Delete(folder, true); }
            catch (Exception) { }
        }

        /// <summary>Deletes stale <c>rec-*</c> folders older than the given age, and the lyrics/settings
        /// copies (<c>*.lrc</c>, <c>*.xml</c>) that plugin versions before 1.3 left directly in the
        /// plugin's own <c>%TEMP%\StarryKaraoke</c> folder. Nothing else is swept: other files and
        /// folders, and anything outside that folder, are never touched.</summary>
        public static int SweepStale(TimeSpan olderThan, string root = null)
        {
            return Sweep(DateTime.UtcNow - olderThan, root);
        }

        /// <summary>FR-C-07: removes every recording folder and legacy lyrics/settings copy, whatever
        /// its age. Only the same names the startup sweep recognises are touched.</summary>
        public static int SweepAll(string root = null)
        {
            return Sweep(DateTime.MaxValue, root);
        }

        private static int Sweep(DateTime cutoff, string root)
        {
            var baseDir = root ?? Root;
            try
            {
                if (!Directory.Exists(baseDir)) return 0;
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
                foreach (var file in Directory.GetFiles(baseDir))
                {
                    var ext = Path.GetExtension(file);
                    if (!ext.Equals(".lrc", StringComparison.OrdinalIgnoreCase) &&
                        !ext.Equals(".xml", StringComparison.OrdinalIgnoreCase)) continue;
                    try
                    {
                        if (File.GetLastWriteTimeUtc(file) >= cutoff) continue;
                        File.Delete(file);
                        removed++;
                    }
                    catch (Exception) { }
                }
                return removed;
            }
            catch (Exception) { return 0; }
        }
    }

    /// <summary>Plain path comparison for the plugin's early output check (R4-01 is enforced again,
    /// with symlink resolution, by the recorder before it starts work).</summary>
    internal static class RecordingPaths
    {
        public static bool SamePath(string a, string b)
        {
            if (string.IsNullOrWhiteSpace(a) || string.IsNullOrWhiteSpace(b)) return false;
            try
            {
                return string.Equals(Full(a), Full(b), StringComparison.OrdinalIgnoreCase);
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static string Full(string path) =>
            Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }
}
