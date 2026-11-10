using System;
using System.Collections.Generic;
using System.Text;
using System.Windows;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class SmoothSceneTests
    {
        private const double FrameSeconds = 1.0 / 144.0;

        private static List<KaraokeLine> Lines()
        {
            var lrc = new StringBuilder();
            for (var i = 0; i < 10; i++) lrc.Append($"[00:{i * 2 + 1:00}.00]made up line {i}\n");
            return Timeline.Build(Lrc.Parse(lrc.ToString()), 22000, JapaneseMode.RomajiOnly, null);
        }

        private static KaraokeScene Scene(out List<KaraokeLine> lines)
        {
            var scene = new KaraokeScene(new Settings
            {
                ShowStars = false, ShowProgress = false, ShowHeader = false,
                LineBursts = false, Glow = false, GrowCurrentLine = true
            });
            lines = Lines();
            scene.SetSong(lines, "Test", 22000);
            return scene;
        }

        /// <summary>Design section 3's frame-sequence check, run on the real scene: the recorded
        /// scroll offset across ten lines at 144 fps stays within the pure path's continuity bounds.</summary>
        [Fact]
        public void The_real_scene_scrolls_within_the_path_bounds_for_ten_lines()
        {
            RunSta(() =>
            {
                var scene = Scene(out var lines);
                var size = new Size(1280, 720);
                double previous = double.NaN, previousVelocity = 0;
                var maxStep = 0.0;
                var maxVelocityJump = 0.0;
                for (var frame = 0; frame <= (int)(22 / FrameSeconds); frame++)
                {
                    var t = frame * FrameSeconds * 1000.0;
                    scene.Update(FrameSeconds, t, size);
                    var scroll = scene.ScrollOffset;
                    if (!double.IsNaN(previous))
                    {
                        var step = Math.Abs(scroll - previous);
                        maxStep = Math.Max(maxStep, step);
                        var velocity = (scroll - previous) / FrameSeconds;
                        maxVelocityJump = Math.Max(maxVelocityJump, Math.Abs(velocity - previousVelocity));
                        previousVelocity = velocity;
                    }
                    previous = scroll;
                }
                Assert.True(scene.ScrollPeakVelocity > 0);
                Assert.True(maxStep <= scene.ScrollPeakVelocity * FrameSeconds + 0.000001,
                    $"scene step {maxStep:0.0000} px exceeds the path bound");
                Assert.True(maxVelocityJump <= scene.ScrollPeakAcceleration * FrameSeconds + 0.01,
                    $"scene velocity jump {maxVelocityJump:0.000} px/s exceeds one frame of acceleration");
            });
        }

        /// <summary>A seek keeps the shown position and velocity continuous, then the residual
        /// settles below two pixels within 0.4 s without crossing the path.</summary>
        [Fact]
        public void A_seek_does_not_jump_and_settles_within_400_ms()
        {
            RunSta(() =>
            {
                var scene = Scene(out _);
                var size = new Size(1280, 720);
                var t = 0.0;
                for (; t < 8000; t += FrameSeconds * 1000.0) scene.Update(FrameSeconds, t, size);

                var before = scene.ScrollOffset;
                t = 13000;
                scene.Update(FrameSeconds, t, size);
                Assert.Equal(before, scene.ScrollOffset, 9);
                var sign = Math.Sign(scene.ScrollResidual);

                var start = t;
                for (; t < start + 400; t += FrameSeconds * 1000.0) scene.Update(FrameSeconds, t, size);
                scene.Update(FrameSeconds, start + 400, size);
                Assert.True(Math.Abs(scene.ScrollResidual) < 2,
                    $"residual after 0.4 s was {scene.ScrollResidual:0.00} px");
                Assert.Equal(sign, Math.Sign(scene.ScrollResidual));
            });
        }

        private static void RunSta(Action action)
        {
            Exception failure = null;
            var thread = new System.Threading.Thread(() =>
            {
                try { action(); }
                catch (Exception e) { failure = e; }
            });
            thread.SetApartmentState(System.Threading.ApartmentState.STA);
            thread.Start();
            thread.Join();
            if (failure != null) throw new Xunit.Sdk.XunitException(failure.ToString());
        }
        /// <summary>The recorder warms a segment up with one big step and then renders at a fixed dt.
        /// Because the path is a function of song time, that must land on the same offset as
        /// continuous playback, so separately rendered video parts join without a scroll jump.</summary>
        [Fact]
        public void A_recorder_warmup_lands_on_the_same_scroll_as_continuous_playback()
        {
            RunSta(() =>
            {
                var size = new Size(1280, 720);
                var continuous = Scene(out _);
                var segment = Scene(out _);
                var start = 4000.0;
                for (var t = 0.0; t <= start; t += 1000.0 / 30.0) continuous.Update(1.0 / 30.0, t, size);
                segment.Update(1.0, start, size);
                for (var t = start; t <= 8000; t += 1000.0 / 30.0)
                {
                    continuous.Update(1.0 / 30.0, t, size);
                    segment.Update(1.0 / 30.0, t, size);
                    Assert.Equal(continuous.ScrollOffset, segment.ScrollOffset, 9);
                    Assert.Equal(continuous.LineScale(continuous.CurrentLine(t)),
                                 segment.LineScale(segment.CurrentLine(t)), 9);
                }
            });
        }
    }
}
