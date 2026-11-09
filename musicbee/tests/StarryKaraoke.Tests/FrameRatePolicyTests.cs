using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class FrameRatePolicyTests
    {
        [Theory]
        [InlineData(60, 144, true, false, false, false, 60)]
        [InlineData(30, 144, true, false, false, false, 30)]
        [InlineData(120, 60, true, false, false, false, 120)]
        [InlineData(0, 144, true, false, false, false, 144)]
        [InlineData(0, 0, true, false, false, false, 60)]
        [InlineData(60, 144, false, false, false, false, FrameRatePolicy.PausedFps)]
        [InlineData(60, 144, true, true, false, false, 0)]
        [InlineData(60, 144, true, false, true, false, 0)]
        [InlineData(60, 144, true, false, false, true, 0)]
        public void Effective_rate_follows_playback_visibility_and_the_window_monitor(
            int configured, int monitorHz, bool playing, bool minimized, bool hidden, bool covered, int expected)
        {
            Assert.Equal(expected,
                FrameRatePolicy.EffectiveFps(configured, monitorHz, playing, minimized, hidden, covered));
        }

        [Fact]
        public void A_paused_window_still_ticks_but_far_less_often()
        {
            Assert.Equal(10, FrameRatePolicy.EffectiveFps(120, 144, false, false, false, false));
            Assert.Equal(0, FrameRatePolicy.EffectiveFps(120, 144, false, true, false, false));
        }

        [Fact]
        public void The_setting_defaults_to_60_and_display_means_the_window_monitor()
        {
            Assert.Equal(60, new Settings().WindowFps);
            Assert.Equal(60, FrameRatePolicy.TargetFps(0, 0));
            Assert.Equal(144, FrameRatePolicy.TargetFps(0, 144));
            Assert.Equal(120, FrameRatePolicy.TargetFps(120, 144));
        }
    }
}
