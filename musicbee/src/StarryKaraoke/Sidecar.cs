using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using System.Threading;

namespace MusicBeePlugin
{
    /// <summary>Names of the sidecar files the plugin and LyricLoom write next to an audio file.</summary>
    internal static class SidecarFiles
    {
        public static string Stem(string audioPath) =>
            Path.Combine(Path.GetDirectoryName(audioPath) ?? "",
                         Path.GetFileNameWithoutExtension(audioPath ?? ""));

        public static string Generic(string audioPath) => Stem(audioPath) + ".lrc";
        public static string Japanese(string audioPath) => Stem(audioPath) + ".japanese.lrc";
        public static string Romaji(string audioPath) => Stem(audioPath) + ".romaji.lrc";

        /// <summary>All three files the plugin watches or reads.</summary>
        public static IEnumerable<string> All(string audioPath)
        {
            yield return Generic(audioPath);
            yield return Japanese(audioPath);
            yield return Romaji(audioPath);
        }

        /// <summary>The sidecars to try for a Japanese display mode, most specific first. The generic
        /// .lrc is always the last fallback.</summary>
        public static string[] Candidates(string audioPath, JapaneseMode mode)
        {
            switch (mode)
            {
                case JapaneseMode.RomajiOnly:
                    return new[] { Romaji(audioPath), Japanese(audioPath), Generic(audioPath) };
                default:
                    return new[] { Japanese(audioPath), Generic(audioPath) };
            }
        }

        public static string PickExisting(string audioPath, JapaneseMode mode, Func<string, bool> exists)
        {
            if (string.IsNullOrEmpty(audioPath)) return null;
            foreach (var path in Candidates(audioPath, mode))
                if (exists(path)) return path;
            return null;
        }
    }

    /// <summary>Decides whether a file-system event is for the playing song and is newer than the copy
    /// the window already shows. Kept plain so the debounce/reload rule can be tested without watching
    /// a real directory.</summary>
    internal sealed class SidecarTracker
    {
        private readonly string _stem;
        public DateTime LastSeenUtc { get; private set; }

        public SidecarTracker(string audioPath, DateTime lastSeenUtc = default(DateTime))
        {
            _stem = Path.GetFileNameWithoutExtension(audioPath ?? "");
            LastSeenUtc = lastSeenUtc;
        }

        public bool IsForSong(string path)
        {
            var name = Path.GetFileName(path ?? "");
            if (!name.EndsWith(".lrc", StringComparison.OrdinalIgnoreCase)) return false;
            var stem = name.Substring(0, name.Length - 4);
            if (stem.EndsWith(".japanese", StringComparison.OrdinalIgnoreCase))
                stem = stem.Substring(0, stem.Length - ".japanese".Length);
            else if (stem.EndsWith(".romaji", StringComparison.OrdinalIgnoreCase))
                stem = stem.Substring(0, stem.Length - ".romaji".Length);
            return stem.Equals(_stem, StringComparison.OrdinalIgnoreCase);
        }

        public bool ShouldReload(string path, DateTime writeUtc) =>
            IsForSong(path) && writeUtc > LastSeenUtc;

        public void Mark(DateTime writeUtc)
        {
            if (writeUtc > LastSeenUtc) LastSeenUtc = writeUtc;
        }
    }

    /// <summary>A FileSystemWatcher over the playing song's folder. Events are debounced by 500 ms and
    /// checked against the modification time of the last copy the window loaded.</summary>
    internal sealed class SidecarWatcher : IDisposable
    {
        private readonly FileSystemWatcher _watcher;
        private readonly Timer _debounce;
        private readonly SidecarTracker _tracker;
        private readonly Action<string> _changed;
        private readonly Action<Exception> _log;
        private readonly object _gate = new object();
        private string _pendingPath;
        private DateTime _pendingUtc;
        private bool _disposed;

        public string AudioPath { get; }

        public SidecarWatcher(string audioPath, Action<string> changed, Action<Exception> log)
        {
            AudioPath = audioPath;
            _changed = changed;
            _log = log;
            _tracker = new SidecarTracker(audioPath);

            var newest = DateTime.MinValue;
            foreach (var path in SidecarFiles.All(audioPath))
            {
                try
                {
                    if (!File.Exists(path)) continue;
                    var writeUtc = File.GetLastWriteTimeUtc(path);
                    if (writeUtc > newest) newest = writeUtc;
                }
                catch (Exception) { }
            }
            _tracker.Mark(newest);

            _debounce = new Timer(Flush, null, Timeout.Infinite, Timeout.Infinite);
            var folder = Path.GetDirectoryName(audioPath);
            if (string.IsNullOrEmpty(folder) || !Directory.Exists(folder)) return;

            _watcher = new FileSystemWatcher(folder, "*.lrc")
            {
                NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.Size | NotifyFilters.CreationTime,
                IncludeSubdirectories = false,
                EnableRaisingEvents = true
            };
            _watcher.Created += OnChanged;
            _watcher.Changed += OnChanged;
            _watcher.Renamed += OnRenamed;
        }

        private void OnChanged(object sender, FileSystemEventArgs e) => Queue(e.FullPath);

        private void OnRenamed(object sender, RenamedEventArgs e) => Queue(e.FullPath);

        private void Queue(string path)
        {
            if (_disposed || path == null) return;
            try
            {
                if (!_tracker.IsForSong(path)) return;
                var writeUtc = File.GetLastWriteTimeUtc(path);
                if (!_tracker.ShouldReload(path, writeUtc)) return;
                lock (_gate)
                {
                    if (writeUtc >= _pendingUtc)
                    {
                        _pendingUtc = writeUtc;
                        _pendingPath = path;
                    }
                }
                _debounce.Change(500, Timeout.Infinite);
            }
            catch (Exception e)
            {
                _log?.Invoke(e);
            }
        }

        private void Flush(object state)
        {
            string path;
            DateTime writeUtc;
            lock (_gate)
            {
                path = _pendingPath;
                writeUtc = _pendingUtc;
                _pendingPath = null;
                _pendingUtc = DateTime.MinValue;
            }
            if (_disposed || path == null) return;
            try
            {
                if (!_tracker.ShouldReload(path, writeUtc)) return;
                _tracker.Mark(writeUtc);
                _changed?.Invoke(path);
            }
            catch (Exception e)
            {
                _log?.Invoke(e);
            }
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            try { _debounce.Dispose(); } catch (Exception) { }
            try
            {
                if (_watcher != null)
                {
                    _watcher.EnableRaisingEvents = false;
                    _watcher.Created -= OnChanged;
                    _watcher.Changed -= OnChanged;
                    _watcher.Renamed -= OnRenamed;
                    _watcher.Dispose();
                }
            }
            catch (Exception) { }
        }
    }

    /// <summary>Chooses between MusicBee's lyrics and a sidecar. A sidecar is preferred when it has
    /// word timing and MusicBee's copy does not, and always when the caller just saw it change.</summary>
    internal static class LyricsSelector
    {
        private static readonly Regex HasTime = new Regex(@"\[\d+:\d+", RegexOptions.Compiled);
        private static readonly Regex HasWordTime = new Regex(@"<\d+:\d+", RegexOptions.Compiled);

        public static bool HasSyncedLyrics(string lrc) => !string.IsNullOrEmpty(lrc) && HasTime.IsMatch(lrc);
        public static bool HasWordTiming(string lrc) => !string.IsNullOrEmpty(lrc) && HasWordTime.IsMatch(lrc);

        public static string Choose(string musicBeeLyrics, string fileLyrics, bool preferFile)
        {
            var mbTimed = HasSyncedLyrics(musicBeeLyrics);
            var fileTimed = HasSyncedLyrics(fileLyrics);
            if (fileTimed && (preferFile || !mbTimed || (HasWordTiming(fileLyrics) && !HasWordTiming(musicBeeLyrics))))
                return fileLyrics;
            return mbTimed ? musicBeeLyrics : null;
        }
    }
}
