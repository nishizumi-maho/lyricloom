using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class DiagnosticsReportTests
    {
        [Fact]
        public void The_report_lists_only_the_supported_diagnostics()
        {
            var text = DiagnosticsReport.Build(
                "1.3.0", "3.5.8698 (API 51)", @"C:\Plugins\IpaDic", null,
                @"C:\Tools\ffmpeg.exe", "ffmpeg version 7.1", @"C:\Program Files\LyricLoom\LyricLoom.exe",
                @"C:\Plugins\mb_StarryKaraoke.log");

            Assert.Contains("Starry Karaoke plugin: 1.3.0", text);
            Assert.Contains("MusicBee: 3.5.8698 (API 51)", text);
            Assert.Contains("Romaji dictionary: found: C:\\Plugins\\IpaDic", text);
            Assert.Contains("ffmpeg: C:\\Tools\\ffmpeg.exe  (ffmpeg version 7.1)", text);
            Assert.Contains("LyricLoom: C:\\Program Files\\LyricLoom\\LyricLoom.exe", text);
            Assert.Contains("Log: C:\\Plugins\\mb_StarryKaraoke.log", text);
        }

        [Fact]
        public void Missing_components_and_errors_are_reported()
        {
            var text = DiagnosticsReport.Build(
                "1.3.0", "unknown", @"C:\Plugins\IpaDic", "boom\nsecond line",
                "", "", "", "");

            Assert.Contains("Romaji dictionary: missing or unusable", text);
            Assert.Contains("boom second line", text);
            Assert.Contains("ffmpeg: not found", text);
            Assert.Contains("LyricLoom: not found", text);
            Assert.Contains("Log: unknown", text);
        }
    }
}
