using System;
using System.IO;
using System.Threading;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class StartupTasksTests
    {
        /// <summary>FR-C-09: when the dictionary is installed, the tagger warmup runs on a pool
        /// thread; when it is missing, nothing is started.</summary>
        [Fact]
        public void FR_C_09_the_romaji_dictionary_is_warmed_on_a_pool_thread_when_present()
        {
            using (var temp = new TempFolder())
            using (var called = new ManualResetEventSlim(false))
            using (var notCalled = new ManualResetEventSlim(false))
            {
                Assert.False(StartupTasks.DictionaryExists(temp.Path));
                File.WriteAllText(temp.File("sys.dic"), "fake dictionary");

                Assert.True(StartupTasks.DictionaryExists(temp.Path));

                var uiThread = Thread.CurrentThread.ManagedThreadId;
                var warmThread = 0;
                StartupTasks.WarmupRomanizer(temp.Path, null, () =>
                {
                    warmThread = Thread.CurrentThread.ManagedThreadId;
                    called.Set();
                });
                Assert.True(called.Wait(TimeSpan.FromSeconds(5)));
                Assert.NotEqual(uiThread, warmThread);

                StartupTasks.WarmupRomanizer(temp.File("missing"), null, () => notCalled.Set());
                Assert.False(notCalled.Wait(TimeSpan.FromMilliseconds(300)));
            }
        }
    }
}
