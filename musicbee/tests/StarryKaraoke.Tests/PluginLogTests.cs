using System;
using System.IO;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class PluginLogTests
    {
        [Fact]
        public void Log_rotates_before_it_grows_past_the_cap()
        {
            var folder = Path.Combine(Path.GetTempPath(), "StarryKaraokeTests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            var path = Path.Combine(folder, "mb_StarryKaraoke.log");
            try
            {
                File.WriteAllText(path, new string('x', 300));
                PluginLog.Append(path, "new entry", 100);
                Assert.True(File.Exists(path + ".old"));
                Assert.Equal(300, new FileInfo(path + ".old").Length);
                Assert.Contains("new entry", File.ReadAllText(path));
                Assert.DoesNotContain("xxx", File.ReadAllText(path));
            }
            finally
            {
                try { Directory.Delete(folder, true); } catch (Exception) { }
            }
        }
    }
}
