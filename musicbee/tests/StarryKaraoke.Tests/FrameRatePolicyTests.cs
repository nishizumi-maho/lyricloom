using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class FrameRatePolicyTests
    {
        // The old test asserted a 60 fps default and 60 on a 144 Hz display. This package changes
        // that behaviour on purpose: the default is "match display" and every lower rate is an
        // integer divisor of the monitor refresh, never a non-divisor such as 60 on 144 Hz.
        [Theory]
        [InlineData(1, 144, true, false, false, false, 144)]
        [InlineData(2, 144, true, false, false, false, 72)]
        [InlineData(3, 144, true, false, false, false, 48)]
        [InlineData(1, 120, true, false, false, false, 120)]
        [InlineData(2, 120, true, false, false, false, 60)]
        [InlineData(3, 120, true, false, false, false, 40)]
        [InlineData(1, 60, true, false, false, false, 60)]
        [InlineData(2, 60, true, false, false, false, 30)]
        [InlineData(3, 60, true, false, false, false, 20)]
        [InlineData(1, 0, true, false, false, false, 60)]
        [InlineData(2, 0, true, false, false, false, 30)]
        [InlineData(3, 0, true, false, false, false, 20)]
        [InlineData(1, 144, true, true, false, false, 0)]
        [InlineData(1, 144, true, false, true, false, 0)]
        [InlineData(1, 144, true, false, false, true, 0)]
        public void Effective_rate_is_an_integer_divisor_of_the_window_monitor(
            int divisor, int monitorHz, bool playing, bool minimized, bool hidden, bool covered, int expected)
        {
            Assert.Equal(expected,
                FrameRatePolicy.EffectiveFps(divisor, monitorHz, playing, minimized, hidden, covered));
        }

        [Theory]
        [InlineData(144, 12)]
        [InlineData(120, 12)]
        [InlineData(60, 12)]
        [InlineData(30, 10)]
        [InlineData(165, 11)]
        public void A_paused_window_still_ticks_at_a_slow_integer_divisor(int monitorHz, int expected)
        {
            Assert.Equal(expected, FrameRatePolicy.PausedFps(monitorHz));
            Assert.Equal(expected, FrameRatePolicy.EffectiveFps(1, monitorHz, false, false, false, false));
            Assert.Equal(0, FrameRatePolicy.EffectiveFps(1, monitorHz, false, true, false, false));
        }

        [Theory]
        [InlineData(60, 144, 2)]      // 72 is closer than 48 and Match display (144)
        [InlineData(30, 144, 3)]      // 48
        [InlineData(120, 144, 1)]     // 144
        [InlineData(60, 120, 2)]
        [InlineData(120, 120, 1)]
        [InlineData(30, 120, 3)]      // 40
        [InlineData(60, 60, 1)]
        [InlineData(30, 60, 2)]
        [InlineData(0, 144, 1)]
        public void Legacy_fps_values_migrate_to_the_nearest_divisor(int oldFps, int monitorHz, int expected)
        {
            Assert.Equal(expected, FrameRatePolicy.NearestDivisor(oldFps, monitorHz));
        }

        [Fact]
        public void The_setting_defaults_to_match_display_and_target_fps_follows_the_divisor()
        {
            var s = new Settings();
            Assert.Equal(0, s.WindowFps);
            Assert.Equal(1, s.WindowFpsDivisor);
            Assert.Equal(60, FrameRatePolicy.TargetFps(1, 0));
            Assert.Equal(144, FrameRatePolicy.TargetFps(1, 144));
            Assert.Equal(72, FrameRatePolicy.TargetFps(2, 144));
            Assert.Equal(48, FrameRatePolicy.TargetFps(3, 144));
        }
    }
}
