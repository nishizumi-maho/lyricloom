using System;

namespace MusicBeePlugin
{
    /// <summary>
    /// When and how often the karaoke window should repaint. Kept free of WPF so the rules can be
    /// tested directly: a hidden, minimised or fully covered window does no work at all, a paused
    /// song only ticks slowly, and a configured frame rate never exceeds the monitor's refresh rate.
    /// </summary>
    internal static class FrameRatePolicy
    {
        public const int DefaultFps = 60;
        public const int PausedFps = 10;

        /// <summary>0 means "follow the window's monitor"; anything else is the requested cap.</summary>
        public static int TargetFps(int configuredFps, int monitorHz)
        {
            if (configuredFps > 0) return configuredFps;
            return monitorHz > 0 ? monitorHz : DefaultFps;
        }

        public static bool Suspend(bool minimized, bool hidden, bool fullyCovered) =>
            minimized || hidden || fullyCovered;

        /// <summary>Repaints per second, or 0 when rendering must stop entirely.</summary>
        public static int EffectiveFps(int configuredFps, int monitorHz, bool playing,
                                       bool minimized, bool hidden, bool fullyCovered)
        {
            if (Suspend(minimized, hidden, fullyCovered)) return 0;
            return playing ? TargetFps(configuredFps, monitorHz) : PausedFps;
        }
    }
}
