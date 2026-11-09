using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Controls;

namespace MusicBeePlugin
{
    /// <summary>The diagnostics text shown in Settings and from the context menu. It contains only
    /// the version numbers and the paths the user is shown in Settings: never lyrics.</summary>
    internal static class DiagnosticsReport
    {
        public static string Build(string pluginVersion, string musicBeeVersion,
                                   string romajiDictionary, string romajiError,
                                   string ffmpegPath, string ffmpegVersion,
                                   string lyricLoomPath, string logPath)
        {
            var text = new StringBuilder();
            text.AppendLine("Starry Karaoke plugin: " + Show(pluginVersion));
            text.AppendLine("MusicBee: " + Show(musicBeeVersion));
            if (string.IsNullOrEmpty(romajiDictionary))
                text.AppendLine("Romaji dictionary: not configured");
            else if (string.IsNullOrEmpty(romajiError))
                text.AppendLine("Romaji dictionary: found: " + romajiDictionary);
            else
            {
                text.AppendLine("Romaji dictionary: missing or unusable: " + romajiDictionary);
                text.AppendLine("  " + romajiError.Replace("\r", " ").Replace("\n", " "));
            }
            text.AppendLine("ffmpeg: " + (string.IsNullOrEmpty(ffmpegPath)
                ? "not found"
                : ffmpegPath + (string.IsNullOrEmpty(ffmpegVersion) ? "" : "  (" + ffmpegVersion + ")")));
            text.AppendLine("LyricLoom: " + (string.IsNullOrEmpty(lyricLoomPath) ? "not found" : lyricLoomPath));
            text.AppendLine("Log: " + Show(logPath));
            return text.ToString().TrimEnd();
        }

        public static bool OpenLogFolder(string logPath)
        {
            try
            {
                var folder = Path.GetDirectoryName(logPath) ?? "";
                if (File.Exists(logPath))
                {
                    Process.Start(new ProcessStartInfo("explorer.exe", "/select,\"" + logPath + "\"")
                    {
                        UseShellExecute = true
                    });
                    return true;
                }
                if (Directory.Exists(folder))
                {
                    Process.Start(new ProcessStartInfo("explorer.exe", "\"" + folder + "\"")
                    {
                        UseShellExecute = true
                    });
                    return true;
                }
            }
            catch (Exception) { }
            return false;
        }

        private static string Show(string value) => string.IsNullOrWhiteSpace(value) ? "unknown" : value;
    }

    /// <summary>Small window behind the context menu's "Diagnostics..." item: the same text as the
    /// Settings section, with Copy and Open log folder.</summary>
    internal sealed class DiagnosticsWindow : Window
    {
        public DiagnosticsWindow(string text, string logPath)
        {
            Title = "Starry Karaoke — Diagnostics";
            Width = 620;
            SizeToContent = SizeToContent.Height;
            ResizeMode = ResizeMode.CanResize;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

            var panel = new StackPanel { Margin = new Thickness(14) };
            var box = new TextBox
            {
                Text = text ?? "",
                IsReadOnly = true,
                AcceptsReturn = true,
                TextWrapping = TextWrapping.Wrap,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                MinHeight = 150,
                MaxHeight = 420
            };
            panel.Children.Add(box);

            var buttons = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right,
                Margin = new Thickness(0, 12, 0, 0)
            };
            var copy = new Button { Content = "Copy", Width = 92, Margin = new Thickness(0, 0, 8, 0) };
            copy.Click += (s, e) => Safe.Run(() =>
            {
                Clipboard.SetText(box.Text);
                copy.Content = "Copied";
            }, null);
            var open = new Button { Content = "Open log folder", Width = 128, Margin = new Thickness(0, 0, 8, 0) };
            open.Click += (s, e) => Safe.Run(() =>
            {
                if (!DiagnosticsReport.OpenLogFolder(logPath))
                    MessageBox.Show(this, "The log folder does not exist yet.", "Starry Karaoke",
                                    MessageBoxButton.OK, MessageBoxImage.Information);
            }, null);
            var close = new Button { Content = "Close", Width = 84, IsCancel = true };
            buttons.Children.Add(copy);
            buttons.Children.Add(open);
            buttons.Children.Add(close);
            panel.Children.Add(buttons);
            Content = panel;
        }
    }
}
