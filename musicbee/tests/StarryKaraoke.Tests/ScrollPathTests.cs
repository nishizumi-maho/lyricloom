using System;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class ScrollPathTests
    {
        private const double FrameSeconds = 1.0 / 144.0;

        private static ScrollPath TenLines()
        {
            var centers = new double[10];
            var starts = new double[10];
            for (var i = 0; i < 10; i++)
            {
                centers[i] = 200 + i * 120 + (i % 3) * 7;
                starts[i] = 1000 + i * 2000;
            }
            return new ScrollPath(centers, starts, 1.0, 90);
        }

        /// <summary>Design section 3: at 144 frames/s across ten lines the shown position is
        /// continuous, the largest step is bounded by the path's peak velocity, and a velocity
        /// jump is no larger than one frame of the path's acceleration.</summary>
        [Fact]
        public void Ten_lines_at_144_fps_have_no_step_or_velocity_jump_above_the_path_bounds()
        {
            var path = TenLines();
            var end = 1000 + 9 * 2000 + 2000;
            var positions = new System.Collections.Generic.List<double>();
            for (var t = 0.0; t <= end; t += FrameSeconds * 1000.0) positions.Add(path.PositionAt(t));

            var maxStep = 0.0;
            var maxVelocityJump = 0.0;
            var previousVelocity = 0.0;
            for (var i = 1; i < positions.Count; i++)
            {
                var step = Math.Abs(positions[i] - positions[i - 1]);
                maxStep = Math.Max(maxStep, step);
                var velocity = (positions[i] - positions[i - 1]) / FrameSeconds;
                if (i > 1) maxVelocityJump = Math.Max(maxVelocityJump, Math.Abs(velocity - previousVelocity));
                previousVelocity = velocity;
            }

            Assert.True(maxStep <= path.PeakVelocity * FrameSeconds + 0.000001,
                $"step {maxStep:0.0000} px exceeds {path.PeakVelocity * FrameSeconds:0.0000} px");
            Assert.True(maxVelocityJump <= path.PeakAcceleration * FrameSeconds + 0.01,
                $"velocity jump {maxVelocityJump:0.000} px/s exceeds one frame of acceleration");
        }

        [Fact]
        public void Every_line_is_centred_at_its_start_plus_lag()
        {
            var path = TenLines();
            for (var i = 0; i < 10; i++)
            {
                var center = 200 + i * 120 + (i % 3) * 7;
                Assert.Equal(center, path.PositionAt(1000 + i * 2000 + 100), 9);
            }
        }

        /// <summary>Two lines 100 ms apart at speed 1 use a 75/25 ms window (3:1) instead of the
        /// normal 300/100 ms one, and the previous glide ends where the next begins.</summary>
        [Fact]
        public void Close_lines_shrink_the_glide_to_the_gap_keeping_the_three_to_one_lead()
        {
            var path = new ScrollPath(new[] { 0.0, 200.0 }, new[] { 1000.0, 1100.0 }, 1.0, 90);
            Assert.Equal(0, path.PositionAt(1025), 6);     // 1100 - 75
            Assert.Equal(200, path.PositionAt(1125), 6);   // 1100 + 25
            Assert.Equal(100, path.PositionAt(1075), 6);   // smootherstep(0.5) * 200
        }

        /// <summary>After a seek the residual starts at the old shown position and decays without
        /// crossing the path; by 0.4 s it is under two pixels for a typical line-distance jump.</summary>
        [Fact]
        public void A_seek_residual_settles_within_400_ms_without_overshoot()
        {
            var residual = 300.0;
            var velocity = ScrollPath.ClampResidualVelocity(residual, -468.0);
            for (var ms = 0.0; ms <= 400; ms += 1)
            {
                var value = ScrollPath.ResidualAt(residual, velocity, ms / 1000.0);
                Assert.True(value >= 0, $"residual crossed zero at {ms} ms");
            }
            Assert.True(Math.Abs(ScrollPath.ResidualAt(residual, velocity, 0.4)) < 2);
        }
    }
}
