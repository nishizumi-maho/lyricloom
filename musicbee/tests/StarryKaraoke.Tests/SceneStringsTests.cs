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
    }
}
