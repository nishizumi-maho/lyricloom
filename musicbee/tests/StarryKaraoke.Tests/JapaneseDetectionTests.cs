using System.Collections.Generic;
using System.Linq;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    /// <summary>R4-18: Han characters alone are not Japanese. A Chinese song must not be sent
    /// through IPADIC; a Japanese song (kana present) still gets readings for its kanji-only lines.</summary>
    public class JapaneseDetectionTests
    {
        [Fact]
        public void IsJapanese_requires_kana()
        {
            Assert.False(Lrc.IsJapanese("晴天"));
            Assert.False(Lrc.IsJapanese("東京"));
            Assert.True(Lrc.IsJapanese("ほしぞら"));
            Assert.True(Lrc.IsJapanese("カタカナ"));
        }

        [Fact]
        public void Chinese_song_gets_no_japanese_readings()
        {
            var calls = new List<string>();
            var lines = Timeline.Build(Lrc.Parse("[00:01.00]晴天\n[00:05.00]故事\n"), 10000,
                JapaneseMode.RomajiOnly, s => { calls.Add(s); return "wrong"; });

            Assert.Empty(calls);
            Assert.Equal("晴天", lines[0].Main.Text);
            Assert.Equal("故事", lines[1].Main.Text);
            Assert.Null(lines[0].Sub);
        }

        [Fact]
        public void Japanese_song_with_kana_gets_readings()
        {
            var lines = Timeline.Build(Lrc.Parse("[00:01.00]ほしぞら\n"), 9000, JapaneseMode.RomajiOnly,
                s => s.Replace("ほし", "hoshi").Replace("ぞら", "zora"));

            Assert.Equal("hoshizora", lines[0].Main.Text);
        }

        [Fact]
        public void Han_only_line_is_read_when_the_song_is_japanese()
        {
            // The second line proves the song is Japanese; the first line is kanji-only.
            var lines = Timeline.Build(Lrc.Parse("[00:01.00]星\n[00:05.00]きらきら\n"), 10000,
                JapaneseMode.RomajiOnly, s => s == "星" ? "hoshi" : s.Replace("きら", "kira").Replace("きら", "kira"));

            Assert.Equal("hoshi", lines[0].Main.Text);
            Assert.Equal("kirakira", lines[1].Main.Text);
        }

        [Fact]
        public void A_chinese_line_in_an_otherwise_japanese_song_follows_the_song_rule()
        {
            var calls = new List<string>();
            var lines = Timeline.Build(Lrc.Parse("[00:01.00]你好\n[00:05.00]ほし\n"), 10000,
                JapaneseMode.RomajiOnly, s => { calls.Add(s); return s == "ほし" ? "hoshi" : "niha"; });
            Assert.Equal(new[] { "你好", "ほし" }, calls);
            Assert.Equal("niha", lines[0].Main.Text);
            Assert.Equal("hoshi", lines[1].Main.Text);
        }
    }
}
