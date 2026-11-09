using System;
using System.Collections.Generic;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class PlaybackClockTests
    {
        private const double FrameMs = 1000.0 / 144.0;

        /// <summary>Design section 1: ten polls per second with +-40 ms of timing jitter, evaluated
        /// at 144 frames/s, stay within 25 ms after the first second, never move backwards, and
        /// never step by more than one frame at the maximum correction rate.</summary>
        [Fact]
        public void Jittered_ten_hz_polls_track_the_song_without_jumps_at_144_fps()
        {
            var clock = new PlaybackClock();
            clock.Sample(0, true, 0);
            var samples = new List<(double At, double Pos)>();
            var random = new Random(12345);
            for (var k = 1; k <= 40; k++)
            {
                var at = k * 100.0 + (random.NextDouble() * 80.0 - 40.0);
                samples.Add((at, at));
            }
            samples.Sort((a, b) => a.At.CompareTo(b.At));

            var next = 0;
            var previous = double.NegativeInfinity;
            var maxErrorAfterOneSecond = 0.0;
            var maxStep = 0.0;
            for (var frame = 0; frame <= 144 * 4; frame++)
            {
                var t = frame * FrameMs;
                while (next < samples.Count && samples[next].At <= t)
                {
                    clock.Sample(samples[next].Pos, true, samples[next].At);
                    next++;
                }
                var now = clock.NowMs(t);
                if (frame > 0)
                {
                    maxStep = Math.Max(maxStep, now - previous);
                    Assert.True(now >= previous - 1e-9, $"the clock went back at {t:0.0} ms");
                }
                if (t >= 1000) maxErrorAfterOneSecond = Math.Max(maxErrorAfterOneSecond, Math.Abs(now - t));
                previous = now;
            }

            Assert.True(maxErrorAfterOneSecond < 25,
                $"error after one second was {maxErrorAfterOneSecond:0.00} ms");
            Assert.True(maxStep <= FrameMs * 1.05 + 1,
                $"largest 144 fps step was {maxStep:0.000} ms");
        }

        /// <summary>A two second seek is absorbed by one poll, not by minutes of 15% jumps.</summary>
        [Fact]
        public void A_two_second_seek_snaps_within_one_sample()
        {
            var clock = new PlaybackClock();
            clock.Sample(0, true, 0);
            for (var t = 0.0; t <= 500; t += FrameMs) clock.NowMs(t);

            clock.Sample(2500, true, 500);
            var now = clock.NowMs(500 + FrameMs);
            Assert.InRange(now, 2490, 2515);
        }

        /// <summary>Pausing freezes at the reported position; resuming starts from the new one.</summary>
        [Fact]
        public void Pause_freezes_and_resume_starts_from_the_reported_position()
        {
            var clock = new PlaybackClock();
            clock.Sample(0, true, 0);
            for (var t = 0.0; t <= 1000; t += FrameMs) clock.NowMs(t);

            clock.Sample(1000, false, 1000);
            for (var t = 1000.0; t <= 2000; t += FrameMs) Assert.Equal(1000, clock.NowMs(t), 6);

            clock.Sample(1000, true, 2000);
            var resumed = clock.NowMs(2000 + FrameMs);
            Assert.InRange(resumed, 1005, 1020);
            Assert.True(clock.Playing);
        }
    }
}
