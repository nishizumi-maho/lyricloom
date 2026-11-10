namespace MusicBeePlugin
{
    /// <summary>Every text the scene, the karaoke window and its transport bar draw or show, in one
    /// place, so it can be translated without hunting through the drawing and menu code (and so no
    /// Portuguese label sneaks back in).</summary>
    internal static class Strings
    {
        // scene
        public const string NoSyncedLyrics = "no synced lyrics";
        public const string LoopBadge = "⟲  loop";
        public const string ThanksForSinging = "✦  thanks for singing  ✦";
        public const string CountdownDots = "·  ·  ·";
        public const string NextSongPrefix = "Next: ";

        public static string NextSongLabel(string nextSong) => NextSongPrefix + (nextSong ?? "");

        // window
        public const string WindowTitle = "Starry Karaoke";
        public const string NoWordTimingHint = "No word timing for this song. Make word-timed lyrics with LyricLoom.";
        public const string MakeWithLyricLoom = "Make with LyricLoom...";
        public const string Dismiss = "Dismiss";
        public const string LyricLoomPending = "Sent to LyricLoom — the lyrics appear here when they are ready";
        public const string ScreenshotFilePrefix = "Starry Karaoke ";
        public const string ScreenshotFolder = "Starry Karaoke";
        public const string ScreenshotSaved = "Screenshot saved";
        public const string ScreenshotFailed = "Could not save the screenshot";
        public const string JumpedToLine = "Jumped to line";
        public const string SongDelayReset = "Song delay reset";

        public static string SongDelayLabel(int milliseconds) =>
            "Song delay " + milliseconds.ToString("+0;-0;0") + " ms";

        // toasts shared with the transport bar
        public const string Muted = "Muted";
        public const string SoundOn = "Sound on";
        public const string LoopOff = "Loop off";
        public const string NoLyricsToLoop = "No lyrics to loop";
        public const string LoopingSection = "Looping this section";
        public const string LoopingLine = "Looping this line";
        public const string VolumeTip = "Volume";
        public const string MuteTip = "Mute (M)";
        public const string PlayPauseTip = "Play / pause (space)";
        public const string PreviousTrackTip = "Previous track";
        public const string BackTenSecondsTip = "Back 10 s (←)";
        public const string ForwardTenSecondsTip = "Forward 10 s (→)";
        public const string NextTrackTip = "Next track";
        public const string SongDelayTip = "This song's lyric delay; [ and ] adjust it, Ctrl+0 resets it";

        public static string TransportDelayLabel(int milliseconds) =>
            "delay " + milliseconds.ToString("+0;-0;0") + " ms";

        // context menu
        public const string ExitFullscreen = "Exit fullscreen (Esc)";
        public const string EnterFullscreen = "Fullscreen (F11)";
        public const string KeepOnTop = "Keep on top in fullscreen";
        public const string FullscreenMonitor = "Fullscreen monitor";
        public const string PrimaryMonitorSuffix = " (primary)";
        public const string CurrentMonitor = "Current monitor";
        public const string SkipIntro = "Skip intro (P)";
        public const string LoopCurrentLine = "Loop current line (L)";
        public const string LoopThisSection = "Loop this section (Shift+L)";
        public const string LoopOffItem = "Loop off";
        public const string SaveScreenshot = "Save screenshot (F12)";
        public const string Japanese = "Japanese";
        public const string RomajiOnly = "Romaji only";
        public const string JapaneseAndRomaji = "Japanese + romaji";
        public const string JapaneseOnly = "Japanese only";
        public const string MakeLyricsWithLyricLoom = "Make word-timed lyrics with LyricLoom...";
        public const string RecordSongVideo = "Record song video...";
        public const string Settings = "Settings...";
        public const string Diagnostics = "Diagnostics...";
        public const string Close = "Close";
    }
}
