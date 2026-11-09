using System;
using System.Windows;
using System.Windows.Interop;

namespace MusicBeePlugin
{
    /// <summary>FR-C-04: every dialog the karaoke window opens must be owned by it, and when the
    /// window is topmost (the default fullscreen party mode) the dialog must not open behind it.
    /// Native WinForms dialogs cannot be WPF-owned, so they get the window handle as owner and the
    /// window's Topmost flag is lowered for as long as the modal dialog is up.</summary>
    internal static class DialogPlacement
    {
        /// <summary>True when a dialog owned by <paramref name="owner"/> also needs the topmost flag
        /// so the fullscreen window cannot cover it.</summary>
        public static bool ShouldBeTopmost(Window owner) => owner != null && owner.Topmost;

        /// <summary>The window's native handle as a WinForms owner, or null when it has no handle yet.</summary>
        public static System.Windows.Forms.IWin32Window Win32Owner(Window owner)
        {
            if (owner == null) return null;
            try
            {
                var handle = new WindowInteropHelper(owner).Handle;
                return handle == IntPtr.Zero ? null : new HandleWindow(handle);
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>Temporarily lowers a topmost owner while a native modal dialog is shown, then
        /// restores it. The dialog is therefore visible above the karaoke window instead of behind
        /// it, and the window returns to topmost when the dialog closes.</summary>
        public static T AboveOwner<T>(Window owner, Func<T> show)
        {
            if (show == null) throw new ArgumentNullException(nameof(show));
            var restore = ShouldBeTopmost(owner);
            if (restore) owner.Topmost = false;
            try { return show(); }
            finally
            {
                if (restore)
                {
                    try { owner.Topmost = true; } catch (Exception) { }
                }
            }
        }

        private sealed class HandleWindow : System.Windows.Forms.IWin32Window
        {
            public IntPtr Handle { get; }
            public HandleWindow(IntPtr handle) { Handle = handle; }
        }
    }
}
