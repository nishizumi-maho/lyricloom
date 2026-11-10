using System.Windows;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class FullscreenLayoutTests
    {
        [Theory]
        [InlineData(1.0, 1920.0, 1080.0)]
        [InlineData(1.5, 1280.0, 720.0)]
        [InlineData(2.0, 960.0, 540.0)]
        public void Monitor_bounds_are_converted_from_device_pixels(double scale,
                                                                    double width, double height)
        {
            var r = FullscreenLayout.FromDevice(0, 0, 1920, 1080, scale, scale);
            Assert.Equal(0, r.Left);
            Assert.Equal(0, r.Top);
            Assert.Equal(width, r.Width);
            Assert.Equal(height, r.Height);
        }

        [Fact]
        public void A_secondary_monitor_keeps_its_offset()
        {
            var r = FullscreenLayout.FromDevice(-1920, 0, 1920, 1080, 1.5, 1.5);
            Assert.Equal(-1280, r.Left);
            Assert.Equal(0, r.Top);
            Assert.Equal(1280, r.Width);
            Assert.Equal(720, r.Height);
        }

        [Fact]
        public void A_bad_scale_falls_back_to_one()
        {
            var r = FullscreenLayout.FromDevice(0, 0, 100, 50, double.NaN, 0);
            Assert.Equal(new Rect(0, 0, 100, 50), r);
            Assert.True(FullscreenLayout.FromDevice(0, 0, 0, 50, 1, 1).IsEmpty);
        }
    }
}
