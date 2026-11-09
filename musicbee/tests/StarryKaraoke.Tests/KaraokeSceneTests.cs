using System;
using System.Linq;
using System.Windows;
using System.Windows.Media;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class KaraokeSceneTests
    {
        /// <summary>R4-25: a line-end burst lives for 0.8 seconds, not 0.8 milliseconds. It must be
        /// visible on the Text layer 400 ms after the line ends and gone at 900 ms.</summary>
        [Fact]
        public void Line_end_bursts_are_visible_for_most_of_a_second()
        {
            RunSta(() =>
            {
                var settings = new Settings
                {
                    LineBursts = true, ShowStars = true, ShowProgress = false, ShowHeader = false,
                    PartyMode = false, Glow = false
                };
                var lines = Timeline.Build(Lrc.Parse("[00:01.00]one\n"), 9000, JapaneseMode.RomajiOnly, null);
                var scene = new KaraokeScene(settings);
                scene.SetSong(lines, "Test", 9000);
                var size = new Size(640, 360);

                Assert.True(CountEllipses(scene, size, lines[0].EndMs + 400) > 0,
                            "a burst should be drawn 400 ms after the line end");
                Assert.Equal(0, CountEllipses(scene, size, lines[0].EndMs + 900));
            });
        }

        [Fact]
        public void Burst_progress_is_in_seconds()
        {
            Assert.Null(KaraokeScene.BurstProgress(-1));
            Assert.Equal(0, KaraokeScene.BurstProgress(0));
            Assert.Equal(0.5, KaraokeScene.BurstProgress(400));
            Assert.Equal(1, KaraokeScene.BurstProgress(800));
            Assert.Null(KaraokeScene.BurstProgress(900));
        }

        [Fact]
        public void Pixels_per_dip_accepts_only_valid_values()
        {
            var scene = new KaraokeScene(new Settings());
            Assert.Equal(1.0, scene.PixelsPerDip);
            scene.PixelsPerDip = 1.5;
            Assert.Equal(1.5, scene.PixelsPerDip);
            scene.PixelsPerDip = double.NaN;
            scene.PixelsPerDip = 0;
            scene.PixelsPerDip = double.PositiveInfinity;
            Assert.Equal(1.5, scene.PixelsPerDip);
        }

        /// <summary>The sweep edge is cached per quarter pixel. Rounding must never move it by more
        /// than half a bucket, so the moving edge stays visually continuous.</summary>
        [Fact]
        public void The_cached_gradient_edge_is_within_an_eighth_of_a_pixel()
        {
            for (var x = -5.0; x <= 5000; x += 0.013)
            {
                var snapped = KaraokeScene.LitBucket(x) / 4.0;
                Assert.True(Math.Abs(snapped - x) <= 0.125 + 1e-9,
                    $"edge {x} snapped to {snapped}");
            }
        }

        private static int CountEllipses(KaraokeScene scene, Size size, double t)
        {
            scene.Update(0.016, t, size);
            var visual = new DrawingVisual();
            using (var dc = visual.RenderOpen()) scene.Render(KaraokeScene.Layer.Text, dc, size, t);
            return CountEllipses(visual.Drawing);
        }

        private static int CountEllipses(Drawing drawing)
        {
            if (drawing is DrawingGroup group) return group.Children.Sum(CountEllipses);
            if (drawing is GeometryDrawing geometry && geometry.Geometry is EllipseGeometry) return 1;
            return 0;
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
    }
}
