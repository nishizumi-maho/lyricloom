using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class LoopRulesTests
    {
        [Fact]
        public void A_line_loop_switches_to_the_section_instead_of_turning_off()
        {
            Assert.Equal(LoopMode.Section, LoopRules.Set(LoopMode.Line, LoopMode.Section));
            Assert.Equal(LoopMode.Section, LoopRules.Set(LoopMode.Section, LoopMode.Section));
        }

        [Fact]
        public void A_section_loop_switches_back_to_the_line()
        {
            Assert.Equal(LoopMode.Line, LoopRules.Set(LoopMode.Section, LoopMode.Line));
        }

        [Fact]
        public void Pressing_the_same_toggle_turns_the_loop_off()
        {
            Assert.Equal(LoopMode.Off, LoopRules.Toggle(LoopMode.Line, LoopMode.Line));
            Assert.Equal(LoopMode.Off, LoopRules.Toggle(LoopMode.Section, LoopMode.Section));
            Assert.Equal(LoopMode.Section, LoopRules.Toggle(LoopMode.Off, LoopMode.Section));
            Assert.Equal(LoopMode.Line, LoopRules.Toggle(LoopMode.Section, LoopMode.Line));
        }

        [Fact]
        public void Loop_off_clears_any_range()
        {
            Assert.Equal(LoopMode.Off, LoopRules.Off(LoopMode.Line));
            Assert.Equal(LoopMode.Off, LoopRules.Off(LoopMode.Section));
        }
    }
}
