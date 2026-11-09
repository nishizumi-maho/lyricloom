using System;
using System.IO;
using System.Linq;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class SettingsTests
    {
        private sealed class TempFolder : IDisposable
        {
            public string Path { get; }

            public TempFolder()
            {
                Path = System.IO.Path.Combine(System.IO.Path.GetTempPath(),
                    "StarryKaraokeTests", Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(Path);
            }

            public string Write(string name, string text)
            {
                var path = System.IO.Path.Combine(Path, name);
                File.WriteAllText(path, text);
                return path;
            }

            public void Dispose()
            {
                try { Directory.Delete(Path, true); } catch (Exception) { }
            }
        }

        [Fact]
        public void Validate_clamps_every_numeric_and_repairs_enums_and_colours()
        {
            var s = new Settings
            {
                TextScale = double.NaN,
                StarDensity = -5,
                TransitionSpeed = double.PositiveInfinity,
                LyricsOffsetMs = -123456,
                IntroLeadMs = -1,
                WindowFps = 999,
                VideoFps = 5,
                Japanese = (JapaneseMode)42,
                AutoOpenLyrics = (AutoOpenLyrics)99,
                OnUnsupportedSong = (UnsupportedSongAction)7,
                WindowWidth = double.NaN,
                WindowHeight = double.NaN,
                WindowLeft = double.PositiveInfinity,
                LitColor = "not a colour",
                WindowMonitor = null,
                FfmpegPath = null,
                LyricLoomPath = null
            };

            s.Validate();

            Assert.Equal(1.0, s.TextScale);
            Assert.Equal(0.25, s.StarDensity);
            Assert.Equal(1.0, s.TransitionSpeed);
            Assert.Equal(-10000, s.LyricsOffsetMs);
            Assert.Equal(0, s.IntroLeadMs);
            Assert.Equal(240, s.WindowFps);
            Assert.Equal(10, s.VideoFps);
            Assert.Equal(JapaneseMode.RomajiOnly, s.Japanese);
            Assert.Equal(AutoOpenLyrics.WordTimedOnly, s.AutoOpenLyrics);
            Assert.Equal(UnsupportedSongAction.Keep, s.OnUnsupportedSong);
            Assert.Equal(1100, s.WindowWidth);
            Assert.Equal(680, s.WindowHeight);
            Assert.True(double.IsNaN(s.WindowLeft));
            Assert.Equal("#FFCE5C", s.LitColor);
            Assert.Equal("", s.WindowMonitor);
            Assert.Equal("", s.FfmpegPath);
            Assert.Equal("", s.LyricLoomPath);
        }

        [Fact]
        public void Load_repairs_nan_negative_and_unknown_values_in_the_xml()
        {
            using (var temp = new TempFolder())
            {
                temp.Write(Settings.FileName,
                    "<Settings>" +
                    "<SettingsVersion>1</SettingsVersion>" +
                    "<TextScale>NaN</TextScale>" +
                    "<StarDensity>-4</StarDensity>" +
                    "<TransitionSpeed>99</TransitionSpeed>" +
                    "<LyricsOffsetMs>-99999</LyricsOffsetMs>" +
                    "<IntroLeadMs>-20</IntroLeadMs>" +
                    "<WindowFps>-5</WindowFps>" +
                    "<VideoFps>10000</VideoFps>" +
                    "<Japanese>99</Japanese>" +
                    "<AutoOpenLyrics>42</AutoOpenLyrics>" +
                    "<OnUnsupportedSong>Klingon</OnUnsupportedSong>" +
                    "<LineBursts>maybe</LineBursts>" +
                    "<WindowLeft>NaN</WindowLeft>" +
                    "<WindowWidth>NaN</WindowWidth>" +
                    "<FontFamily></FontFamily>" +
                    "<LitColor>not-a-colour</LitColor>" +
                    "</Settings>");

                string warning;
                var s = Settings.LoadWithReport(temp.Path, Settings.FileName, out warning);

                Assert.Null(warning);
                Assert.Equal(1.0, s.TextScale);
                Assert.Equal(0.25, s.StarDensity);
                Assert.Equal(3.0, s.TransitionSpeed);
                Assert.Equal(-10000, s.LyricsOffsetMs);
                Assert.Equal(0, s.IntroLeadMs);
                Assert.Equal(0, s.WindowFps);
                Assert.Equal(240, s.VideoFps);
                Assert.Equal(JapaneseMode.RomajiOnly, s.Japanese);
                Assert.Equal(AutoOpenLyrics.WordTimedOnly, s.AutoOpenLyrics);
                Assert.Equal(UnsupportedSongAction.Keep, s.OnUnsupportedSong);
                Assert.True(s.LineBursts);
                Assert.True(double.IsNaN(s.WindowLeft));
                Assert.Equal(1100, s.WindowWidth);
                Assert.False(string.IsNullOrEmpty(s.FontFamily));
                Assert.Equal("#FFCE5C", s.LitColor);
            }
        }

        [Fact]
        public void Old_settings_file_gets_word_timed_auto_open_and_keeps_its_values()
        {
            using (var temp = new TempFolder())
            {
                temp.Write(Settings.FileName, "<Settings><TextScale>1.2</TextScale><Glow>false</Glow></Settings>");
                string warning;
                var s = Settings.LoadWithReport(temp.Path, Settings.FileName, out warning);
                Assert.Null(warning);
                Assert.Equal(AutoOpenLyrics.WordTimedOnly, s.AutoOpenLyrics);
                Assert.False(s.AutoOpenFocus);
                Assert.Equal(1.2, s.TextScale);
                Assert.False(s.Glow);
            }
        }

        [Fact]
        public void New_install_defaults_to_word_timed_auto_open()
        {
            using (var temp = new TempFolder())
            {
                var s = Settings.Load(temp.Path);
                Assert.Equal(AutoOpenLyrics.WordTimedOnly, s.AutoOpenLyrics);
                Assert.Equal(UnsupportedSongAction.Keep, s.OnUnsupportedSong);
                Assert.False(s.AutoOpenFocus);
            }
        }

        [Fact]
        public void Save_is_crash_safe_and_keeps_the_previous_file_as_a_backup()
        {
            using (var temp = new TempFolder())
            {
                new Settings { TextScale = 1.1 }.Save(temp.Path);
                new Settings { TextScale = 1.7 }.Save(temp.Path);

                var main = File.ReadAllText(Path.Combine(temp.Path, Settings.FileName));
                var backup = File.ReadAllText(Path.Combine(temp.Path, Settings.FileName + ".bak"));
                Assert.Contains("1.7", main);
                Assert.Contains("1.1", backup);
                Assert.Empty(Directory.GetFiles(temp.Path, "*.tmp"));
                Assert.Equal(1.7, Settings.Load(temp.Path).TextScale);
            }
        }

        [Fact]
        public void Save_round_trips_the_new_auto_open_and_lyricloom_fields()
        {
            using (var temp = new TempFolder())
            {
                new Settings
                {
                    AutoOpenLyrics = AutoOpenLyrics.AnySynced,
                    OnUnsupportedSong = UnsupportedSongAction.Hide,
                    AutoOpenFocus = true,
                    LyricLoomPath = @"D:\Tools\LyricLoom.exe",
                    WindowMonitor = @"\\.\DISPLAY2"
                }.Save(temp.Path);

                var s = Settings.Load(temp.Path);
                Assert.Equal(AutoOpenLyrics.AnySynced, s.AutoOpenLyrics);
                Assert.Equal(UnsupportedSongAction.Hide, s.OnUnsupportedSong);
                Assert.True(s.AutoOpenFocus);
                Assert.Equal(@"D:\Tools\LyricLoom.exe", s.LyricLoomPath);
                Assert.Equal(@"\\.\DISPLAY2", s.WindowMonitor);
            }
        }

        [Fact]
        public void A_bad_file_is_kept_as_bad_timestamp_and_the_user_is_told_once()
        {
            using (var temp = new TempFolder())
            {
                var path = temp.Write(Settings.FileName, "<Settings><TextScale>1.0</TextScale>");
                string warning;
                var s = Settings.LoadWithReport(temp.Path, Settings.FileName, out warning);

                Assert.NotNull(warning);
                Assert.False(File.Exists(path));
                var bad = Directory.GetFiles(temp.Path, "*.bad-*").Single();
                Assert.Contains("<TextScale>1.0", File.ReadAllText(bad));
                Assert.Equal(1.0, s.TextScale);
                Assert.Equal(AutoOpenLyrics.WordTimedOnly, s.AutoOpenLyrics);

                s.Save(temp.Path);
                Assert.True(File.Exists(path));
                Assert.True(File.Exists(bad));
            }
        }

        [Fact]
        public void A_null_settings_root_is_treated_as_a_bad_file()
        {
            using (var temp = new TempFolder())
            {
                temp.Write(Settings.FileName,
                    "<Settings xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:nil=\"true\" />");
                string warning;
                var s = Settings.LoadWithReport(temp.Path, Settings.FileName, out warning);
                Assert.NotNull(warning);
                Assert.Equal(AutoOpenLyrics.WordTimedOnly, s.AutoOpenLyrics);
                Assert.NotEmpty(Directory.GetFiles(temp.Path, "*.bad-*"));
            }
        }

        [Fact]
        public void Uninstall_deletes_only_the_plugins_own_settings_files()
        {
            using (var temp = new TempFolder())
            {
                var settings = temp.Write(Settings.FileName, "<Settings />");
                var backup = temp.Write(Settings.FileName + ".bak", "<Settings />");
                var bad = temp.Write(Settings.FileName + ".bad-20261109-101010-000", "x");
                var tmp = temp.Write(Settings.FileName + ".0123abcd.tmp", "x");
                var other = temp.Write("mb_DesktopLyrics.xml", "<other />");
                var similar = temp.Write("mb_StarryKaraoke.xml.keep", "x");

                Assert.Equal(4, Settings.DeleteFiles(temp.Path));

                Assert.False(File.Exists(settings));
                Assert.False(File.Exists(backup));
                Assert.False(File.Exists(bad));
                Assert.False(File.Exists(tmp));
                Assert.True(File.Exists(other));
                Assert.True(File.Exists(similar));
                Assert.Equal(0, Settings.DeleteFiles(Path.Combine(temp.Path, "missing")));
            }
        }
    }
}
