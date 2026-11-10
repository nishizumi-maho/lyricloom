using System;
using System.IO;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    /// <summary>RV1-05: the plugin's per-recording input copies live in a rec-* folder, and the
    /// startup sweep removes only those folders after 24 hours.</summary>
    public class RecordingTempTests
    {
        [Fact]
        public void Stale_folders_are_older_than_twenty_four_hours()
        {
            Assert.Equal(TimeSpan.FromHours(24), RecordingTemp.StaleAfter);
        }

        [Fact]
        public void The_plugin_and_the_recorder_agree_on_the_sweep_prefix()
        {
            Assert.Equal(StarryKaraoke.Recorder.RecorderTemp.RunPrefix, RecordingTemp.RunPrefix);
            Assert.Equal(StarryKaraoke.Recorder.RecorderTemp.RootFolderName, RecordingTemp.RootFolderName);
        }

        [Fact]
        public void Run_folder_uses_the_recorder_prefix_and_is_deleted()
        {
            using (var root = new TempFolder())
            {
                var folder = RecordingTemp.CreateRunFolder(root.Path);
                Assert.StartsWith(RecordingTemp.RunPrefix, Path.GetFileName(folder), StringComparison.Ordinal);
                File.WriteAllText(Path.Combine(folder, RecordingTemp.LyricsFileName), "[00:01.00]one");

                RecordingTemp.DeleteRunFolder(folder);

                Assert.False(Directory.Exists(folder));
            }
        }

        [Fact]
        public void Sweep_removes_only_stale_rec_folders()
        {
            using (var root = new TempFolder())
            {
                var stale = Directory.CreateDirectory(Path.Combine(root.Path, RecordingTemp.RunPrefix + "stale"));
                var fresh = Directory.CreateDirectory(Path.Combine(root.Path, RecordingTemp.RunPrefix + "fresh"));
                var other = Directory.CreateDirectory(Path.Combine(root.Path, "other-old"));
                var old = DateTime.UtcNow - TimeSpan.FromHours(25);
                Directory.SetLastWriteTimeUtc(stale.FullName, old);
                Directory.SetLastWriteTimeUtc(other.FullName, old);

                var removed = RecordingTemp.SweepStale(RecordingTemp.StaleAfter, root.Path);

                Assert.Equal(1, removed);
                Assert.False(Directory.Exists(stale.FullName));
                Assert.True(Directory.Exists(fresh.FullName));
                Assert.True(Directory.Exists(other.FullName));
            }
        }

        [Fact]
        public void Sweep_removes_stale_lyrics_and_settings_copies_left_by_an_older_plugin_only()
        {
            using (var root = new TempFolder())
            {
                var old = DateTime.UtcNow - TimeSpan.FromDays(2);
                string Make(string name, DateTime? when)
                {
                    var path = Path.Combine(root.Path, name);
                    File.WriteAllText(path, "x");
                    if (when.HasValue) File.SetLastWriteTimeUtc(path, when.Value);
                    return path;
                }
                var oldLyrics = Make("20260101-120000.lrc", old);
                var oldSettings = Make("20260101-120000.xml", old);
                var freshLyrics = Make("20261109-120000.lrc", null);
                var otherOld = Make("notes.txt", old);

                var removed = RecordingTemp.SweepStale(RecordingTemp.StaleAfter, root.Path);

                Assert.Equal(2, removed);
                Assert.False(File.Exists(oldLyrics));
                Assert.False(File.Exists(oldSettings));
                Assert.True(File.Exists(freshLyrics));
                Assert.True(File.Exists(otherOld));
            }
        }

        [Fact]
        public void FR_C_07_uninstall_sweep_has_no_age_limit()
        {
            using (var root = new TempFolder())
            {
                // All of these are fresh: uninstall must remove them anyway, because no startup
                // sweep runs after the plugin is gone.
                var rec = Directory.CreateDirectory(Path.Combine(root.Path, RecordingTemp.RunPrefix + "fresh"));
                File.WriteAllText(Path.Combine(rec.FullName, RecordingTemp.LyricsFileName), "[00:01.00]one");
                var legacyLyrics = Path.Combine(root.Path, "20260101-120000.lrc");
                var legacySettings = Path.Combine(root.Path, "20260101-120000.xml");
                var other = Path.Combine(root.Path, "notes.txt");
                File.WriteAllText(legacyLyrics, "x");
                File.WriteAllText(legacySettings, "x");
                File.WriteAllText(other, "x");

                var removed = RecordingTemp.SweepAll(root.Path);

                Assert.Equal(3, removed);
                Assert.False(Directory.Exists(rec.FullName));
                Assert.False(File.Exists(legacyLyrics));
                Assert.False(File.Exists(legacySettings));
                Assert.True(File.Exists(other));
            }
        }

        [Fact]
        public void Output_must_not_be_the_playing_audio_file()
        {
            Assert.True(RecordingPaths.SamePath(@"C:\Music\song.mp4", @"c:\music\SONG.MP4"));
            Assert.False(RecordingPaths.SamePath(@"C:\Music\song.mp4", @"C:\Music\other.mp4"));
            Assert.False(RecordingPaths.SamePath("", @"C:\Music\song.mp4"));
        }
    }
}
