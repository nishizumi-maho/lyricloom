using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace StarryKaraoke.Recorder
{
    /// <summary>Output-path safety for the recorder (R4-01).
    ///
    /// The recorder must never treat one of its own inputs as the video target, and it must never
    /// delete an existing target before the replacement exists. ffmpeg writes a unique partial file
    /// in the target folder; <see cref="Commit"/> then swaps it into place with File.Replace, keeping
    /// the old file as a backup until the swap has succeeded.</summary>
    internal static class OutputSafety
    {
        public static void ValidateOutput(string output, params string[] inputs)
        {
            if (string.IsNullOrWhiteSpace(output)) throw new ArgumentException("No output file was given.");
            var full = Canonical(output);
            if (Directory.Exists(full)) throw new ArgumentException("The output path is a folder: " + output);
            var folder = Path.GetDirectoryName(full);
            if (string.IsNullOrEmpty(folder) || !Directory.Exists(folder))
                throw new ArgumentException("The output folder does not exist: " + (folder ?? output));

            foreach (var input in inputs)
            {
                if (string.IsNullOrWhiteSpace(input) || Directory.Exists(input)) continue;
                if (SamePath(full, input))
                    throw new ArgumentException("The video cannot be written over an input file it reads: " + input);
            }
        }

        /// <summary>A unique partial file in the target's own folder, so the final replace is atomic
        /// and stays on one volume even when the target is a network share.</summary>
        public static string PartialPath(string target)
        {
            var full = Path.GetFullPath(target);
            var folder = Path.GetDirectoryName(full);
            if (string.IsNullOrEmpty(folder)) throw new ArgumentException("The output path has no folder: " + target);
            return Path.Combine(folder, Path.GetFileName(full) + "." + Guid.NewGuid().ToString("N") + ".part.mp4");
        }

        /// <summary>Moves a finished partial file over the target. The previous target is kept as a
        /// backup until the atomic replace has returned; only then is the backup removed. If anything
        /// fails, the old target is still there (or is restored from the backup).</summary>
        public static void Commit(string partial, string target)
        {
            if (string.IsNullOrWhiteSpace(partial) || !File.Exists(partial))
                throw new IOException("The video encoder did not produce a complete file; the existing video was left unchanged.");
            if (new FileInfo(partial).Length == 0)
                throw new IOException("The video encoder produced an empty file; the existing video was left unchanged.");

            var partialFull = Path.GetFullPath(partial);
            var targetFull = Path.GetFullPath(target);
            var folder = Path.GetDirectoryName(targetFull);
            if (string.IsNullOrEmpty(folder) || !Directory.Exists(folder))
                throw new IOException("The output folder does not exist: " + (folder ?? target));

            if (!File.Exists(targetFull))
            {
                File.Move(partialFull, targetFull);
                return;
            }

            var backup = Path.Combine(folder, Path.GetFileName(targetFull) + ".bak-" + Guid.NewGuid().ToString("N"));
            try
            {
                // File.Replace is the atomic swap; the old target is moved to backup, not deleted.
                File.Replace(partialFull, targetFull, backup, true);
            }
            catch
            {
                // ReplaceFile is documented to leave the destination in place on failure, but be
                // defensive: if the target vanished and the backup exists, put the old file back.
                try
                {
                    if (!File.Exists(targetFull) && File.Exists(backup)) File.Move(backup, targetFull);
                }
                catch (Exception) { }
                throw;
            }

            try { File.Delete(backup); } catch (Exception) { }
        }

        public static bool SamePath(string a, string b) =>
            string.Equals(Canonical(a), Canonical(b), StringComparison.OrdinalIgnoreCase) ||
            string.Equals(Path.GetFullPath(a), Path.GetFullPath(b), StringComparison.OrdinalIgnoreCase);

        /// <summary>Absolute path with symlinks/junctions and 8.3 names resolved when the file (or its
        /// folder, for a not-yet-created target) exists.</summary>
        public static string Canonical(string path)
        {
            var full = Path.GetFullPath(path);
            try
            {
                if (File.Exists(full) || Directory.Exists(full))
                {
                    var real = FinalPath(full);
                    if (!string.IsNullOrEmpty(real)) full = real;
                }
                else
                {
                    var folder = Path.GetDirectoryName(full);
                    if (!string.IsNullOrEmpty(folder) && Directory.Exists(folder))
                    {
                        var real = FinalPath(folder);
                        if (!string.IsNullOrEmpty(real)) full = Path.Combine(real, Path.GetFileName(full));
                    }
                }
            }
            catch (Exception) { }

            if (full.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase)) full = @"\\" + full.Substring(8);
            else if (full.StartsWith(@"\\?\", StringComparison.Ordinal)) full = full.Substring(4);
            return full.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        }

        // ---------------------------------------------------------------- Win32 final path

        private const uint FILE_SHARE_ALL = 0x1 | 0x2 | 0x4;
        private const uint OPEN_EXISTING = 3;
        private const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateFileW(string fileName, uint desiredAccess, uint shareMode,
            IntPtr securityAttributes, uint creationDisposition, uint flagsAndAttributes, IntPtr templateFile);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern uint GetFinalPathNameByHandleW(IntPtr file, StringBuilder path, uint pathLength, uint flags);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);

        private static string FinalPath(string path)
        {
            var h = CreateFileW(path, 0, FILE_SHARE_ALL, IntPtr.Zero, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, IntPtr.Zero);
            if (h == new IntPtr(-1)) return null;
            try
            {
                var sb = new StringBuilder(512);
                var n = GetFinalPathNameByHandleW(h, sb, (uint)sb.Capacity, 0);
                if (n == 0) return null;
                if (n >= sb.Capacity)
                {
                    sb = new StringBuilder((int)n + 1);
                    n = GetFinalPathNameByHandleW(h, sb, (uint)sb.Capacity, 0);
                    if (n == 0) return null;
                }
                return sb.ToString();
            }
            finally { CloseHandle(h); }
        }
    }
}
