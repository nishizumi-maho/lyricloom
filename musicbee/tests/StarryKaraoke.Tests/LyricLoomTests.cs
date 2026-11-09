using System;
using System.Collections.Generic;
using System.IO;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class LyricLoomTests
    {
        private const string Registry = @"C:\Registry\LyricLoom.exe";
        private const string Local = @"C:\Users\me\AppData\Local\Programs\LyricLoom\LyricLoom.exe";
        private const string Programs = @"C:\Program Files\LyricLoom\LyricLoom.exe";
        private const string Configured = @"D:\Tools\LyricLoom.exe";

        private static LyricLoomLocator Locator(params string[] existing)
        {
            var files = new HashSet<string>(existing, StringComparer.OrdinalIgnoreCase);
            return new LyricLoomLocator(() => Registry, files.Contains, () => @"C:\Users\me\AppData\Local",
                                        () => @"C:\Program Files");
        }

        [Fact]
        public void Configured_path_wins_over_every_automatic_source()
        {
            var locator = Locator(Configured, Registry, Local, Programs);
            Assert.Equal(Configured, locator.Find(Configured));
        }

        [Fact]
        public void Registry_executable_is_used_when_the_setting_is_empty()
        {
            var locator = Locator(Registry, Local, Programs);
            Assert.Equal(Registry, locator.Find(""));
        }

        [Fact]
        public void Local_app_data_programs_is_the_next_fallback()
        {
            var locator = Locator(Local, Programs);
            Assert.Equal(Local, locator.Find(null));
        }

        [Fact]
        public void Program_files_is_the_last_fallback()
        {
            var locator = Locator(Programs);
            Assert.Equal(Programs, locator.Find("   "));
        }

        [Fact]
        public void Missing_everywhere_returns_null()
        {
            Assert.Null(Locator().Find(@"C:\nowhere\LyricLoom.exe"));
        }

        [Fact]
        public void A_missing_configured_path_falls_through_to_auto_discovery()
        {
            var locator = Locator(Registry);
            Assert.Equal(Registry, locator.Find(@"D:\gone\LyricLoom.exe"));
        }

        [Fact]
        public void Launch_arguments_quote_the_audio_path_and_reject_a_quote_in_it()
        {
            Assert.Equal("--process \"C:\\Music\\song.mp3\"", LyricLoomLauncher.ArgumentsFor(@"C:\Music\song.mp3"));
            Assert.Throws<ArgumentException>(() => LyricLoomLauncher.ArgumentsFor("C:\\Music\\bad\"name.mp3"));
        }

        [Fact]
        public void Download_page_points_at_the_release()
        {
            Assert.Equal("https://github.com/nishizumi-maho/lyricloom/releases/latest", LyricLoomLauncher.DownloadUrl);
        }
    }
}
