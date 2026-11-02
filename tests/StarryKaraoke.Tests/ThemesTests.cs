using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class ThemesTests
    {
        [Fact]
        public void Every_preset_has_a_valid_palette()
        {
            foreach (var name in Themes.Names)
            {
                if (name == Themes.Custom) continue;
                var p = Themes.Get(name);
                Assert.NotNull(p);
                Assert.False(string.IsNullOrEmpty(p.Lit));
                Assert.False(string.IsNullOrEmpty(p.Head));
                Assert.False(string.IsNullOrEmpty(p.BackgroundTop));
            }
        }

        [Fact]
        public void Random_theme_is_stable_for_the_same_song()
        {
            Assert.Equal(Themes.ForSong("Same Song — Artist").Name, Themes.ForSong("Same Song — Artist").Name);
        }

        [Fact]
        public void Applying_a_preset_copies_its_values()
        {
            var s = new Settings();
            Themes.Get("Sakura").CopyTo(s);
            Assert.Equal("Sakura", s.Theme);
            Assert.Equal(Themes.Get("Sakura").Lit, s.LitColor);
        }
    }
}
