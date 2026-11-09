using System;
using System.IO;
using System.Threading;

namespace MusicBeePlugin
{
    /// <summary>FR-C-09: startup work that must not run on MusicBee's UI thread.</summary>
    internal static class StartupTasks
    {
        /// <summary>Loads the romaji dictionary on a background thread when it is installed. The
        /// first Japanese lyric load then converts immediately instead of parsing IPADIC inline.</summary>
        public static void WarmupRomanizer(string dictionaryDirectory, Action<Exception> log, Action warmup = null)
        {
            ThreadPool.QueueUserWorkItem(_ => Safe.Run(() =>
            {
                if (!DictionaryExists(dictionaryDirectory)) return;
                (warmup ?? RomajiCore.Romanizer.Warmup)();
            }, log));
        }

        internal static bool DictionaryExists(string directory) =>
            !string.IsNullOrEmpty(directory) && File.Exists(Path.Combine(directory, "sys.dic"));
    }
}
