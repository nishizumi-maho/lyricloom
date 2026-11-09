using StarryKaraoke.Recorder;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class RecorderConcurrencyTests
    {
        /// <summary>R4-12: hardware encoders have driver session limits, so at most two segments
        /// run in parallel; software encoding uses half the logical processors, capped at eight.</summary>
        [Fact]
        public void Hardware_encoders_use_at_most_two_parts()
        {
            Assert.Equal(2, Renderer.WorkersFor("h264_nvenc -preset p5", 100000, 30, 16));
            Assert.Equal(1, Renderer.WorkersFor("h264_amf -quality quality", 100000, 30, 2));
            Assert.Equal(1, Renderer.WorkersFor("h264_qsv -global_quality 20", 100000, 30, 1));
        }

        [Fact]
        public void Software_encoding_uses_half_the_processors_within_limits()
        {
            Assert.Equal(1, Renderer.WorkersFor("libx264 -preset fast", 100000, 30, 1));
            Assert.Equal(2, Renderer.WorkersFor("libx264 -preset fast", 100000, 30, 4));
            Assert.Equal(4, Renderer.WorkersFor("libx264 -preset fast", 100000, 30, 8));
            Assert.Equal(8, Renderer.WorkersFor("libx264 -preset fast", 100000, 30, 32));
        }

        [Fact]
        public void Very_short_videos_still_render_one_part()
        {
            Assert.Equal(1, Renderer.WorkersFor("libx264 -preset fast", 30, 30, 16));
            Assert.Equal(1, Renderer.WorkersFor("h264_nvenc", 30, 30, 16));
        }
    }
}
