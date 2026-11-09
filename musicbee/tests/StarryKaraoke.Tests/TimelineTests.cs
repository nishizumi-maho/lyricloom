using System.Linq;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class TimelineTests
    {
        // Sample lines are made up for the tests.
        private const string Plain = "[ti:Test]\n[#source:x]\n[00:01.00]first line\n[00:05.00][00:20.00]repeated\n[00:09.00]\n[00:12.50]last one\n";
        private const string Words = "[00:02.00]<00:02.00>hello <00:03.00>quiet <00:04.00>night<00:05.00>\n[00:08.00]next\n";

        [Fact]
        public void Parse_skips_tags_and_expands_repeated_stamps()
        {
            var lines = Lrc.Parse(Plain);
            Assert.Equal(new[] { 1000.0, 5000, 9000, 12500, 20000 }, lines.Select(l => l.StartMs));
            Assert.Equal("repeated", lines[4].Text);
        }

        [Fact]
        public void Oversized_numbers_are_skipped_without_failing_the_file()
        {
            var lrc = "[99999999999:59.99]broken\n[offset:999999999999]\n[00:01.00]still here\n";
            var lines = Lrc.Parse(lrc);
            Assert.Single(lines);
            Assert.Equal(1000, lines[0].StartMs);
            Assert.Equal("still here", lines[0].Text);
        }

        [Fact]
        public void Offset_moves_lines_earlier()
        {
            var lines = Lrc.Parse("[offset:500]\n[00:02.00]<00:02.00>a <00:03.00>b\n");
            Assert.Equal(1500, lines[0].StartMs);
            Assert.Equal(2500, lines[0].Pieces[1].StartMs);
        }

        [Fact]
        public void Word_tags_split_pieces_and_trailing_tag_is_end()
        {
            var l = Lrc.Parse(Words)[0];
            Assert.Equal(new[] { "hello ", "quiet ", "night" }, l.Pieces.Select(p => p.Text));
            Assert.Equal(5000, l.EndTagMs);
        }

        [Fact]
        public void Trailing_space_after_the_closing_word_tag_still_closes_the_line()
        {
            var l = Lrc.Parse("[00:01.00]hello <00:02.00> \n")[0];
            Assert.Equal(2000, l.EndTagMs);
            Assert.Equal("hello ", l.Text);
        }

        [Fact]
        public void Word_timing_lights_each_word_at_its_tag()
        {
            var line = Timeline.Build(Lrc.Parse(Words), 60000, JapaneseMode.RomajiOnly, null)[0];
            var m = line.Main;
            Assert.Equal("hello quiet night", m.Text);
            Assert.Equal(0, m.LitChars(1999));
            Assert.Equal(6, m.LitChars(3000));          // "hello " done when "quiet" starts
            Assert.Equal(12, m.LitChars(4000));
            Assert.Equal(m.Text.Length, m.LitChars(5000));
            Assert.Equal(5000, line.EndMs);
        }

        [Fact]
        public void Lit_chars_never_go_back()
        {
            foreach (var line in Timeline.Build(Lrc.Parse(Plain + Words), 60000, JapaneseMode.RomajiOnly, null))
            {
                double last = 0;
                for (var t = line.StartMs - 200; t < line.NextMs; t += 7)
                {
                    var lit = line.Main.LitChars(t);
                    Assert.True(lit >= last, $"went back at {t}");
                    last = lit;
                }
            }
        }

        [Fact]
        public void Line_timed_ends_before_next_line()
        {
            var lines = Timeline.Build(Lrc.Parse(Plain), 60000, JapaneseMode.RomajiOnly, null);
            Assert.All(lines.Take(lines.Count - 1), l => Assert.True(l.EndMs <= l.NextMs));
            Assert.True(lines[2].IsBreak);
        }

        [Fact]
        public void Japanese_modes_pick_main_and_sub()
        {
            var lrc = "[00:01.00]<00:01.00>ほし<00:02.00>ぞら\n";
            string Fake(string s) => s.Replace("ほし", "hoshi").Replace("ぞら", "zora");
            var romaji = Timeline.Build(Lrc.Parse(lrc), 9000, JapaneseMode.RomajiOnly, Fake)[0];
            Assert.Equal("hoshizora", romaji.Main.Text);
            Assert.Null(romaji.Sub);
            Assert.Equal(5, romaji.Main.LitChars(2000));   // "hoshi" lit when "zora" starts

            var both = Timeline.Build(Lrc.Parse(lrc), 9000, JapaneseMode.JapaneseAndRomaji, Fake)[0];
            Assert.Equal("ほしぞら", both.Main.Text);
            Assert.Equal("hoshizora", both.Sub.Text);

            var jp = Timeline.Build(Lrc.Parse(lrc), 9000, JapaneseMode.JapaneseOnly, Fake)[0];
            Assert.Equal("ほしぞら", jp.Main.Text);
            Assert.Null(jp.Sub);
        }

        [Fact]
        public void Full_width_space_is_folded()
        {
            var line = Timeline.Build(Lrc.Parse("[00:01.00]one　two\n"), 9000, JapaneseMode.RomajiOnly, null)[0];
            Assert.Equal("one two", line.Main.Text);
        }

        [Fact]
        public void Last_word_finishes_soon_after_it_starts_not_at_the_next_line()
        {
            // no closing tag (as LYRICS BOCA writes them), long instrumental before the next line
            var lrc = "[00:10.00] <00:10.00>one <00:10.40>two <00:10.80>three <00:11.20>four\n[00:30.00]next\n";
            var line = Timeline.Build(Lrc.Parse(lrc), 60000, JapaneseMode.RomajiOnly, null)[0];
            Assert.InRange(line.EndMs, 11450, 12700);
            Assert.Equal(line.Main.Text.Length, line.Main.LitChars(12800));   // fully lit in the instrumental
        }

        [Fact]
        public void Last_word_never_runs_into_the_next_line()
        {
            var lrc = "[00:10.00]<00:10.00>one <00:11.00>longerword\n[00:11.50]next\n";
            var line = Timeline.Build(Lrc.Parse(lrc), 60000, JapaneseMode.RomajiOnly, null)[0];
            Assert.True(line.EndMs <= 11450);
        }

        [Fact]
        public void Intro_skip_lands_before_first_sung_line()
        {
            var lines = Timeline.Build(Lrc.Parse("[00:05.00]\n[00:20.00]first words\n"), 60000, JapaneseMode.RomajiOnly, null);
            Assert.Equal(17000, Timeline.IntroSkipTarget(lines, 3000));
            var early = Timeline.Build(Lrc.Parse("[00:02.00]right away\n"), 60000, JapaneseMode.RomajiOnly, null);
            Assert.Null(Timeline.IntroSkipTarget(early, 3000));
        }

        [Fact]
        public void A_word_shorter_than_60_ms_still_gets_a_60_ms_ramp()
        {
            var line = Timeline.Build(Lrc.Parse("[00:01.00]<00:01.00>ab <00:01.05>cd\n"),
                                      9000, JapaneseMode.RomajiOnly, null)[0];
            var m = line.Main;
            Assert.Equal("ab cd", m.Text);
            Assert.Equal(1060, m.CharEndMs[1], 3);        // 50 ms tag gap widened to the 60 ms minimum
            Assert.True(m.CharEndMs[0] > 1000);
            double last = 0;
            for (var t = 990.0; t < 1300; t += 1)
            {
                var lit = m.LitChars(t);
                Assert.True(lit >= last);
                last = lit;
            }
        }

        [Fact]
        public void Current_index_finds_last_started_line()
        {
            var lines = Timeline.Build(Lrc.Parse(Plain), 60000, JapaneseMode.RomajiOnly, null);
            Assert.Equal(-1, Timeline.CurrentIndex(lines, 500));
            Assert.Equal(0, Timeline.CurrentIndex(lines, 1000));
            Assert.Equal(3, Timeline.CurrentIndex(lines, 13000));
        }
    }
}
