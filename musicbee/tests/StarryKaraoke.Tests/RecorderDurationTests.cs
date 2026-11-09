using StarryKaraoke.Recorder;
using Xunit;

namespace StarryKaraoke.Tests
{
    /// <summary>FR-C-02: the recording must cover the real audio, not MusicBee's possibly short
    /// library estimate, and must keep the scene's outro visible.</summary>
    public class RecorderDurationTests
    {
        [Fact]
        public void FR_C_02_a_longer_probe_replaces_a_short_library_duration()
        {
            // A VBR MP3 whose header says 3:00 but whose audio runs 3:00.8.
            Assert.Equal(180800, VideoTiming.ChooseDurationMs(180000, 180800));
            // A longer-than-library probe is accepted within two minutes.
            Assert.Equal(240000, VideoTiming.ChooseDurationMs(180000, 240000));
            // A wildly different probe is a wrong file, not a longer song.
            Assert.Equal(180000, VideoTiming.ChooseDurationMs(180000, 600000));
        }

        [Fact]
        public void FR_C_02_a_shorter_probe_is_only_trusted_within_ten_seconds()
        {
            Assert.Equal(179000, VideoTiming.ChooseDurationMs(180000, 179000));
            Assert.Equal(180000, VideoTiming.ChooseDurationMs(180000, 120000));
            Assert.Equal(180000, VideoTiming.ChooseDurationMs(180000, 0));
            Assert.Equal(180800, VideoTiming.ChooseDurationMs(0, 180800));
        }

        [Fact]
        public void FR_C_02_frames_cover_the_full_audio_and_the_scene_outro()
        {
            // 60 s of audio + 2.5 s outro at 30 fps.
            Assert.Equal(1875, VideoTiming.FrameCount(60000, 0, 30));
            // A skipped intro shortens the video by exactly the skipped audio.
            Assert.Equal(1725, VideoTiming.FrameCount(60000, 5000, 30));
            // The real duration of the VBR example above is covered too.
            Assert.Equal(1899, VideoTiming.FrameCount(60800, 0, 30));
            // The outro can be disabled for a test or a future setting.
            Assert.Equal(1800, VideoTiming.FrameCount(60000, 0, 30, 0));
            Assert.Equal(0, VideoTiming.FrameCount(60000, 63000, 30));
        }

        [Fact]
        public void FR_C_02_the_intro_skip_always_leaves_one_second_of_song()
        {
            Assert.Equal(0, VideoTiming.StartMs(60000, -500));
            Assert.Equal(5000, VideoTiming.StartMs(60000, 5000));
            Assert.Equal(59000, VideoTiming.StartMs(60000, 70000));
        }

        [Fact]
        public void FR_C_02_ffmpegs_duration_line_is_parsed()
        {
            Assert.Equal(225670, AudioProbe.ParseDurationMilliseconds("  Duration: 00:03:45.67, start: 0.000000, bitrate: 320 kb/s"), 3);
            Assert.Equal(3723500, AudioProbe.ParseDurationMilliseconds("Duration: 01:02:03.5, start: 0.000000"), 3);
            Assert.Equal(0, AudioProbe.ParseDurationMilliseconds("Duration: N/A, bitrate: N/A"));
            Assert.Equal(0, AudioProbe.ParseDurationMilliseconds(""));
        }
    }
}
