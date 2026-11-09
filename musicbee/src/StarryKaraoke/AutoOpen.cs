using System;
using System.Text.RegularExpressions;

namespace MusicBeePlugin
{
    /// <summary>When the karaoke window opens by itself. A single setting with three choices:
    /// Off, only for word-timed lyrics, or for any synced lyrics.</summary>
    public enum AutoOpenLyrics
    {
        Off = 0,
        WordTimedOnly = 1,
        AnySynced = 2
    }

    /// <summary>What happens to an open window when the next song has no supported lyrics.</summary>
    public enum UnsupportedSongAction
    {
        Keep = 0,
        Hide = 1,
        Close = 2
    }

    /// <summary>What the lyrics the plugin would show can do.</summary>
    public enum LyricsKind
    {
        None = 0,
        LineTimed = 1,
        WordTimed = 2
    }

    /// <summary>What the plugin should do about the karaoke window for the current song.</summary>
    public enum AutoOpenAction
    {
        None = 0,
        Open = 1,
        Show = 2,
        Keep = 3,
        Hide = 4,
        Close = 5
    }

    /// <summary>The auto-open rules, kept free of WPF and MusicBee so they can be tested directly.</summary>
    internal static class AutoOpenRule
    {
        private static readonly Regex HasTime = new Regex(@"\[\d+:\d+", RegexOptions.Compiled);
        private static readonly Regex HasWordTime = new Regex(@"<\d+:\d+", RegexOptions.Compiled);

        /// <summary>Classifies the lyrics exactly as the window would see them. Lyrics with a timing
        /// tag but no line the parser accepts count as none.</summary>
        public static LyricsKind Classify(string lrc)
        {
            if (string.IsNullOrEmpty(lrc)) return LyricsKind.None;
            try
            {
                if (Lrc.Parse(lrc).Count == 0) return LyricsKind.None;
            }
            catch (Exception)
            {
                return LyricsKind.None;   // malformed timestamps: the plugin cannot show these lyrics
            }
            if (HasWordTime.IsMatch(lrc)) return LyricsKind.WordTimed;
            if (HasTime.IsMatch(lrc)) return LyricsKind.LineTimed;
            return LyricsKind.None;
        }

        public static bool IsSupported(AutoOpenLyrics setting, LyricsKind kind)
        {
            switch (setting)
            {
                case AutoOpenLyrics.WordTimedOnly:
                    return kind == LyricsKind.WordTimed;
                case AutoOpenLyrics.AnySynced:
                    return kind == LyricsKind.WordTimed || kind == LyricsKind.LineTimed;
                default:
                    return false;
            }
        }

        /// <summary>
        /// The whole decision table: the setting, the lyrics kind, whether playback is running, whether
        /// the window exists/is visible, whether the user closed it by hand for this song, and what to
        /// do with an unsupported song.
        /// </summary>
        public static AutoOpenAction Decide(AutoOpenLyrics setting, LyricsKind kind, bool playing,
                                            bool windowExists, bool windowVisible, bool dismissedByUser,
                                            UnsupportedSongAction unsupported)
        {
            if (setting == AutoOpenLyrics.Off) return AutoOpenAction.None;
            if (dismissedByUser) return AutoOpenAction.None;

            var supported = IsSupported(setting, kind);
            if (!windowExists)
                return supported && playing ? AutoOpenAction.Open : AutoOpenAction.None;

            if (!supported)
            {
                switch (unsupported)
                {
                    case UnsupportedSongAction.Hide: return AutoOpenAction.Hide;
                    case UnsupportedSongAction.Close: return AutoOpenAction.Close;
                    default: return AutoOpenAction.Keep;
                }
            }

            if (!playing) return AutoOpenAction.None;
            return windowVisible ? AutoOpenAction.None : AutoOpenAction.Show;
        }
    }
}
