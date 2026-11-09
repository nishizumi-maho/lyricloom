using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class SceneStringsTests
    {
        /// <summary>R4-29: the scene's user-facing text is English and lives in one place.</summary>
        [Fact]
        public void Default_scene_strings_are_english()
        {
            Assert.Equal("Next: Some Song", Strings.NextSongLabel("Some Song"));
            Assert.Equal("no synced lyrics", Strings.NoSyncedLyrics);
            Assert.Equal("✦  thanks for singing  ✦", Strings.ThanksForSinging);
            Assert.Equal("⟲  loop", Strings.LoopBadge);
            Assert.Equal("·  ·  ·", Strings.CountdownDots);
            Assert.DoesNotContain("A seguir", Strings.NextSongPrefix);
        }

        /// <summary>The karaoke window's own text is in the same place as the scene's.</summary>
        [Fact]
        public void Window_strings_are_english()
        {
            Assert.Equal("Sent to LyricLoom — the lyrics appear here when they are ready", Strings.LyricLoomPending);
            Assert.Equal("Song delay +100 ms", Strings.SongDelayLabel(100));
            Assert.Equal("Song delay reset", Strings.SongDelayReset);
            Assert.Equal("Make word-timed lyrics with LyricLoom...", Strings.MakeLyricsWithLyricLoom);
            Assert.Equal("Fullscreen (F11)", Strings.EnterFullscreen);
        }
    }
}
