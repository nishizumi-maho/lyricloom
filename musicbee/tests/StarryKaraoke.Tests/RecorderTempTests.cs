using System;
using System.IO;
using StarryKaraoke.Recorder;
using Xunit;

namespace StarryKaraoke.Tests
{
    /// <summary>R4-13: the recorder keeps its work in its own short-lived folder and removes it on
    /// every normal exit; a crash is covered by a startup sweep limited to its own name prefix.</summary>
    public class RecorderTempTests
    {
        [Fact]
        public void Run_folder_has_the_recorder_prefix_and_is_deleted()
        {
            using (var root = new TempFolder())
            {
                var folder = RecorderTemp.CreateRunFolder(root.Path);
                Assert.StartsWith(Path.GetFullPath(root.Path), Path.GetFullPath(folder), StringComparison.OrdinalIgnoreCase);
                Assert.StartsWith(RecorderTemp.RunPrefix, Path.GetFileName(folder), StringComparison.Ordinal);
                File.WriteAllText(Path.Combine(folder, "part00.mp4"), "x");

                RecorderTemp.DeleteRunFolder(folder);

                Assert.False(Directory.Exists(folder));
            }
        }

        [Fact]
        public void Sweep_removes_only_stale_folders_with_the_recorder_prefix()
        {
            using (var root = new TempFolder())
            {
                var stale = Directory.CreateDirectory(Path.Combine(root.Path, RecorderTemp.RunPrefix + "stale"));
                var fresh = Directory.CreateDirectory(Path.Combine(root.Path, RecorderTemp.RunPrefix + "fresh"));
                var other = Directory.CreateDirectory(Path.Combine(root.Path, "other-old"));
                var old = DateTime.UtcNow - TimeSpan.FromHours(2);
                Directory.SetLastWriteTimeUtc(stale.FullName, old);
                Directory.SetLastWriteTimeUtc(other.FullName, old);

                var removed = RecorderTemp.SweepStale(TimeSpan.FromHours(1), root.Path);

                Assert.Equal(1, removed);
                Assert.False(Directory.Exists(stale.FullName));
                Assert.True(Directory.Exists(fresh.FullName));
                Assert.True(Directory.Exists(other.FullName));
            }
        }

        [Fact]
        public void Temp_input_copies_are_deleted_but_a_manual_input_elsewhere_is_kept()
        {
            using (var root = new TempFolder())
            using (var elsewhere = new TempFolder())
            {
                var copy = Path.Combine(root.Path, "20260101-120000.lrc");
                var manual = Path.Combine(elsewhere.Path, "real-song.lrc");
                File.WriteAllText(copy, "[00:01.00]one");
                File.WriteAllText(manual, "[00:01.00]one");

                RecorderTemp.DeleteOwnedInputCopy(copy, root.Path);
                RecorderTemp.DeleteOwnedInputCopy(manual, root.Path);

                Assert.False(File.Exists(copy));
                Assert.True(File.Exists(manual));
            }
        }

        [Fact]
        public void Sweep_never_touches_a_stale_file_directly_under_the_temp_root()
        {
            using (var root = new TempFolder())
            {
                var pluginCopy = Path.Combine(root.Path, "20260101-120000.xml");
                File.WriteAllText(pluginCopy, "<Settings/>");
                Directory.SetLastWriteTimeUtc(pluginCopy, DateTime.UtcNow - TimeSpan.FromDays(2));

                RecorderTemp.SweepStale(TimeSpan.FromHours(1), root.Path);

                Assert.True(File.Exists(pluginCopy));
            }
        }
    }
}
