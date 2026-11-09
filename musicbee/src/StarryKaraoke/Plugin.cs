using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
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
        private int _autoOpenGeneration;

        private string _storageFolder;
        private string _logPath;
        private Control _mainWindow;

        private string _currentSongUrl = "";
        /// <summary>FR-C-06: whether the current song's file exists. Refreshed on the thread pool so
        /// MusicBee's UI thread never probes a network share.</summary>
        private volatile bool _currentSongIsLocal;
        private string _dismissedSongUrl;
        private bool _autoAttemptedForSong;
        private bool _shuttingDown;
        private string _lastHeader = "";
        private double _lastDuration;
        private SongOffsetStore _songOffsets;
        private SidecarWatcher _sidecarWatcher;
        private string _sidecarWatcherPending;
        private int _sidecarWatcherGeneration;
        private readonly object _sidecarWatcherLock = new object();
        private bool _lyricLoomStarting;
        private readonly LyricLoomRequestGuard _lyricLoomRequests = new LyricLoomRequestGuard();
        private System.Windows.Threading.Dispatcher _safetyDispatcher;
        private bool _dispatcherMessageShown;

        private string StorageFolder => _storageFolder ?? (_storageFolder = _mb.Setting_GetPersistentStoragePath());
        private readonly List<System.Threading.Timer> _autoOpenTimers = new List<System.Threading.Timer>();

        private sealed class SongSnapshot
        {
            public string Url = "", MbLyrics = "", Title = "", Artist = "", Next = "";
            public double Duration;
        }

        public PluginInfo Initialise(IntPtr apiInterfacePtr)
        {
            _mb = new MusicBeeApiInterface();
            _mb.Initialise(apiInterfacePtr);
            _storageFolder = _mb.Setting_GetPersistentStoragePath();
            _mainWindow = Control.FromHandle(_mb.MB_GetWindowHandle());
            var dll = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? "";
            _logPath = Path.Combine(dll, "mb_StarryKaraoke.log");

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
            _about.ReceiveNotifications = ReceiveNotificationFlags.PlayerEvents | ReceiveNotificationFlags.DownloadEvents;
            _about.ConfigurationPanelHeight = 0;

            string warning;
            _settings = Settings.LoadWithReport(StorageFolder, Settings.FileName, out warning);
            _songOffsets = new SongOffsetStore(StorageFolder);
            RomajiCore.Romanizer.UseFirstExistingDictionary(
                Path.Combine(dll, "RomajiLyrics", "IpaDic"),
                Path.Combine(StorageFolder, "Plugins", "RomajiLyrics", "IpaDic"),
                Path.Combine(dll, "IpaDic"));
            // FR-C-09: parse the dictionary off the UI thread before the first Japanese song.
            StartupTasks.WarmupRomanizer(RomajiCore.Romanizer.DictionaryDirectory, LogException);

            if (_mainWindow != null && _mainWindow.InvokeRequired)
                _mainWindow.BeginInvoke((Action)InstallDispatcherSafetyNet);
            else
                InstallDispatcherSafetyNet();

            Log($"initialise {v} (MusicBee API {_mb.ApiRevision})");
            var swept = RecordingTemp.SweepStale(RecordingTemp.StaleAfter);
            if (swept > 0) Log("removed " + swept + " stale recording temp folder(s)");
            Log("romaji dictionary: " + RomajiCore.Romanizer.DictionaryDirectory +
                (File.Exists(Path.Combine(RomajiCore.Romanizer.DictionaryDirectory, "sys.dic")) ? "" : " (missing sys.dic)"));
            if (_songOffsets != null && !string.IsNullOrEmpty(_songOffsets.LastError))
                Log(_songOffsets.LastError);
            if (!string.IsNullOrEmpty(warning))
            {
                Log(warning);
                OnUi(() => Message(warning));
            }
            return _about;
        }

        public bool Configure(IntPtr panelHandle)
        {
            OnUi(() => Safe.Run(OpenSettings, LogException));
            return true;
        }

        public void SaveSettings()
        {
            try { _settings.Save(StorageFolder); }
            catch (Exception e) { Log("saving settings failed: " + e); }
        }

        public void Close(PluginCloseReason reason)
        {
            _shuttingDown = true;
            DisposeAutoOpenTimers();
            DisposeSidecarWatcher();
            var reopen = _window != null;
            OnUi(() =>
            {
                if (_window != null)
                {
                    _window.StoreBounds(_settings);
                    _window.CloseForShutdown();
                }
                _settings.WindowOpen = reopen;   // MusicBee closing: open again next time
                SaveSettings();
            }, wait: true);
        }

        public void Uninstall()
        {
            // MusicBee calls this when the user uninstalls the plugin: remove everything the plugin
            // created (settings, their backups, the log, which holds song paths). Nothing else.
            Settings.DeleteFiles(StorageFolder);
            // FR-C-07: a recording's private copies (lyrics.lrc, settings.xml) live in
            // %TEMP%\StarryKaraoke\rec-*, and older plugin versions left .lrc/.xml files directly in
            // that folder. There is no later startup sweep after an uninstall, so remove them now,
            // with no age limit.
            RecordingTemp.SweepAll();
            foreach (var logPath in new[] { _logPath, string.IsNullOrEmpty(_storageFolder) ? null
                                                           : Path.Combine(_storageFolder, "mb_StarryKaraoke.log") })
            {
                if (string.IsNullOrEmpty(logPath)) continue;
                foreach (var file in new[] { logPath, logPath + ".old" })
                {
                    try { if (File.Exists(file)) File.Delete(file); }
                    catch (Exception) { }
                }
            }
        }

        /// <summary>Appends to mb_StarryKaraoke.log next to the plugin DLL. Rotated at 1 MB; never
        /// contains lyrics text.</summary>
        private void Log(string message)
        {
            try { PluginLog.Append(_logPath, message); }
            catch (Exception)
            {
                try
                {
                    if (!string.IsNullOrEmpty(_storageFolder))
                        PluginLog.Append(Path.Combine(_storageFolder, "mb_StarryKaraoke.log"), message);
                }
                catch (Exception) { }
            }
        }

        private void LogException(Exception e) => Log("error: " + e);

        private void InstallDispatcherSafetyNet()
        {
            try
            {
                var dispatcher = System.Windows.Threading.Dispatcher.CurrentDispatcher;
                if (_safetyDispatcher == dispatcher) return;
                var installed = Safe.InstallDispatcherHandler(dispatcher, LogException, message =>
                    {
                        if (_dispatcherMessageShown) return;
                        _dispatcherMessageShown = true;
                        _window?.ShowMessage(message);
                    });
                if (installed) _safetyDispatcher = dispatcher;
            }
            catch (Exception e)
            {
                Log("could not install the dispatcher safety net: " + e.Message);
            }
        }

        public void ReceiveNotification(string sourceFileUrl, NotificationType type)
        {
            Safe.Run(() => HandleNotification(sourceFileUrl, type), LogException);
        }

        private void HandleNotification(string sourceFileUrl, NotificationType type)
        {
            switch (type)
            {
                case NotificationType.PluginStartup:
                    Log("startup");
                    var item = _mb.MB_AddMenuItem("mnuView/Starry Karaoke", "Starry Karaoke: open the karaoke window",
                                                  (s, e) => OnUi(Toggle));
                    Log("menu item: " + (item?.Text ?? "null"));
                    _mb.MB_AddMenuItem("mnuTools/Starry Karaoke: record song video", "Starry Karaoke: record a karaoke video of the playing song",
                                       (s, e) => OnUi(() => Safe.Run(RecordVideo, LogException)));
                    _mb.MB_AddMenuItem("mnuTools/Starry Karaoke: make word-timed lyrics with LyricLoom",
                                       "Starry Karaoke: ask LyricLoom to write word-timed lyrics for the playing song",
                                       (s, e) => OnUi(() => Safe.Run(CreateLyricsWithLyricLoom, LogException)));
                    // These are separate MusicBee menu commands so MusicBee's own hotkey editor can
                    // bind them, even while the karaoke window does not have the keyboard focus.
                    AddCommand("Starry Karaoke: toggle window", "Show, restore or hide the karaoke window",
                               Toggle);
                    AddCommand("Starry Karaoke: toggle fullscreen", "Toggle fullscreen on the chosen monitor",
                               ToggleFullscreen);
                    AddCommand("Starry Karaoke: lyrics delay +100 ms", "Delay this song's lyrics by 100 ms",
                               () => AdjustSongOffset(100));
                    AddCommand("Starry Karaoke: lyrics delay -100 ms", "Show this song's lyrics 100 ms earlier",
                               () => AdjustSongOffset(-100));
                    AddCommand("Starry Karaoke: reset this song's lyrics delay", "Reset this song's extra lyric delay",
                               ResetSongOffset);
                    AddCommand("Starry Karaoke: loop current line", "Loop the line that is playing",
                               LoopCurrentLine);
                    if (_settings.WindowOpen) OnUi(Open);
                    else OnUi(() => RefreshCurrentSongLocal(CurrentSongUrl()));
                    break;
                case NotificationType.TrackChanged:
                    HandleTrackChanged(sourceFileUrl);
                    break;
                case NotificationType.NowPlayingLyricsReady:
                    HandleLyricsReady(sourceFileUrl);
                    break;
                case NotificationType.PlayStateChanged:
                    HandlePlayStateChanged();
                    break;
            }
        }

        private void HandleTrackChanged(string sourceFileUrl)
        {
            var url = sourceFileUrl ?? "";
            var changed = !string.Equals(url, _currentSongUrl, StringComparison.OrdinalIgnoreCase);
            var previous = _currentSongUrl;
            _currentSongUrl = url;
            if (changed)
            {
                _currentSongIsLocal = false;
                _dismissedSongUrl = null;
                _autoAttemptedForSong = false;
                if (!string.IsNullOrEmpty(previous)) _lyricLoomRequests.Forget(previous);
                DisposeSidecarWatcher();
            }
            Interlocked.Increment(ref _autoOpenGeneration);
            if (_window != null) LoadSong();
            else RefreshCurrentSongLocal(url);
            OnUi(() =>
            {
                if (changed) _window?.ClearLyricLoomPending();
            });
            QueueAutoOpenAttempt();
        }

        /// <summary>FR-C-06: checks the current song's file on the pool, then applies the cached flag
        /// and the sidecar watcher on the UI thread. The UI thread never calls File.Exists on a song
        /// path.</summary>
        private void RefreshCurrentSongLocal(string url)
        {
            if (string.IsNullOrEmpty(url)) return;
            ThreadPool.QueueUserWorkItem(_ =>
            {
                var local = false;
                try { local = File.Exists(url); } catch (Exception) { }
                OnUi(() =>
                {
                    if (_shuttingDown) return;
                    if (string.IsNullOrEmpty(_currentSongUrl)) _currentSongUrl = url;
                    if (!string.Equals(url, _currentSongUrl, StringComparison.OrdinalIgnoreCase)) return;
                    _currentSongIsLocal = local;
                    _window?.SetLyricLoomEnabled(local);
                    UpdateSidecarWatcher(url);
                });
            });
        }

        private void HandleLyricsReady(string sourceFileUrl)
        {
            Log("lyrics ready");
            if (!string.IsNullOrEmpty(sourceFileUrl) &&
                !string.Equals(sourceFileUrl, _currentSongUrl, StringComparison.OrdinalIgnoreCase))
            {
                // A late notification for the previous song must not reload the window with its lyrics.
                Log("ignored lyrics-ready for a previous song");
                return;
            }
            if (_window != null) LoadSong();
            if (_settings.AutoOpenLyrics != AutoOpenLyrics.Off)
                ScheduleAutoOpen(_currentSongUrl, 0);
        }

        private void HandlePlayStateChanged()
        {
            if (_settings.PartyMode) QueuePartyAction();
            QueueAutoOpenAttempt();
        }

        /// <summary>Party mode reads the real player state right before it acts. A stale poll value
        /// must not open a fullscreen window after playback stopped, or leave one up when it did.</summary>
        private void QueuePartyAction()
        {
            ThreadPool.QueueUserWorkItem(_ =>
            {
                PlayState state;
                try { state = _mb.Player_GetPlayState(); }
                catch (Exception) { return; }
                OnUi(() => Safe.Run(() =>
                {
                    if (_settings == null || _shuttingDown || !_settings.PartyMode) return;
                    if (state == PlayState.Playing) PartyStart();
                    else PartyStop();
                }, LogException));
            });
        }

        /// <summary>Only the first Playing notification for a song may auto-open; a pause/resume must
        /// not reopen a window the user closed.</summary>
        private void QueueAutoOpenAttempt()
        {
            var url = _currentSongUrl;
            if (string.IsNullOrEmpty(url) || _settings.AutoOpenLyrics == AutoOpenLyrics.Off || _shuttingDown) return;
            ThreadPool.QueueUserWorkItem(_ =>
            {
                if (!IsPlaying()) return;
                OnUi(() =>
                {
                    if (!string.Equals(url, _currentSongUrl, StringComparison.OrdinalIgnoreCase)) return;
                    if (_autoAttemptedForSong || _shuttingDown) return;
                    _autoAttemptedForSong = true;
                    ScheduleAutoOpen(url, 0);
                });
            });
        }

        /// <summary>Checks the lyrics the window would actually show and opens/shows/hides/closes the
        /// window. MusicBee may fetch lyrics shortly after a track change, so an unsupported song is
        /// looked at again after 1.5 s and after 4 s.</summary>
        private void ScheduleAutoOpen(string url, int attempt)
        {
            if (_settings == null || _shuttingDown) return;
            if (string.IsNullOrEmpty(url) || !string.Equals(url, _currentSongUrl, StringComparison.OrdinalIgnoreCase)) return;
            if (string.Equals(url, _dismissedSongUrl, StringComparison.OrdinalIgnoreCase)) return;
            if (_settings.AutoOpenLyrics == AutoOpenLyrics.Off) return;

            var generation = Interlocked.Increment(ref _autoOpenGeneration);
            ThreadPool.QueueUserWorkItem(_ =>
            {
                if (generation != Volatile.Read(ref _autoOpenGeneration)) return;
                if (!string.Equals(url, _currentSongUrl, StringComparison.OrdinalIgnoreCase)) return;
                if (!IsPlaying()) return;

                var lyricsSource = OnUiGet(() => ReadLyricsSource(), null);
                if (lyricsSource == null) return;
                var kind = AutoOpenRule.Classify(PickLyrics(lyricsSource, false));
                OnUi(() =>
                {
                    if (generation != Volatile.Read(ref _autoOpenGeneration)) return;
                    if (!string.Equals(url, _currentSongUrl, StringComparison.OrdinalIgnoreCase)) return;
                    if (string.Equals(url, _dismissedSongUrl, StringComparison.OrdinalIgnoreCase)) return;
                    if (_settings.AutoOpenLyrics == AutoOpenLyrics.Off || _shuttingDown) return;

                    if (!AutoOpenRule.IsSupported(_settings.AutoOpenLyrics, kind))
                    {
                        // The song has no supported lyrics yet: give MusicBee/LyricLoom a chance to
                        // deliver them before applying Keep/Hide/Close. The timer is URL-guarded.
                        if (attempt < 2)
                        {
                            ScheduleRetry(url, attempt + 1, attempt == 0 ? 1500 : 2500);
                            return;
                        }
                        var unsupported = AutoOpenRule.Decide(_settings.AutoOpenLyrics, kind, true,
                            _window != null, _window != null && _window.IsVisible, false, _settings.OnUnsupportedSong);
                        ApplyUnsupportedSong(url, kind, unsupported);
                        return;
                    }

                    var action = AutoOpenRule.Decide(_settings.AutoOpenLyrics, kind, true, _window != null,
                        _window != null && _window.IsVisible, false, _settings.OnUnsupportedSong);
                    if (action == AutoOpenAction.Open) OpenAuto();
                    else if (action == AutoOpenAction.Show) ShowAuto();
                });
            });
        }

        private void ScheduleRetry(string url, int attempt, int delay)
        {
            System.Threading.Timer timer = null;
            timer = new System.Threading.Timer(_ =>
            {
                lock (_autoOpenTimers) _autoOpenTimers.Remove(timer);
                try { timer.Dispose(); } catch (Exception) { }
                ScheduleAutoOpen(url, attempt);
            }, null, delay, Timeout.Infinite);
            lock (_autoOpenTimers) _autoOpenTimers.Add(timer);
        }

        private void DisposeAutoOpenTimers()
        {
            System.Threading.Timer[] timers;
            lock (_autoOpenTimers)
            {
                timers = _autoOpenTimers.ToArray();
                _autoOpenTimers.Clear();
            }
            foreach (var timer in timers)
                try { timer.Dispose(); } catch (Exception) { }
        }

        private void ApplyUnsupportedSong(string url, LyricsKind kind, AutoOpenAction action)
        {
            var w = _window;
            if (w == null) return;
            if (!string.Equals(url, _currentSongUrl, StringComparison.OrdinalIgnoreCase)) return;
            switch (action)
            {
                case AutoOpenAction.Hide:
                    StopPolling();
                    w.Hide();
                    break;
                case AutoOpenAction.Close:
                    w.CloseForTrackChange();
                    break;
                default:
                    _lines = new List<KaraokeLine>();
                    w.SetSong(_lines, _lastHeader, _lastDuration, url, _songOffsets.Get(url));
                    w.SetNextSong("");
                    w.SetWordTimingAvailable(false, !string.IsNullOrEmpty(url));
                    w.ShowMessage(kind == LyricsKind.LineTimed
                        ? "No word-timed lyrics for this song"
                        : "No synced lyrics for this song");
                    break;
            }
        }

        /// <summary>Party mode: bring the karaoke forward and fill the screen when playback starts.
        /// The caller has already read the live play state on the worker.</summary>
        private void PartyStart()
        {
            if (!_settings.PartyMode) return;
            if (!string.IsNullOrEmpty(_dismissedSongUrl) &&
                string.Equals(_dismissedSongUrl, _currentSongUrl, StringComparison.OrdinalIgnoreCase)) return;
            if (_window == null) OpenWindow(autoOpen: true);
            else
            {
                if (_window.WindowState == System.Windows.WindowState.Minimized)
                    _window.WindowState = System.Windows.WindowState.Normal;
                if (!_window.IsVisible)
                {
                    _window.ShowActivated = true;
                    _window.Show();
                }
            }
            _window?.Activate();
            _window?.SetFullscreen(true);
        }

        /// <summary>Applies Settings.PartyModeOnStop when the player is no longer playing. The
        /// window is not treated as a user dismissal when party mode closes or hides it.</summary>
        private void PartyStop()
        {
            var w = _window;
            if (w == null) return;
            switch (_settings.PartyModeOnStop)
            {
                case PartyModeOnStop.LeaveFullscreen:
                    w.SetFullscreen(false);
                    break;
                case PartyModeOnStop.Hide:
                    w.SetFullscreen(false);
                    w.Hide();
                    StopPolling();
                    break;
                case PartyModeOnStop.Close:
                    w.CloseForTrackChange();
                    break;
            }
        }

        // ---------------------------------------------------------------- windows

        private void Toggle()
        {
            if (_window == null || !_window.IsVisible ||
                _window.WindowState == System.Windows.WindowState.Minimized)
            {
                Open();   // View > Starry Karaoke also restores a minimised or hidden window
                return;
            }
            _window.Close();
        }

        private void Open()
        {
            _dismissedSongUrl = null;   // opening it by hand arms auto-open again for this song
            OpenWindow(autoOpen: false);
        }

        private void OpenAuto() => OpenWindow(autoOpen: true);

        private void ShowAuto()
        {
            var w = _window;
            if (w == null) { OpenWindow(autoOpen: true); return; }
            if (w.IsVisible) return;
            w.ShowActivated = _settings.AutoOpenFocus;
            w.Show();
            if (_settings.AutoOpenFocus) w.Activate();
        }

        private void OpenWindow(bool autoOpen, bool preferSidecar = false)
        {
            InstallDispatcherSafetyNet();
            var activate = !autoOpen || _settings.AutoOpenFocus;
            if (_window != null)
            {
                _window.ShowActivated = activate;
                if (_window.WindowState == System.Windows.WindowState.Minimized)
                    _window.WindowState = System.Windows.WindowState.Normal;
                if (!_window.IsVisible) _window.Show();
                if (activate) _window.Activate();
                return;
            }

            var controls = new PlayerControls
            {
                PlayPause = () => OnPlayer(() => _mb.Player_PlayPause()),
                Previous = () => OnPlayer(() => _mb.Player_PlayPreviousTrack()),
                Next = () => OnPlayer(() => _mb.Player_PlayNextTrack()),
                Seek = ms => OnPlayer(() => _mb.Player_SetPosition((int)Math.Max(0, ms))),
                SetVolume = v => OnPlayer(() => _mb.Player_SetVolume(Math.Max(0, Math.Min(1, v)))),
                SetMute = m => OnPlayer(() => _mb.Player_SetMute(m))
            };
            var w = new KaraokeWindow(_settings,
                                      () => PolledSampleSnapshot(),
                                      controls, showActivated: activate, log: LogException);
            ElementHost.EnableModelessKeyboardInterop(w);
            w.SettingsRequested += (s, e) => Safe.Run(OpenSettings, LogException);
            w.RecordRequested += (s, e) => Safe.Run(RecordVideo, LogException);
            w.SkipIntroRequested += (s, e) => Safe.Run(() => SkipIntro(force: true), LogException);
            w.LyricLoomRequested += (s, e) => Safe.Run(CreateLyricsWithLyricLoom, LogException);
            w.DiagnosticsRequested += (s, e) => Safe.Run(ShowDiagnostics, LogException);
            w.SongOffsetChanged += ms => Safe.Run(() =>
            {
                var url = CurrentSongUrl();
                if (string.IsNullOrEmpty(url)) return;
                _songOffsets.Set(url, ms);
                if (!string.IsNullOrEmpty(_songOffsets.LastError)) Log(_songOffsets.LastError);
            }, LogException);
            w.FullscreenMonitorChosen += device => Safe.Run(() =>
            {
                _settings.FullscreenMonitor = device ?? "";
                SaveSettings();
            }, LogException);
            w.FullscreenTopmostChanged += topmost => Safe.Run(() =>
            {
                _settings.FullscreenTopmost = topmost;
                SaveSettings();
            }, LogException);
            w.PollingNeeded += allowed =>
            {
                if (allowed) StartPolling();
                else StopPolling();
            };
            w.JapaneseModeChosen += mode => Safe.Run(() =>
            {
                _settings.Japanese = mode;
                SaveSettings();
                w.ApplySettings(_settings);
                w.RefreshMenu();
                LoadSong();
            }, LogException);
            w.UserClosed += (s, e) =>
            {
                // Do not auto-open this song again, but a new song may.
                if (!_shuttingDown) _dismissedSongUrl = _currentSongUrl;
            };
            w.Closing += (s, e) => Safe.Run(() => w.StoreBounds(_settings), LogException);
            w.Closed += (s, e) =>
            {
                if (!ReferenceEquals(_window, w)) return;
                _window = null;
                Interlocked.Increment(ref _songGeneration);
                StopPolling();
                UpdateSidecarWatcher(_currentSongUrl);
                _settings.WindowOpen = false;
                SaveSettings();
            };
            // WindowOpen is only saved as true by a clean MusicBee shutdown (Close), so a crash with the
            // window open does not make it open again, and crash again, at every start.
            _window = w;
            StartPolling();
            w.SetLyricLoomEnabled(_currentSongIsLocal);
            w.Show();
            if (activate) w.Activate();
            LoadSong(preferSidecar);
        }

        // ---------------------------------------------------------------- player, off the UI thread

        // THREADING CONTRACT (FR-C-05): every Player_* call in this file runs on a pool thread, never
        // on MusicBee's UI thread. Evidence: while the player seeks it holds the position and waits
        // for the thread that asked, so a position read from the UI thread deadlocks MusicBee (the
        // regression that made "go back in a song" hang). This is deliberate and must not be
        // "corrected" by moving the calls to OnUi: the getters are polled from a background timer,
        // the commands are serialised on _playerLock below, and every NowPlaying_*/NowPlayingList_*
        // call (the part of the API without a documented thread contract) is marshalled to the UI
        // thread through OnUiGet/OnUi instead.
        private System.Threading.Timer _pollTimer;
        // The position, play state and sample timestamp must reach the window together: a torn
        // read (new timestamp with the previous position) would make the clock extrapolate a
        // whole poll interval. One immutable object swapped atomically is cheaper than a lock
        // around a player call, which must never block the UI thread.
        private sealed class PollSample
        {
            public double PositionMs, SampledAtMs;
            public bool Playing;
            public float Volume;
            public bool Mute;
        }
        private PollSample _polledSample;
        private bool _pollFailureLogged;

        private (double PositionMs, bool Playing, float Volume, bool Mute, double SampledAtMs) PolledSampleSnapshot()
        {
            var sample = Interlocked.CompareExchange(ref _polledSample, null, null);
            return sample == null
                ? (0.0, false, 1f, false, 0.0)
                : (sample.PositionMs, sample.Playing, sample.Volume, sample.Mute, sample.SampledAtMs);
        }

        private void StartPolling()
        {
            if (_pollTimer != null) return;
            _pollTimer = new System.Threading.Timer(_ =>
            {
                if (_window == null || _shuttingDown) return;
                try
                {
                    // Stamp the sample when the player is asked, not when a frame later reads it:
                    // a 100 ms poll can be up to 100 ms old, and that latency is exactly what made
                    // the old clock treat a stale reading as "now".
                    var sample = new PollSample { SampledAtMs = PlaybackClock.TimestampMs() };
                    sample.PositionMs = _mb.Player_GetPosition();
                    sample.Playing = _mb.Player_GetPlayState() == PlayState.Playing;
                    sample.Volume = _mb.Player_GetVolume();
                    sample.Mute = _mb.Player_GetMute();
                    Interlocked.Exchange(ref _polledSample, sample);
                }
                catch (Exception e)
                {
                    // A failed poll is harmless: the window keeps the previous sample and the next
                    // tick tries again. Log the first failure once so a broken API cannot flood the
                    // log at 10 lines per second (FR-C-05).
                    if (_pollFailureLogged) return;
                    _pollFailureLogged = true;
                    Log("player poll failed; further failures are ignored: " + e);
                }
            }, null, 0, 100);
        }

        private void StopPolling()
        {
            var timer = Interlocked.Exchange(ref _pollTimer, null);
            try { timer?.Dispose(); } catch (Exception) { }
        }

        private bool IsPlaying()
        {
            try { return _mb.Player_GetPlayState() == PlayState.Playing; }
            catch (Exception) { return false; }
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
            if (_settingsWindow != null)
            {
                if (_settingsWindow.WindowState == System.Windows.WindowState.Minimized)
                    _settingsWindow.WindowState = System.Windows.WindowState.Normal;
                if (!_settingsWindow.IsVisible) _settingsWindow.Show();
                _settingsWindow.Activate();
                return;
            }
            var before = _settings.Japanese;
            var dlg = new SettingsWindow(_settings, preview => Safe.Run(() => _window?.ApplySettings(preview), LogException),
                                         LogException, BuildDiagnosticsText, _window?.MonitorHz ?? 0);
            // FR-C-04: own the dialog and keep it above a topmost fullscreen karaoke window.
            if (_window != null && _window.IsVisible) dlg.Owner = _window;
            dlg.Topmost = DialogPlacement.ShouldBeTopmost(_window);
            ElementHost.EnableModelessKeyboardInterop(dlg);
            dlg.Closed += (s, e) => Safe.Run(() =>
            {
                _settingsWindow = null;
                if (dlg.Result == null) return;
                _window?.StoreBounds(dlg.Result);
                dlg.Result.WindowOpen = _window != null;
                _settings = dlg.Result;
                SaveSettings();
                _window?.ApplySettings(_settings);
                _window?.RefreshMenu();
                RefreshCurrentSongLocal(_currentSongUrl);
                if (_settings.Japanese != before) LoadSong();
                // Editing colours or turning party mode on must not bring the karaoke window in
                // front of whatever the user is doing. Party mode starts on the next genuine
                // play-state change instead.
            }, LogException);
            _settingsWindow = dlg;
            dlg.Show();
        }

        // ---------------------------------------------------------------- LyricLoom

        /// <summary>Asks LyricLoom to make word-timed lyrics for the playing file. The command goes to
        /// the already running LyricLoom (or starts it) without a shell and without focus stealing.
        /// The plugin itself never contacts the network.</summary>
        private void CreateLyricsWithLyricLoom()
        {
            if (_lyricLoomStarting) return;
            _lyricLoomStarting = true;
            var audio = "";
            try
            {
                audio = _mb.NowPlaying_GetFileUrl();
                if (string.IsNullOrEmpty(audio) || !File.Exists(audio))
                {
                    Message("No local song is playing.");
                    return;
                }
                if (!_lyricLoomRequests.TryBegin(audio, DateTime.UtcNow))
                {
                    // The song is already with LyricLoom: keep the waiting status, do not queue it twice.
                    _window?.ShowLyricLoomPending();
                    Log("LyricLoom: already asked for " + Path.GetFileName(audio));
                    return;
                }
                var exe = LyricLoomLocator.Default.Find(_settings.LyricLoomPath);
                if (string.IsNullOrEmpty(exe))
                {
                    _lyricLoomRequests.Forget(audio);
                    var answer = Ask(
                        "LyricLoom was not found.\n\nDownload LyricLoom from the release page?\n" + LyricLoomLauncher.DownloadUrl);
                    if (answer == System.Windows.MessageBoxResult.Yes)
                        try { System.Diagnostics.Process.Start(LyricLoomLauncher.DownloadUrl); }
                        catch (Exception e) { Log("could not open the LyricLoom download page: " + e.Message); }
                    return;
                }
                LyricLoomLauncher.Start(exe, audio);
                Log("LyricLoom: launched for " + Path.GetFileName(audio));
                _window?.ShowLyricLoomPending();
            }
            catch (Exception e)
            {
                _lyricLoomRequests.Forget(audio);
                Log("could not start LyricLoom: " + e);
                Message("Could not start LyricLoom. See mb_StarryKaraoke.log for details.");
            }
            finally
            {
                _lyricLoomStarting = false;
            }
        }

        // ---------------------------------------------------------------- video

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
                    var song = OnUiGet(() => ReadSongSnapshot(), null);
                    if (song == null || string.IsNullOrEmpty(song.Url) || !File.Exists(song.Url))
                    {
                        OnUi(() => Message("No local song is playing."));
                        return;
                    }
                    var lrc = PickLyrics(song, false);
                    if (string.IsNullOrEmpty(lrc))
                    {
                        OnUi(() => Message("This song has no synced lyrics."));
                        return;
                    }
                    var header = string.IsNullOrEmpty(song.Artist) ? song.Title : song.Title + "   —   " + song.Artist;
                    if (japanese != JapaneseMode.JapaneseOnly && Lrc.IsJapanese(header))
                    {
                        var r = Lrc.Tidy(Romanize(header));
                        if (r.Length > 0) header = r;
                    }
                    OnUi(() => RecordVideo(exe, dll, song.Url, lrc, song.Duration, song.Title, song.Artist, header));
                }
                catch (Exception e) { Log("record failed: " + e); }
            });
        }

        private void RecordVideo(string exe, string dll, string audio, string lrc, double duration, string title, string artist, string header)
        {
            // Resolve ffmpeg before asking for an output file: a user without ffmpeg must learn that
            // now, not after typing a filename into a recorder that then shows a modal error.
            var ffmpeg = ResolveFfmpeg();
            if (string.IsNullOrEmpty(ffmpeg))
            {
                const string text = "ffmpeg was not found, so a video cannot be recorded.\n\n" +
                                    "Install it with \"winget install Gyan.FFmpeg\", or put ffmpeg.exe next to LyricLoom / on PATH, " +
                                    "or choose it in Settings > Recorded video.\n\nOpen Settings now?";
                if (Ask(text) == System.Windows.MessageBoxResult.Yes) OpenSettings();
                return;
            }
            if (!string.Equals(_settings.FfmpegPath, ffmpeg, StringComparison.OrdinalIgnoreCase))
            {
                _settings.FfmpegPath = ffmpeg;
                SaveSettings();
            }

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
                // FR-C-04: the karaoke window may be fullscreen and topmost. Own the native dialog
                // and lower Topmost while it is up so it cannot appear behind the karaoke window.
                var owner = DialogPlacement.Win32Owner(_window);
                var result = DialogPlacement.AboveOwner(_window,
                    () => owner != null ? dlg.ShowDialog(owner) : dlg.ShowDialog());
                if (result != DialogResult.OK) return;
                target = dlg.FileName;
            }

            // Never let the recorder start only to be told (or worse, to overwrite) that its target is
            // the song it reads. The recorder checks this again with symlinks resolved.
            if (RecordingPaths.SamePath(target, audio))
            {
                Log("record refused: the output is the song's own audio file");
                Message("The video cannot be saved over the song's audio file. Choose another file name.");
                return;
            }

            // The recorder gets its own copies: the lyrics and settings as they are now. They live in
            // a per-run rec-* folder, so a killed recorder leaves them where the startup sweep finds
            // them (RV1-05).
            string work;
            try { work = RecordingTemp.CreateRunFolder(); }
            catch (Exception e)
            {
                Log("could not create the recorder's temp folder: " + e);
                Message("Could not prepare the temporary files for the recorder. See mb_StarryKaraoke.log for details.");
                return;
            }

            var started = false;
            try
            {
                var lrcPath = Path.Combine(work, RecordingTemp.LyricsFileName);
                File.WriteAllText(lrcPath, lrc);
                var settingsPath = Path.Combine(work, RecordingTemp.SettingsFileName);
                _settings.Save(work, RecordingTemp.SettingsFileName);
                var dict = new[] { Path.Combine(dll, "RomajiLyrics", "IpaDic"), Path.Combine(StorageFolder, "Plugins", "RomajiLyrics", "IpaDic"), Path.Combine(dll, "IpaDic") };
                var dictDir = Array.Find(dict, d => File.Exists(Path.Combine(d, "sys.dic"))) ?? "";

                string Q(string s) => "\"" + s.Replace("\"", "'") + "\"";
                var args = $"--lrc {Q(lrcPath)} --audio {Q(audio)} --out {Q(target)} --settings {Q(settingsPath)} " +
                           $"--title {Q(header)} --duration {duration.ToString(System.Globalization.CultureInfo.InvariantCulture)} " +
                           $"--dict {Q(dictDir)} --ffmpeg {Q(ffmpeg)}";
                Log("record: " + target);
                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(exe, args) { UseShellExecute = false, WorkingDirectory = dll });
                started = true;
            }
            catch (Exception e)
            {
                Log("could not start the recorder: " + e);
                Message("Could not start StarryKaraoke.Recorder.exe. See mb_StarryKaraoke.log for details.");
            }
            finally
            {
                // On every path where the recorder did not start, its private copies must not stay.
                if (!started) RecordingTemp.DeleteRunFolder(work);
            }
        }

        private static string SafeName(string s)
        {
            foreach (var c in Path.GetInvalidFileNameChars()) s = s.Replace(c, '_');
            return s.Trim();
        }

        /// <summary>FR-C-04: every message box is owned by the karaoke window (when it is visible)
        /// and shown above it when the window is topmost.</summary>
        private void Message(string text)
        {
            var owner = _window != null && _window.IsVisible ? _window : null;
            if (owner == null)
            {
                System.Windows.MessageBox.Show(text, "Starry Karaoke",
                    System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Information);
                return;
            }
            DialogPlacement.AboveOwner(owner, () => System.Windows.MessageBox.Show(owner, text, "Starry Karaoke",
                System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Information));
        }

        private System.Windows.MessageBoxResult Ask(string text)
        {
            var owner = _window != null && _window.IsVisible ? _window : null;
            if (owner == null)
            {
                return System.Windows.MessageBox.Show(text, "Starry Karaoke",
                    System.Windows.MessageBoxButton.YesNo, System.Windows.MessageBoxImage.Information);
            }
            return DialogPlacement.AboveOwner(owner, () => System.Windows.MessageBox.Show(owner, text, "Starry Karaoke",
                System.Windows.MessageBoxButton.YesNo, System.Windows.MessageBoxImage.Information));
        }

        // ---------------------------------------------------------------- menu commands

        private void AddCommand(string text, string description, Action action) =>
            _mb.MB_AddMenuItem("mnuTools/" + text, description,
                               (s, e) => OnUi(() => Safe.Run(action, LogException)));

        private void ToggleFullscreen()
        {
            if (_window == null || !_window.IsVisible ||
                _window.WindowState == System.Windows.WindowState.Minimized)
            {
                OpenWindow(autoOpen: false);
                _window?.SetFullscreen(true);
                return;
            }
            _window.SetFullscreen(!_window.IsFullscreen);
        }

        /// <summary>Changes the playing song's own delay. Works with no window open too: the store
        /// remembers it for when the window next loads the song.</summary>
        private void AdjustSongOffset(int delta)
        {
            var url = CurrentSongUrl();
            if (string.IsNullOrEmpty(url)) return;
            if (_window != null && string.Equals(url, _currentSongUrl, StringComparison.OrdinalIgnoreCase))
            {
                _window.NudgeOffset(delta);
                return;
            }
            var value = Math.Max(-10000, Math.Min(10000, _songOffsets.Get(url) + delta));
            _songOffsets.Set(url, value);
            if (!string.IsNullOrEmpty(_songOffsets.LastError)) Log(_songOffsets.LastError);
        }

        private void ResetSongOffset()
        {
            var url = CurrentSongUrl();
            if (string.IsNullOrEmpty(url)) return;
            if (_window != null && string.Equals(url, _currentSongUrl, StringComparison.OrdinalIgnoreCase))
            {
                _window.ResetOffset();
                return;
            }
            _songOffsets.Reset(url);
        }

        private void LoopCurrentLine()
        {
            if (_window == null) OpenWindow(autoOpen: false);
            _window?.SetLoop(false);
        }

        private string CurrentSongUrl()
        {
            if (!string.IsNullOrEmpty(_currentSongUrl)) return _currentSongUrl;
            try { return _mb.NowPlaying_GetFileUrl() ?? ""; }
            catch (Exception) { return ""; }
        }

        // ---------------------------------------------------------------- diagnostics

        private string ResolveFfmpeg()
        {
            try { return FfmpegLocator.Resolve(_settings?.FfmpegPath, _settings?.LyricLoomPath); }
            catch (Exception e)
            {
                Log("could not look for ffmpeg: " + e.Message);
                return null;
            }
        }

        private string MusicBeeVersionText()
        {
            try
            {
                var file = System.Diagnostics.Process.GetCurrentProcess().MainModule?.FileName;
                var version = string.IsNullOrEmpty(file)
                    ? ""
                    : System.Diagnostics.FileVersionInfo.GetVersionInfo(file).FileVersion;
                return (string.IsNullOrEmpty(version) ? "unknown" : version) + " (API " + _mb.ApiRevision + ")";
            }
            catch (Exception)
            {
                return "unknown (API " + _mb.ApiRevision + ")";
            }
        }

        /// <summary>FR-C-06: resolves ffmpeg and starts `ffmpeg -version`, so callers run it on the
        /// thread pool; opening the Settings window or Diagnostics must not wait for it on
        /// MusicBee's UI thread.</summary>
        private string BuildDiagnosticsText()
        {
            var pluginVersion = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "";
            var dictionary = RomajiCore.Romanizer.DictionaryDirectory ?? "";
            var dictionaryFound = !string.IsNullOrEmpty(dictionary) &&
                                  File.Exists(Path.Combine(dictionary, "sys.dic"));
            // Do not copy Romanizer.LastError into the report: an exception stack trace can contain
            // paths outside the ones diagnostics is allowed to show.
            var dictionaryError = dictionaryFound
                ? (string.IsNullOrEmpty(RomajiCore.Romanizer.LastError)
                    ? null
                    : "the dictionary could not be loaded; see the log")
                : "sys.dic was not found";
            var ffmpeg = ResolveFfmpeg() ?? "";
            var ffmpegVersion = ffmpeg.Length > 0 ? FfmpegInfo.VersionLine(ffmpeg) : "";
            string lyricLoom = "";
            try { lyricLoom = LyricLoomLocator.Default.Find(_settings?.LyricLoomPath) ?? ""; }
            catch (Exception) { }
            return DiagnosticsReport.Build(pluginVersion, MusicBeeVersionText(), dictionary, dictionaryError,
                                           ffmpeg, ffmpegVersion, lyricLoom, _logPath);
        }

        private void ShowDiagnostics()
        {
            var window = new DiagnosticsWindow("Checking the versions...", _logPath);
            if (_window != null && _window.IsVisible) window.Owner = _window;
            window.Topmost = DialogPlacement.ShouldBeTopmost(_window);
            ElementHost.EnableModelessKeyboardInterop(window);
            window.Show();
            ThreadPool.QueueUserWorkItem(_ =>
            {
                string text;
                try { text = BuildDiagnosticsText(); }
                catch (Exception e)
                {
                    Log("building diagnostics failed: " + e);
                    text = "Diagnostics could not be built. See mb_StarryKaraoke.log for details.";
                }
                try
                {
                    var dispatcher = window.Dispatcher;
                    if (!dispatcher.HasShutdownStarted)
                        dispatcher.BeginInvoke((Action)(() => window.SetText(text)));
                }
                catch (Exception) { }
            });
        }

        // ---------------------------------------------------------------- lyrics

        /// <summary>Reads the playing song's ID3/NowPlaying fields on MusicBee's UI thread. It does no
        /// file I/O: the sidecars are read afterwards on the pool (FR-C-06), so a sleeping network
        /// share cannot freeze MusicBee.</summary>
        private SongSnapshot ReadSongSnapshot()
        {
            var song = new SongSnapshot();
            try { song.Url = _mb.NowPlaying_GetFileUrl() ?? ""; } catch (Exception e) { Log("reading the playing file failed: " + e.Message); }
            try { song.MbLyrics = PickMusicBeeLyrics() ?? ""; } catch (Exception e) { Log("reading lyrics failed: " + e.Message); }
            try { song.Title = _mb.NowPlaying_GetFileTag(MetaDataType.TrackTitle) ?? ""; } catch (Exception) { }
            try { song.Artist = _mb.NowPlaying_GetFileTag(MetaDataType.Artist) ?? ""; } catch (Exception) { }
            try { song.Duration = _mb.NowPlaying_GetDuration(); } catch (Exception) { }
            try { song.Next = NextSongText(); } catch (Exception) { }
            return song;
        }

        /// <summary>The auto-open check only needs the URL and MusicBee's lyrics; no tags or file
        /// I/O. Called on the UI thread through OnUiGet.</summary>
        private SongSnapshot ReadLyricsSource()
        {
            var song = new SongSnapshot();
            try { song.Url = _mb.NowPlaying_GetFileUrl() ?? ""; } catch (Exception e) { Log("reading the playing file failed: " + e.Message); }
            try { song.MbLyrics = PickMusicBeeLyrics() ?? ""; } catch (Exception e) { Log("reading lyrics failed: " + e.Message); }
            return song;
        }

        private string PickMusicBeeLyrics()
        {
            string mbLyrics = null;
            try { mbLyrics = _mb.NowPlaying_GetLyrics(); } catch (Exception) { }
            if (string.IsNullOrEmpty(mbLyrics) || !LyricsSelector.HasSyncedLyrics(mbLyrics))
                try { mbLyrics = _mb.NowPlaying_GetDownloadedLyrics(); } catch (Exception) { }
            return mbLyrics;
        }

        /// <summary>Reads and times the playing song's lyrics off the UI thread (romaji takes a moment),
        /// then hands them to the window. A newer song makes an older load drop its result.</summary>
        private void LoadSong(bool preferSidecar = false)
        {
            var gen = Interlocked.Increment(ref _songGeneration);
            var mode = _settings.Japanese;
            ThreadPool.QueueUserWorkItem(_ =>
            {
                var header = "";
                var duration = 0.0;
                try
                {
                    var song = OnUiGet(() => ReadSongSnapshot(), null);
                    if (song == null) throw new InvalidOperationException("Could not read the playing song.");
                    duration = song.Duration;
                    var lrc = PickLyrics(song, preferSidecar);
                    var raw = Lrc.Parse(lrc);
                    var lines = Timeline.Build(raw, duration, mode, Romanize);
                    header = string.IsNullOrEmpty(song.Artist) ? song.Title : song.Title + "   —   " + song.Artist;
                    if (mode != JapaneseMode.JapaneseOnly && Lrc.IsJapanese(header))
                        header = Lrc.Tidy(Romanize(header)) is var r && r.Length > 0 ? r : header;
                    var hasWordTiming = AutoOpenRule.Classify(lrc) == LyricsKind.WordTimed;
                    var canCreateLyrics = false;
                    try { canCreateLyrics = !string.IsNullOrEmpty(song.Url) && File.Exists(song.Url); } catch (Exception) { }
                    var songOffset = _songOffsets.Get(song.Url);
                    OnUi(() =>
                    {
                        if (gen != _songGeneration) return;
                        _currentSongIsLocal = canCreateLyrics;
                        _lines = lines;
                        _lastHeader = header;
                        _lastDuration = duration;
                        _window?.SetSong(lines, header, duration, song.Url, songOffset);
                        _window?.SetNextSong(song.Next);
                        _window?.SetWordTimingAvailable(hasWordTiming, canCreateLyrics);
                        _window?.SetLyricLoomEnabled(canCreateLyrics);
                        UpdateSidecarWatcher(song.Url);
                        if (_settings.AutoSkipIntro) SkipIntro(force: false);
                    });
                }
                catch (Exception e)
                {
                    var url = _currentSongUrl;
                    var local = false;
                    try { local = !string.IsNullOrEmpty(url) && File.Exists(url); } catch (Exception) { }
                    Log("loading lyrics failed: " + e);
                    // R4-19: never leave the previous song's lyrics playing over the new one.
                    OnUi(() =>
                    {
                        if (gen != _songGeneration) return;
                        _currentSongIsLocal = local;
                        _lines = new List<KaraokeLine>();
                        _lastHeader = header;
                        _lastDuration = duration;
                        _window?.SetSong(_lines, header, duration, _currentSongUrl, _songOffsets.Get(_currentSongUrl));
                        _window?.SetNextSong("");
                        _window?.SetWordTimingAvailable(false, local);
                        _window?.ShowMessage("Could not read the lyrics for this song");
                        UpdateSidecarWatcher(_currentSongUrl);
                    });
                }
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
            var offset = _settings.LyricsOffsetMs + _songOffsets.Get(_currentSongUrl);
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
        /// timing and MusicBee's copy does not (or MusicBee has none with timing). Japanese/romaji
        /// sidecars written by LyricLoom win for the matching display mode. Reads up to three files,
        /// so it must run on the pool, never on MusicBee's UI thread (FR-C-06).</summary>
        private string PickLyrics(SongSnapshot song, bool preferFile)
        {
            string fileLyrics = null;
            try
            {
                if (song != null && !string.IsNullOrEmpty(song.Url) && File.Exists(song.Url))
                {
                    string warning;
                    fileLyrics = SidecarFiles.ReadLyrics(song.Url, _settings.Japanese, out warning);
                    if (!string.IsNullOrEmpty(warning)) Log(warning);
                }
            }
            catch (Exception e) { Log("reading sidecar lyrics failed: " + e.Message); }

            return LyricsSelector.Choose(song?.MbLyrics, fileLyrics, preferFile);
        }

        // ---------------------------------------------------------------- sidecar watcher

        /// <summary>Keeps one watcher for the playing song while the window is open, and also while it
        /// is closed when auto-open is on, so a sidecar written by LyricLoom can open it.</summary>
        private void UpdateSidecarWatcher(string audioUrl)
        {
            int generation;
            lock (_sidecarWatcherLock)
            {
                if (!ShouldWatchSidecar(audioUrl)) { DisposeSidecarWatcherLocked(); return; }
                if (_sidecarWatcher != null &&
                    string.Equals(_sidecarWatcher.AudioPath, audioUrl, StringComparison.OrdinalIgnoreCase)) return;
                if (string.Equals(_sidecarWatcherPending, audioUrl, StringComparison.OrdinalIgnoreCase)) return;
                DisposeSidecarWatcherLocked();
                _sidecarWatcherPending = audioUrl;
                generation = _sidecarWatcherGeneration;
            }

            // FR-C-06: the watcher constructor reads the sidecar timestamps and creates a
            // FileSystemWatcher; on a network share that can block. Create it on the pool and only
            // publish it when it is still the watcher we want.
            ThreadPool.QueueUserWorkItem(_ =>
            {
                SidecarWatcher created = null;
                try
                {
                    created = new SidecarWatcher(audioUrl, path => OnSidecarChanged(audioUrl, path), LogException);
                }
                catch (Exception e)
                {
                    Log("could not watch the lyrics folder: " + e.Message);
                }
                lock (_sidecarWatcherLock)
                {
                    if (generation != _sidecarWatcherGeneration)
                    {
                        try { created?.Dispose(); } catch (Exception) { }
                        return;
                    }
                    _sidecarWatcherPending = null;
                    if (created != null && !_shuttingDown)
                    {
                        _sidecarWatcher = created;
                        return;
                    }
                    try { created?.Dispose(); } catch (Exception) { }
                }
            });
        }

        private bool ShouldWatchSidecar(string audioUrl)
        {
            // FR-C-06: no File.Exists here. The flag is refreshed on the pool; this method is called
            // from the UI thread whenever the window or auto-open settings change.
            if (_shuttingDown || string.IsNullOrEmpty(audioUrl) || !_currentSongIsLocal) return false;
            if (!string.IsNullOrEmpty(_currentSongUrl) &&
                !string.Equals(audioUrl, _currentSongUrl, StringComparison.OrdinalIgnoreCase)) return false;
            return _window != null || (_settings != null && _settings.AutoOpenLyrics != AutoOpenLyrics.Off);
        }

        /// <summary>Runs on the watcher's timer thread, then applies the result on MusicBee's UI thread.
        /// The lyrics kind is read from the sidecar that appeared, not from MusicBee's possibly stale
        /// cached copy.</summary>
        private void OnSidecarChanged(string audioUrl, string path)
        {
            var kind = LyricsKind.None;
            try { kind = AutoOpenRule.Classify(LyricsFile.Read(path).Text); }
            catch (Exception e) { Log("reading the sidecar failed: " + e.Message); }
            var playing = IsPlaying();
            OnUi(() => Safe.Run(() =>
            {
                if (_shuttingDown) return;
                if (!string.Equals(audioUrl, _currentSongUrl, StringComparison.OrdinalIgnoreCase)) return;
                Log("sidecar changed: " + Path.GetFileName(path));
                _lyricLoomRequests.Forget(audioUrl);
                _window?.ClearLyricLoomPending();
                var dismissed = string.Equals(audioUrl, _dismissedSongUrl, StringComparison.OrdinalIgnoreCase);
                var action = AutoOpenRule.DecideForSidecar(_settings.AutoOpenLyrics, kind, playing,
                    _window != null, _window != null && _window.IsVisible, dismissed);
                if (action == AutoOpenAction.Open && _window == null)
                {
                    OpenWindow(autoOpen: true, preferSidecar: true);
                    return;
                }
                if (_window == null) return;
                if (action == AutoOpenAction.Show && !_window.IsVisible)
                    ShowAuto();
                LoadSong(preferSidecar: true);
            }, LogException));
        }

        private void DisposeSidecarWatcher()
        {
            lock (_sidecarWatcherLock) DisposeSidecarWatcherLocked();
        }

        private void DisposeSidecarWatcherLocked()
        {
            _sidecarWatcherGeneration++;
            _sidecarWatcherPending = null;
            var watcher = Interlocked.Exchange(ref _sidecarWatcher, null);
            try { watcher?.Dispose(); } catch (Exception) { }
        }

        // ---------------------------------------------------------------- threading

        /// <summary>Runs on MusicBee's UI thread, where the windows live, and through the Safe guard.</summary>
        private void OnUi(Action action, bool wait = false)
        {
            void Run() => Safe.Run(action, LogException);
            var main = _mainWindow;
            if (main == null || !main.IsHandleCreated || !main.InvokeRequired) { Run(); return; }
            try
            {
                if (wait) main.Invoke((Action)Run);
                else main.BeginInvoke((Action)Run);
            }
            catch (InvalidOperationException) { }
            catch (Exception e) { Log("marshalling to MusicBee failed: " + e.Message); }
        }

        /// <summary>Reads a MusicBee value on the UI thread. NowPlaying_*, NowPlayingList_* and the
        /// storage path have no documented thread contract, so they are not called from the pool.</summary>
        private T OnUiGet<T>(Func<T> read, T fallback)
        {
            T Run() => Safe.Get(read, fallback, LogException);
            var main = _mainWindow;
            if (main == null || !main.IsHandleCreated || !main.InvokeRequired) return Run();
            try { return (T)main.Invoke((Func<T>)Run); }
            catch (Exception e)
            {
                Log("reading from MusicBee failed: " + e.Message);
                return fallback;
            }
        }
    }
}
