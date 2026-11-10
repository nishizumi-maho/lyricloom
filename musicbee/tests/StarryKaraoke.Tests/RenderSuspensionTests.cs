using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class RenderSuspensionTests
    {
        /// <summary>FR-C-01: a covered window stops drawing and polling, and becomes drawable again
        /// as soon as any part is visible. The window's DispatcherTimer consumes this decision; the
        /// decision itself is plain and needs no WPF or Win32.</summary>
        [Fact]
        public void FR_C_01_rendering_suspends_when_covered_and_resumes_when_visible_again()
        {
            var gate = new RenderSuspension();
            Assert.False(gate.Suspended);
            Assert.True(gate.PollingAllowed);

            Assert.Equal(RenderTransition.Suspended, gate.Update(true));
            Assert.True(gate.Suspended);
            Assert.False(gate.PollingAllowed);

            // Repeated coverage readings do not restart timers or polling.
            Assert.Equal(RenderTransition.None, gate.Update(true));
            Assert.Equal(RenderTransition.None, gate.Update(true));

            Assert.Equal(RenderTransition.Resumed, gate.Update(false));
            Assert.False(gate.Suspended);
            Assert.True(gate.PollingAllowed);
            Assert.Equal(RenderTransition.None, gate.Update(false));
        }

        [Fact]
        public void FR_C_01_closing_the_window_forgets_a_previous_suspension()
        {
            var gate = new RenderSuspension();
            gate.Update(true);
            gate.Reset();
            Assert.False(gate.Suspended);
            Assert.Equal(RenderTransition.None, gate.Update(false));
        }
    }
}
