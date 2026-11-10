using System;

namespace MusicBeePlugin
{
    /// <summary>What a coverage check did to the rendering state.</summary>
    internal enum RenderTransition
    {
        None,
        Suspended,
        Resumed
    }

    /// <summary>FR-C-01: decides when a karaoke window must stop drawing because another window
    /// fully covers it, and when it may draw again. Kept as a plain class so the suspend/resume
    /// decision can be tested without a window, Win32 calls or a dispatcher.</summary>
    internal sealed class RenderSuspension
    {
        /// <summary>True while the window is fully covered: no frames, no polling, no clock sampling.</summary>
        public bool Suspended { get; private set; }

        /// <summary>The player poll is only useful while the window is drawing.</summary>
        public bool PollingAllowed => !Suspended;

        /// <summary>Applies one coverage reading. Returns <see cref="RenderTransition.Suspended"/> or
        /// <see cref="RenderTransition.Resumed"/> only when the state actually changed, so callers can
        /// start/stop their timers and frame subscription exactly once per transition.</summary>
        public RenderTransition Update(bool covered)
        {
            if (covered == Suspended) return RenderTransition.None;
            Suspended = covered;
            return covered ? RenderTransition.Suspended : RenderTransition.Resumed;
        }

        /// <summary>The window closed or became hidden: forget any previous suspension.</summary>
        public void Reset() => Suspended = false;
    }
}
