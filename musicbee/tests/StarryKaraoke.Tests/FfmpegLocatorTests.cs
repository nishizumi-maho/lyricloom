using System.Collections.Generic;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class FfmpegLocatorTests
    {
        private const string Configured = @"D:\Tools\ffmpeg.exe";
        private const string LyricLoom = @"C:\Users\me\AppData\Local\Programs\LyricLoom\LyricLoom.exe";
        private const string BundledFolder = @"C:\Users\me\AppData\Local\Programs\LyricLoom\_internal\imageio_ffmpeg\binaries";
        private const string Bundled = @"C:\Users\me\AppData\Local\Programs\LyricLoom\_internal\imageio_ffmpeg\binaries\ffmpeg-7.1-essentials_build.exe";
        private const string OnPath = @"C:\Tools\bin\ffmpeg.exe";

        private static FfmpegLocator Locator(HashSet<string> files, Dictionary<string, string[]> folders,
                                             string path = @"C:\Windows;C:\Tools\bin")
        {
            return new FfmpegLocator(() => LyricLoom, files.Contains,
                folder => folders.TryGetValue(folder, out var found) ? found : new string[0],
                () => path);
        }

        [Fact]
        public void The_setting_wins_over_the_lyricloom_copy_and_path()
        {
            var files = new HashSet<string> { Configured, Bundled, OnPath };
            var folders = new Dictionary<string, string[]> { [BundledFolder] = new[] { Bundled } };
            Assert.Equal(Configured, Locator(files, folders).Find(Configured));
        }

        [Fact]
        public void A_ffmpeg_bundled_with_lyricloom_is_found_by_glob_and_wins_over_path()
        {
            var files = new HashSet<string> { Bundled, OnPath };
            var folders = new Dictionary<string, string[]> { [BundledFolder] = new[] { Bundled } };
            Assert.Equal(Bundled, Locator(files, folders).Find(""));
        }

        [Fact]
        public void The_bundled_search_does_not_hard_code_the_version()
        {
            var other = BundledFolder + @"\ffmpeg-99.0-custom_build.exe";
            var files = new HashSet<string> { other, OnPath };
            var folders = new Dictionary<string, string[]> { [BundledFolder] = new[] { other } };
            Assert.Equal(other, Locator(files, folders).Find(null));
        }

        [Fact]
        public void Path_is_the_last_fallback()
        {
            var files = new HashSet<string> { OnPath };
            Assert.Equal(OnPath, Locator(files, new Dictionary<string, string[]>()).Find(""));
        }

        [Fact]
        public void A_missing_configured_file_falls_through_and_missing_everywhere_is_null()
        {
            var files = new HashSet<string> { OnPath };
            Assert.Equal(OnPath, Locator(files, new Dictionary<string, string[]>()).Find(@"D:\gone\ffmpeg.exe"));
            Assert.Null(Locator(new HashSet<string>(), new Dictionary<string, string[]>()).Find(""));
        }
    }
}
