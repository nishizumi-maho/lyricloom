using System.IO;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class SongOffsetStoreTests
    {
        private sealed class TempFolder : System.IDisposable
        {
            public string Path { get; }
            public TempFolder()
            {
                Path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "StarryKaraokeTests",
                    System.Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(Path);
            }
            public void Dispose()
            {
                try { Directory.Delete(Path, true); } catch (System.Exception) { }
            }
        }

        private static string Audio(TempFolder folder, string name) => Path.Combine(folder.Path, name);

        [Fact]
        public void Set_get_and_reset_work_per_song()
        {
            using (var temp = new TempFolder())
            {
                var a = Audio(temp, "a.mp3");
                var b = Audio(temp, "b.flac");
                var store = new SongOffsetStore(temp.Path);

                store.Set(a, 250);
                store.Set(b, -150);

                Assert.Equal(250, store.Get(a));
                Assert.Equal(-150, store.Get(b));
                Assert.Equal(0, store.Get(Audio(temp, "missing.mp3")));

                store.Reset(a);
                Assert.Equal(0, store.Get(a));
                Assert.Equal(-150, store.Get(b));
            }
        }

        [Fact]
        public void The_store_survives_a_reload()
        {
            using (var temp = new TempFolder())
            {
                var a = Audio(temp, "song.mp3");
                new SongOffsetStore(temp.Path).Set(a, 400);
                Assert.True(File.Exists(Path.Combine(temp.Path, SongOffsetStore.FileName)));

                var reloaded = new SongOffsetStore(temp.Path);
                Assert.Equal(400, reloaded.Get(a));
                Assert.Null(reloaded.LastError);
            }
        }

        [Fact]
        public void The_lookup_ignores_path_case_and_quotes()
        {
            using (var temp = new TempFolder())
            {
                var a = Audio(temp, "Song.mp3");
                var store = new SongOffsetStore(temp.Path);
                store.Set("\"" + a.ToUpperInvariant() + "\"", 123);
                Assert.Equal(123, store.Get(a));
            }
        }

        [Fact]
        public void Values_are_clamped_to_ten_seconds()
        {
            using (var temp = new TempFolder())
            {
                var a = Audio(temp, "song.mp3");
                var store = new SongOffsetStore(temp.Path);
                store.Set(a, 999999);
                Assert.Equal(10000, store.Get(a));
                store.Set(a, -999999);
                Assert.Equal(-10000, store.Get(a));
            }
        }

        [Fact]
        public void Uninstall_deletes_the_offsets_file()
        {
            using (var temp = new TempFolder())
            {
                var a = Audio(temp, "song.mp3");
                var store = new SongOffsetStore(temp.Path);
                store.Set(a, 300);
                var file = Path.Combine(temp.Path, SongOffsetStore.FileName);
                Assert.True(File.Exists(file));

                Settings.DeleteFiles(temp.Path);

                Assert.False(File.Exists(file));
                Assert.Equal(0, new SongOffsetStore(temp.Path).Get(a));
            }
        }

        [Fact]
        public void A_corrupt_file_is_ignored_and_reported_without_throwing()
        {
            using (var temp = new TempFolder())
            {
                File.WriteAllText(Path.Combine(temp.Path, SongOffsetStore.FileName), "{ not json");
                var store = new SongOffsetStore(temp.Path);
                Assert.NotNull(store.LastError);
                store.Set(Audio(temp, "song.mp3"), 100);
                Assert.Equal(100, new SongOffsetStore(temp.Path).Get(Audio(temp, "song.mp3")));
            }
        }
    }
}
