using System;
using System.Windows;

namespace MusicBeePlugin
{
    /// <summary>Converts a monitor's device-pixel bounds into WPF device-independent units. A
    /// fullscreen window uses exact monitor bounds (not WindowState.Maximized) so it covers the
    /// taskbar as well.</summary>
    internal static class FullscreenLayout
    {
        public static Rect FromDevice(double left, double top, double width, double height,
                                      double scaleX, double scaleY)
        {
            if (double.IsNaN(scaleX) || double.IsInfinity(scaleX) || scaleX <= 0.01) scaleX = 1.0;
            if (double.IsNaN(scaleY) || double.IsInfinity(scaleY) || scaleY <= 0.01) scaleY = 1.0;
            if (width <= 0 || height <= 0) return Rect.Empty;
            return new Rect(left / scaleX, top / scaleY, width / scaleX, height / scaleY);
        }

        public static Rect FromDevice(System.Drawing.Rectangle bounds, double scaleX, double scaleY) =>
            FromDevice(bounds.Left, bounds.Top, bounds.Width, bounds.Height, scaleX, scaleY);
    }
}
