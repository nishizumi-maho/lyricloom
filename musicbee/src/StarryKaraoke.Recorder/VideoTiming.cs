using System;

namespace StarryKaraoke.Recorder
{
    /// <summary>FR-C-02: duration and frame-count math for a recording. MusicBee's library duration
    /// can be shorter than the real audio (VBR MP3 files with a bad Xing/LAME header are the common
    /// case), so the recorder probes the file and never renders a video that ends before the audio.
    /// The scene shows its ending message for the last 2.5 s; the video keeps that outro visible
    /// after the audio ends instead of stopping on the final sample.</summary>
    internal static class VideoTiming
    {
        /// <summary>How long the scene's ending message stays on screen after the audio ends.</summary>
        public const double OutroMs = MusicBeePlugin.KaraokeScene.EndingLeadMs;

        /// <summary>Accepts a probe that is close to MusicBee's estimate. A longer probe may exceed
        /// the estimate by up to two minutes (live rips and bad VBR headers are often far off); a
        /// shorter one only by ten seconds, so a broken probe can never cut the end of the song
        /// again. A wildly different probe is treated as a wrong file and ignored.</summary>
        public static double ChooseDurationMs(double libraryMs, double probedMs)
        {
            if (probedMs <= 0) return libraryMs;
            if (libraryMs <= 0) return probedMs;
            if (probedMs >= libraryMs)
                return probedMs - libraryMs <= 120000 ? probedMs : libraryMs;
            return libraryMs - probedMs <= 10000 ? probedMs : libraryMs;
        }

        /// <summary>The intro skip is clamped so at least one second of the song remains.</summary>
        public static double StartMs(double durationMs, double skipMs)
        {
            var limit = Math.Max(0, durationMs - 1000);
            return Math.Max(0, Math.Min(skipMs, limit));
        }

        /// <summary>Frame count covering the full audio duration plus the scene outro. Rounding up
        /// makes the video at least as long as the audio, so muxing without -shortest never drops
        /// the last audio samples.</summary>
        public static int FrameCount(double durationMs, double startMs, int fps, double outroMs = OutroMs)
        {
            if (fps <= 0) throw new ArgumentOutOfRangeException(nameof(fps));
            var milliseconds = durationMs + Math.Max(0, outroMs) - startMs;
            if (milliseconds <= 0) return 0;
            return (int)Math.Ceiling(milliseconds / 1000.0 * fps);
        }
    }
}
