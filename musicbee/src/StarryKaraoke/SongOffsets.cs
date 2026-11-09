using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;

namespace MusicBeePlugin
{
    [DataContract]
    internal sealed class SongOffsetEntry
    {
        [DataMember(Name = "path", Order = 0)] public string Path;
        [DataMember(Name = "offsetMs", Order = 1)] public int OffsetMs;
    }

    [DataContract]
    internal sealed class SongOffsetFile
    {
        [DataMember(Name = "songs", Order = 0)] public List<SongOffsetEntry> Songs = new List<SongOffsetEntry>();
    }

    /// <summary>
    /// Per-song lyric delays, kept in a small JSON file in the plugin's storage folder and keyed by
    /// the canonical audio file path. The user's .lrc is never modified. Saves are atomic and the
    /// store survives a reload (the next instance reads the same file).
    /// </summary>
    internal sealed class SongOffsetStore
    {
        public const string FileName = "mb_StarryKaraoke.offsets.json";
        private const int LimitMs = 10000;

        private readonly string _path;
        private readonly object _gate = new object();
        private readonly Dictionary<string, int> _offsets =
            new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

        /// <summary>Set when the file could not be read or written; safe to log, contains no lyrics.</summary>
        public string LastError { get; private set; }

        public SongOffsetStore(string folder)
        {
            _path = Path.Combine(folder ?? "", FileName);
            Load();
        }

        public string PathOnDisk => _path;

        /// <summary>The audio path as it is stored: absolute, no quotes. A path that cannot be
        /// canonicalised is used trimmed.</summary>
        public static string KeyFor(string audioPath)
        {
            if (string.IsNullOrWhiteSpace(audioPath)) return "";
            var trimmed = audioPath.Trim().Trim('"');
            try { return Path.GetFullPath(trimmed); }
            catch (Exception) { return trimmed; }
        }

        public int Get(string audioPath)
        {
            var key = KeyFor(audioPath);
            if (key.Length == 0) return 0;
            lock (_gate)
            {
                int value;
                return _offsets.TryGetValue(key, out value) ? value : 0;
            }
        }

        public void Set(string audioPath, int offsetMs)
        {
            var key = KeyFor(audioPath);
            if (key.Length == 0) return;
            lock (_gate)
            {
                var value = Math.Max(-LimitMs, Math.Min(LimitMs, offsetMs));
                if (value == 0) _offsets.Remove(key);
                else _offsets[key] = value;
                Save();
            }
        }

        /// <summary>Resets one song's delay to zero and drops it from the file.</summary>
        public void Reset(string audioPath)
        {
            var key = KeyFor(audioPath);
            if (key.Length == 0) return;
            lock (_gate)
            {
                if (_offsets.Remove(key)) Save();
            }
        }

        public IReadOnlyDictionary<string, int> Snapshot()
        {
            lock (_gate) return new Dictionary<string, int>(_offsets, StringComparer.OrdinalIgnoreCase);
        }

        private void Load()
        {
            try
            {
                if (!File.Exists(_path)) return;
                SongOffsetFile file;
                var serializer = new DataContractJsonSerializer(typeof(SongOffsetFile));
                using (var stream = File.OpenRead(_path))
                    file = (SongOffsetFile)serializer.ReadObject(stream);
                if (file?.Songs == null) return;
                lock (_gate)
                {
                    foreach (var entry in file.Songs)
                    {
                        if (entry == null || string.IsNullOrWhiteSpace(entry.Path)) continue;
                        var key = KeyFor(entry.Path);
                        var value = Math.Max(-LimitMs, Math.Min(LimitMs, entry.OffsetMs));
                        if (key.Length > 0 && value != 0) _offsets[key] = value;
                    }
                }
            }
            catch (Exception e)
            {
                LastError = "could not read the per-song lyric delays: " + e.Message;
            }
        }

        /// <summary>Writes a temporary file and replaces the old one, so a crash mid-write leaves
        /// either the previous file or the new one.</summary>
        public void Save()
        {
            lock (_gate)
            {
                var tmp = _path + "." + Guid.NewGuid().ToString("N") + ".tmp";
                try
                {
                    var folder = Path.GetDirectoryName(_path);
                    if (!string.IsNullOrEmpty(folder)) Directory.CreateDirectory(folder);
                    var file = new SongOffsetFile
                    {
                        Songs = _offsets
                            .OrderBy(pair => pair.Key, StringComparer.OrdinalIgnoreCase)
                            .Select(pair => new SongOffsetEntry { Path = pair.Key, OffsetMs = pair.Value })
                            .ToList()
                    };
                    var serializer = new DataContractJsonSerializer(typeof(SongOffsetFile));
                    using (var stream = File.Create(tmp)) serializer.WriteObject(stream, file);
                    if (File.Exists(_path))
                    {
                        try { File.Replace(tmp, _path, null); }
                        catch (Exception)
                        {
                            File.Delete(_path);
                            File.Move(tmp, _path);
                        }
                    }
                    else
                    {
                        File.Move(tmp, _path);
                    }
                    LastError = null;
                }
                catch (Exception e)
                {
                    LastError = "could not save the per-song lyric delays: " + e.Message;
                }
                finally
                {
                    try { if (File.Exists(tmp)) File.Delete(tmp); }
                    catch (Exception) { }
                }
            }
        }
    }
}
