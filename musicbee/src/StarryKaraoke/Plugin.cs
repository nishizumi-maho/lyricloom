using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using System.Windows.Forms.Integration;

namespace MusicBeePlugin
{
    public partial class Plugin
    {
        private MusicBeeApiInterface _mb;
        private readonly PluginInfo _about = new PluginInfo();
        private Settings _settings;
        private KaraokeWindow _window;
        private SettingsWindow _settingsWindow;
        private int _songGeneration;

        private string StorageFolder => _mb.Setting_GetPersistentStoragePath();
        private static readonly Regex HasTime = new Regex(@"\[\d+:\d+", RegexOptions.Compiled);
        private static readonly Regex HasWordTime = new Regex(@"<\d+:\d+", RegexOptions.Compiled);

        public PluginInfo Initialise(IntPtr apiInterfacePtr)
        {
            _mb = new MusicBeeApiInterface();
            _mb.Initialise(apiInterfacePtr);
            var v = Assembly.GetExecutingAssembly().GetName().Version;
            _about.PluginInfoVersion = PluginInfoVersion;
            _about.Name = "Starry Karaoke";
            _about.Description = "Karaoke window with a starry night sky, word-by-word lyrics and romaji.";
            _about.Author = "nishizumi-maho";
            _about.TargetApplication = "";
            _about.Type = PluginType.General;
            _about.VersionMajor = (short)v.Major;
            _about.VersionMinor = (short)v.Minor;
            _about.Revision = (short)v.Build;
            _about.MinInterfaceVersion = MinInterfaceVersion;
            _about.MinApiRevision = MinApiRevision;
            _about.ReceiveNotifications = ReceiveNotificationFlags.PlayerEvents;
            _about.ConfigurationPanelHeight = 0;

            _settings = Settings.Load(StorageFolder);
            var dll = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? "";
            RomajiCore.Romanizer.UseFirstExistingDictionary(
                Path.Combine(dll, "RomajiLyrics", "IpaDic"),
                Path.Combine(StorageFolder, "Plugins", "RomajiLyrics", "IpaDic"),
                Path.Combine(dll, "IpaDic"));
            Log($"initialise {v} (MusicBee API {_mb.ApiRevision})");
            return _about;
        }

        public bool Configure(IntPtr panelHandle)
        {
            OnUi(OpenSettings);
            return true;
        }

        public void SaveSettings()
        {
            try { _settings.Save(StorageFolder); }
            catch (Exception e) { _mb.MB_Trace("Starry Karaoke: saving settings failed: " + e); }
        }

        public void Close(PluginCloseReason reason)
        {
            var reopen = _window != null;
            OnUi(() =>
            {
                if (_window != null) { _window.StoreBounds(_settings); _window.Close(); }
                _settings.WindowOpen = reopen;   // MusicBee closing: open again next time
                SaveSettings();
            }, wait: true);
        }

        public void Uninstall()
        {
            try { File.Delete(Path.Combine(StorageFolder, Settings.FileName)); } catch (Exception) { }
        }

        /// <summary>Appends to mb_StarryKaraoke.log in MusicBee's storage folder (MB_Trace is easy to miss).</summary>
        private void Log(string message)
        {
            try
            {
                var path = Path.Combine(StorageFolder, "mb_StarryKaraoke.log");
                if (File.Exists(path) && new FileInfo(path).Length > 1_000_000)
                {
                    var old = path + ".old";
                    if (File.Exists(old)) File.Delete(old);
                    File.Move(path, old);
                }
                File.AppendAllText(path, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} {message}{Environment.NewLine}");
            }
            catch (Exception) { }
        }

        public void ReceiveNotification(string sourceFileUrl, NotificationType type)
        {
            switch (type)
            {
                case NotificationType.PluginStartup:
                    Log("startup");
                    try
                    {
                        var item = _mb.MB_AddMenuItem("mnuView/Starry Karaoke", "Starry Karaoke: open the karaoke window",
                                                      (s, e) => OnUi(Toggle));
                        Log("menu item: " + (item?.Text ?? "null"));
                        _mb.MB_AddMenuItem("mnuTools/Starry Karaoke: record song video", "Starry Karaoke: record a karaoke video of the playing song",
                                           (s, e) => OnUi(RecordVideo));
                        if (_settings.WindowOpen) OnUi(Open);
                    }
                    catch (Exception e) { Log("startup failed: " + e); }
                    break;
                case NotificationType.TrackChanged:
                case NotificationType.NowPlayingLyricsReady:
                    if (_window != null) LoadSong();
                    break;
                case NotificationType.PlayStateChanged:
                    if (_settings.PartyMode)
                        ThreadPool.QueueUserWorkItem(_ =>
                        {
                            try
                            {
                                if (_mb.Player_GetPlayState() == PlayState.Playing) OnUi(PartyStart);
                            }
                            catch (Exception) { }
                        });
                    break;
            }
        }

        /// <summary>Party mode: bring the karaoke forward and fill the screen when playback starts.</summary>
        private void PartyStart()
        {
            if (!_settings.PartyMode) return;
            if (_window == null) Open();
            _window?.Activate();
            _window?.SetFullscreen(true);
        }

        // ---------------------------------------------------------------- windows

        private void Toggle()
        {
            if (_window != null) _window.Close();
            else Open();
        }

        private void Open()
        {
            if (_window != null) { _window.Activate(); return; }
            var controls = new PlayerControls
            {
                PlayPause = () => OnPlayer(() => _mb.Player_PlayPause()),
                Previous = () => OnPlayer(() => _mb.Player_PlayPreviousTrack()),
                Next = () => OnPlayer(() => _mb.Player_PlayNextTrack()),
                Seek = ms => OnPlayer(() => _mb.Player_SetPosition((int)Math.Max(0, ms))),
                SetVolume = v => OnPlayer(() => _mb.Player_SetVolume(Math.Max(0, Math.Min(1, v)))),
                SetMute = m => OnPlayer(() => _mb.Player_SetMute(m))
            };
            StartPolling();
            var w = new KaraokeWindow(_settings,
                                      () => (BitConverter.Int64BitsToDouble(Interlocked.Read(ref _polledPositionBits)),
                                             _polledPlaying, _polledVolume, _polledMute),
                                      controls);
            ElementHost.EnableModelessKeyboardInterop(w);
            w.SettingsRequested += (s, e) => OpenSettings();
            w.RecordRequested += (s, e) => RecordVideo();
            w.SkipIntroRequested += (s, e) => SkipIntro(force: true);
            w.OffsetChanged += ms => { _settings.LyricsOffsetMs = ms; SaveSettings(); };
            w.JapaneseModeChosen += mode =>
            {
                _settings.Japanese = mode;
                SaveSettings();
                w.ApplySettings(_settings);
                w.RefreshMenu();
                LoadSong();
            };
            w.Closing += (s, e) => w.StoreBounds(_settings);
            w.Closed += (s, e) =>
            {
                if (!ReferenceEquals(_window, w)) return;
                _window = null;
                _pollTimer?.Dispose();
                _pollTimer = null;
                _settings.WindowOpen = false;
                SaveSettings();
            };
            // WindowOpen is only saved as true by a clean MusicBee shutdown (Close), so a crash with the
            // window open does not make it open again, and crash again, at every start.
            _window = w;
            w.Show();
            if (_settings.PartyMode && _polledPlaying) w.SetFullscreen(true);
            LoadSong();
        }

        // ---------------------------------------------------------------- player, off the UI thread

        // The player API is never called from MusicBee's UI thread: while the player seeks it holds the
        // position and waits for that thread, so a position read from there deadlocks MusicBee (as when
        // going back in a song). A background timer reads it, and commands run on the thread pool.
        private System.Threading.Timer _pollTimer;
        private volatile bool _polledPlaying;
        // A double is not guaranteed atomic on 32-bit Windows, and MusicBee is a 32-bit process: keep
        // the bits in a long and read/write them through Interlocked.
        private long _polledPositionBits;
        private float _polledVolume = 1f;
        private bool _polledMute;

        private void StartPolling()
        {
            if (_pollTimer != null) return;
            _pollTimer = new System.Threading.Timer(_ =>
            {
                if (_window == null) return;
                try
                {
                    Interlocked.Exchange(ref _polledPositionBits, BitConverter.DoubleToInt64Bits(_mb.Player_GetPosition()));
                    _polledPlaying = _mb.Player_GetPlayState() == PlayState.Playing;
                    _polledVolume = _mb.Player_GetVolume();
                    _polledMute = _mb.Player_GetMute();
                }
                catch (Exception) { }
            }, null, 0, 100);
        }

        private readonly object _playerLock = new object();

        /// <summary>Runs a player command on the thread pool, one at a time, in the order given.</summary>
        private void OnPlayer(Action action)
        {
            ThreadPool.QueueUserWorkItem(_ =>
            {
                lock (_playerLock)
                {
                    try { action(); }
                    catch (Exception e) { Log("player command failed: " + e); }
                }
            });
        }

        private void OpenSettings()
        {
            if (_settingsWindow != null) { _settingsWindow.Activate(); return; }
            var before = _settings.Japanese;
            var dlg = new SettingsWindow(_settings, preview => _window?.ApplySettings(preview));
            ElementHost.EnableModelessKeyboardInterop(dlg);
            dlg.Closed += (s, e) =>
            {
                _settingsWindow = null;
                if (dlg.Result == null) return;
                _window?.StoreBounds(dlg.Result);
                dlg.Result.WindowOpen = _window != null;
                _settings = dlg.Result;
                SaveSettings();
                _window?.ApplySettings(_settings);
                _window?.RefreshMenu();
                if (_settings.Japanese != before) LoadSong();
                if (_settings.PartyMode && _polledPlaying) PartyStart();
            };
            _settingsWindow = dlg;
            dlg.Show();
        }

        // ---------------------------------------------------------------- video

        /// <summary>Asks where to save, then starts StarryKaraoke.Recorder.exe (next to this plugin) on the
        /// playing song. The recorder renders the whole song by itself, outside MusicBee.</summary>
        /// <summary>Reads the playing song off the UI thread (see OnPlayer), then asks where to save.</summary>
        private void RecordVideo()
        {
            var dll = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? "";
            var exe = Path.Combine(dll, "StarryKaraoke.Recorder.exe");
            if (!File.Exists(exe)) { Message("StarryKaraoke.Recorder.exe is not in the Plugins folder."); return; }
            var japanese = _settings.Japanese;
            ThreadPool.QueueUserWorkItem(_ =>
            {
                try
                {
                    var audio = _mb.NowPlaying_GetFileUrl();
                    if (string.IsNullOrEmpty(audio) || !File.Exists(audio)) { OnUi(() => Message("No local song is playing.")); return; }
                    var lrc = PickLyrics();
                    if (string.IsNullOrEmpty(lrc)) { OnUi(() => Message("This song has no synced lyrics.")); return; }
                    double duration = _mb.NowPlaying_GetDuration();
                    var title = _mb.NowPlaying_GetFileTag(MetaDataType.TrackTitle) ?? Path.GetFileNameWithoutExtension(audio);
                    var artist = _mb.NowPlaying_GetFileTag(MetaDataType.Artist) ?? "";
                    var header = string.IsNullOrEmpty(artist) ? title : title + "   —   " + artist;
                    if (japanese != JapaneseMode.JapaneseOnly && Lrc.IsJapanese(header))
                    {
                        var r = Lrc.Tidy(Romanize(header));
                        if (r.Length > 0) header = r;
                    }
                    OnUi(() => RecordVideo(exe, dll, audio, lrc, duration, title, artist, header));
                }
                catch (Exception e) { Log("record failed: " + e); }
            });
        }

        private void RecordVideo(string exe, string dll, string audio, string lrc, double duration, string title, string artist, string header)
        {
            string target;
            using (var dlg = new SaveFileDialog
            {
                Title = "Record karaoke video",
                Filter = "MP4 video (*.mp4)|*.mp4",
                FileName = SafeName((string.IsNullOrEmpty(artist) ? "" : artist + " - ") + title + " (karaoke)") + ".mp4",
                InitialDirectory = Environment.GetFolderPath(Environment.SpecialFolder.MyVideos),
                OverwritePrompt = true
            })
            {
                if (dlg.ShowDialog() != DialogResult.OK) return;
                target = dlg.FileName;
            }

            // the recorder gets its own copies: the lyrics and settings as they are now
            var work = Path.Combine(Path.GetTempPath(), "StarryKaraoke");
            Directory.CreateDirectory(work);
            var stamp = DateTime.Now.ToString("yyyyMMdd-HHmmss");
            var lrcPath = Path.Combine(work, stamp + ".lrc");
            File.WriteAllText(lrcPath, lrc);
            var settingsName = stamp + ".xml";
            _settings.Save(work, settingsName);
            var dict = new[] { Path.Combine(dll, "RomajiLyrics", "IpaDic"), Path.Combine(StorageFolder, "Plugins", "RomajiLyrics", "IpaDic"), Path.Combine(dll, "IpaDic") };
            var dictDir = Array.Find(dict, d => File.Exists(Path.Combine(d, "sys.dic"))) ?? "";

            string Q(string s) => "\"" + s.Replace("\"", "'") + "\"";
            var args = $"--lrc {Q(lrcPath)} --audio {Q(audio)} --out {Q(target)} --settings {Q(Path.Combine(work, settingsName))} " +
                       $"--title {Q(header)} --duration {duration.ToString(System.Globalization.CultureInfo.InvariantCulture)} --dict {Q(dictDir)}";
            Log("record: " + target);
            try
            {
                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(exe, args) { UseShellExecute = false, WorkingDirectory = dll });
            }
            catch (Exception e)
            {
                Log("could not start the recorder: " + e);
                Message("Could not start StarryKaraoke.Recorder.exe. See mb_StarryKaraoke.log for details.");
            }
        }

        private static string SafeName(string s)
        {
            foreach (var c in Path.GetInvalidFileNameChars()) s = s.Replace(c, '_');
            return s.Trim();
        }

        private static void Message(string text) =>
            System.Windows.MessageBox.Show(text, "Starry Karaoke", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Information);

        // ---------------------------------------------------------------- lyrics

        /// <summary>Reads and times the playing song's lyrics off the UI thread (romaji takes a moment),
        /// then hands them to the window. A newer song makes an older load drop its result.</summary>
        private void LoadSong()
        {
            var gen = Interlocked.Increment(ref _songGeneration);
            var mode = _settings.Japanese;
            ThreadPool.QueueUserWorkItem(_ =>
            {
                try
                {
                    var lrc = PickLyrics();
                    var title = _mb.NowPlaying_GetFileTag(MetaDataType.TrackTitle) ?? "";
                    var artist = _mb.NowPlaying_GetFileTag(MetaDataType.Artist) ?? "";
                    double duration = _mb.NowPlaying_GetDuration();
                    var raw = Lrc.Parse(lrc);
                    var lines = Timeline.Build(raw, duration, mode, Romanize);
                    var header = string.IsNullOrEmpty(artist) ? title : title + "   —   " + artist;
                    if (mode != JapaneseMode.JapaneseOnly && Lrc.IsJapanese(header)) header = Lrc.Tidy(Romanize(header)) is var r && r.Length > 0 ? r : header;
                    var next = NextSongText();
                    OnUi(() =>
                    {
                        if (gen != _songGeneration) return;
                        _lines = lines;
                        _window?.SetSong(lines, header, duration);
                        _window?.SetNextSong(next);
                        if (_settings.AutoSkipIntro) SkipIntro(force: false);
                    });
                }
                catch (Exception e) { Log("loading lyrics failed: " + e); }
            });
        }

        private string NextSongText()
        {
            try
            {
                var index = _mb.NowPlayingList_GetNextIndex(1);
                if (index < 0) return "";
                var title = _mb.NowPlayingList_GetFileTag(index, MetaDataType.TrackTitle) ?? "";
                var artist = _mb.NowPlayingList_GetFileTag(index, MetaDataType.Artist) ?? "";
                if (string.IsNullOrEmpty(title)) return "";
                return string.IsNullOrEmpty(artist) ? title : title + "   —   " + artist;
            }
            catch (Exception) { return ""; }
        }

        private List<KaraokeLine> _lines = new List<KaraokeLine>();

        /// <summary>Seeks the player to just before the first sung line. Automatic skips only happen near
        /// the start of the song, so a song the user already moved past the intro is left alone.</summary>
        private void SkipIntro(bool force)
        {
            var target = Timeline.IntroSkipTarget(_lines, _settings.IntroLeadMs);
            if (target == null) return;
            var offset = _settings.LyricsOffsetMs;
            OnPlayer(() =>
            {
                var pos = _mb.Player_GetPosition();
                if (pos >= target.Value - 300) return;
                if (!force && pos > 5000) return;
                _mb.Player_SetPosition((int)(target.Value + offset));
                Log($"skip intro: {pos} -> {target.Value:0}");
            });
        }

        private static string Romanize(string s)
        {
            try { return RomajiCore.Romanizer.ToRomaji(s) ?? ""; }
            catch (Exception) { return ""; }
        }

        /// <summary>The lyrics MusicBee has for the song; the .lrc next to the file when it has word
        /// timing and MusicBee's copy does not (or MusicBee has none with timing).</summary>
        private string PickLyrics()
        {
            string mbLyrics = null;
            try { mbLyrics = _mb.NowPlaying_GetLyrics(); } catch (Exception) { }
            if (string.IsNullOrEmpty(mbLyrics) || !HasTime.IsMatch(mbLyrics))
                try { mbLyrics = _mb.NowPlaying_GetDownloadedLyrics(); } catch (Exception) { }

            string fileLyrics = null;
            try
            {
                var url = _mb.NowPlaying_GetFileUrl();
                if (!string.IsNullOrEmpty(url) && File.Exists(url))
                {
                    var lrc = Path.ChangeExtension(url, ".lrc");
                    if (File.Exists(lrc)) fileLyrics = File.ReadAllText(lrc);
                }
            }
            catch (Exception) { }

            var mbTimed = !string.IsNullOrEmpty(mbLyrics) && HasTime.IsMatch(mbLyrics);
            var fileTimed = !string.IsNullOrEmpty(fileLyrics) && HasTime.IsMatch(fileLyrics);
            if (fileTimed && (!mbTimed || (HasWordTime.IsMatch(fileLyrics) && !HasWordTime.IsMatch(mbLyrics)))) return fileLyrics;
            return mbTimed ? mbLyrics : null;
        }

        // ---------------------------------------------------------------- threading

        /// <summary>Runs on MusicBee's UI thread, where the windows live.</summary>
        private void OnUi(Action action, bool wait = false)
        {
            void Safe()
            {
                try { action(); }
                catch (Exception e) { Log("error: " + e); }
            }
            var main = Control.FromHandle(_mb.MB_GetWindowHandle());
            if (main == null || !main.IsHandleCreated || !main.InvokeRequired) { Safe(); return; }
            try
            {
                if (wait) main.Invoke((Action)Safe);
                else main.BeginInvoke((Action)Safe);
            }
            catch (InvalidOperationException) { }
        }
    }
}
