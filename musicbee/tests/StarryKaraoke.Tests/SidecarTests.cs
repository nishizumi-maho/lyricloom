using System;
using System.IO;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class SidecarTests
    {
        private const string Audio = @"C:\Music\Artist\song.mp3";
        private const string Stem = @"C:\Music\Artist\song";

        [Fact]
        public void Japanese_modes_try_the_matching_variant_first()
        {
            var romaji = SidecarFiles.Candidates(Audio, JapaneseMode.RomajiOnly);
            Assert.Equal(Stem + ".romaji.lrc", romaji[0]);
            Assert.Equal(Stem + ".japanese.lrc", romaji[1]);
            Assert.Equal(Stem + ".lrc", romaji[2]);

            foreach (var mode in new[] { JapaneseMode.JapaneseOnly, JapaneseMode.JapaneseAndRomaji })
            {
                var candidates = SidecarFiles.Candidates(Audio, mode);
                Assert.Equal(Stem + ".japanese.lrc", candidates[0]);
                Assert.Equal(Stem + ".lrc", candidates[candidates.Length - 1]);
            }
        }

        [Fact]
        public void Pick_existing_returns_the_first_variant_that_is_there()
        {
            var exists = new Func<string, bool>(p => p == Stem + ".japanese.lrc" || p == Stem + ".lrc");
            Assert.Equal(Stem + ".japanese.lrc", SidecarFiles.PickExisting(Audio, JapaneseMode.JapaneseOnly, exists));
            Assert.Equal(Stem + ".japanese.lrc", SidecarFiles.PickExisting(Audio, JapaneseMode.RomajiOnly, exists));
            Assert.Equal(Stem + ".japanese.lrc", SidecarFiles.PickExisting(Audio, JapaneseMode.JapaneseAndRomaji, exists));
        }

        [Fact]
        public void Choices_follow_word_timing_and_the_reload_flag()
        {
            const string MbWord = "[00:01.00]<00:01.00>a <00:02.00>b\n";
            const string FileWord = "[00:01.00]<00:01.00>c <00:02.00>d\n";
            const string MbLine = "[00:01.00]a b\n";
            const string FileLine = "[00:01.00]c d\n";

            Assert.Same(MbWord, LyricsSelector.Choose(MbWord, FileLine, false));
            Assert.Same(FileWord, LyricsSelector.Choose(MbLine, FileWord, false));
            Assert.Same(MbWord, LyricsSelector.Choose(MbWord, FileWord, false));
            Assert.Same(FileWord, LyricsSelector.Choose(MbWord, FileWord, true));
            Assert.Same(MbLine, LyricsSelector.Choose(MbLine, FileLine, false));
            Assert.Null(LyricsSelector.Choose("plain", "plain", false));
            Assert.Null(LyricsSelector.Choose(null, null, true));
        }

        [Fact]
        public void Tracker_reloads_only_a_newer_sidecar_for_the_same_song()
        {
            var old = new DateTime(2026, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var newer = old.AddSeconds(2);
            var tracker = new SidecarTracker(Audio, old);

            Assert.True(tracker.IsForSong(Stem + ".lrc"));
            Assert.True(tracker.IsForSong(Stem + ".japanese.lrc"));
            Assert.True(tracker.IsForSong(Stem + ".romaji.lrc"));
            Assert.False(tracker.IsForSong(Stem + ".translation.lrc"));
            Assert.False(tracker.IsForSong(@"C:\Music\Artist\other.mp3"));

            Assert.False(tracker.ShouldReload(Stem + ".lrc", old));
            Assert.False(tracker.ShouldReload(Stem + ".lrc", old.AddSeconds(-1)));
            Assert.True(tracker.ShouldReload(Stem + ".lrc", newer));

            tracker.Mark(newer);
            Assert.False(tracker.ShouldReload(Stem + ".lrc", newer));
            Assert.True(tracker.ShouldReload(Stem + ".japanese.lrc", newer.AddMilliseconds(1)));
        }

        [Fact]
        public void Sidecar_names_are_built_next_to_the_audio_file()
        {
            Assert.Equal(Stem + ".lrc", SidecarFiles.Generic(Audio));
            Assert.Equal(Stem + ".japanese.lrc", SidecarFiles.Japanese(Audio));
            Assert.Equal(Stem + ".romaji.lrc", SidecarFiles.Romaji(Audio));
        }
    }
}
