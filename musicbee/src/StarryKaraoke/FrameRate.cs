using System;

namespace MusicBeePlugin
{
    /// <summary>
    /// When and how often the karaoke window should repaint. Kept free of WPF so the rules can be
    /// tested directly: a hidden, minimised or fully covered window does no work at all, a paused
    /// song only ticks slowly, and the render rate is always the monitor's refresh rate divided by
    /// an integer (1, 2 or 3). A non-divisor such as 60 on a 144 Hz display alternates between two
    /// and three vsyncs and judders, so it is never offered.
    /// </summary>
    internal static class FrameRatePolicy
    {
        /// <summary>Fallback when the monitor's refresh rate is unknown.</summary>
        public const int DefaultFps = 60;

        /// <summary>1 = match the display, 2 = half refresh, 3 = third refresh.</summary>
        public static int NormalizeDivisor(int divisor) => divisor < 1 || divisor > 3 ? 1 : divisor;

        /// <summary>Frames per second for a divisor of the window monitor's refresh rate.</summary>
        public static int TargetFps(int divisor, int monitorHz)
        {
            var hz = monitorHz > 0 ? monitorHz : DefaultFps;
            return Math.Max(1, hz / NormalizeDivisor(divisor));
        }

        /// <summary>The offered divisor whose rate is closest to a legacy cap (ties keep the higher
        /// rate). Used to migrate settings written before the divisor setting existed.</summary>
        public static int NearestDivisor(int fps, int monitorHz)
        {
            if (fps <= 0) return 1;
            var hz = monitorHz > 0 ? monitorHz : DefaultFps;
            var best = 1;
            var bestDistance = (double)Math.Abs(hz - fps);
            for (var divisor = 2; divisor <= 3; divisor++)
            {
                var distance = Math.Abs((double)hz / divisor - fps);
                if (distance < bestDistance - 0.000001)
                {
                    best = divisor;
                    bestDistance = distance;
                }
            }
            return best;
        }

        /// <summary>A slow tick while paused, still an exact divisor of the monitor's refresh rate
        /// and kept between 10 and 15 fps.</summary>
        public static int PausedFps(int monitorHz)
        {
            if (monitorHz <= 0) return 12;
            var best = 12;
            var bestDistance = double.MaxValue;
            for (var divisor = 1; divisor <= monitorHz; divisor++)
            {
                if (monitorHz % divisor != 0) continue;
                var fps = monitorHz / divisor;
                if (fps < 10 || fps > 15) continue;
                var distance = Math.Abs(fps - 12.0);
                if (distance < bestDistance)
                {
                    best = fps;
                    bestDistance = distance;
                }
            }
            return best;
        }

        public static bool Suspend(bool minimized, bool hidden, bool fullyCovered) =>
            minimized || hidden || fullyCovered;

        /// <summary>Repaints per second, or 0 when rendering must stop entirely.</summary>
        public static int EffectiveFps(int divisor, int monitorHz, bool playing,
                                       bool minimized, bool hidden, bool fullyCovered)
        {
            if (Suspend(minimized, hidden, fullyCovered)) return 0;
            return playing ? TargetFps(divisor, monitorHz) : PausedFps(monitorHz);
        }
    }
}
