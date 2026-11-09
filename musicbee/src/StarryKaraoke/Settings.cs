using System;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Windows.Media;
using System.Xml;
using System.Xml.Serialization;

namespace MusicBeePlugin
{
    /// <summary>Everything the user can change, saved as XML in MusicBee's persistent storage folder.</summary>
    public sealed class Settings
    {
        public string FontFamily = "Cascadia Mono, Consolas, Yu Gothic UI";
        /// <summary>Multiplies the text size the window picks from its height.</summary>
        public double TextScale = 1.0;
        public string LitColor = "#FFCE5C";
        public string HeadColor = "#FFFFEB";
        public string UnlitColor = "#9496B2";
        public string DimColor = "#4E5068";
        public string GlowColor = "#FFB43C";
        public string BackgroundTop = "#0A0A18";
        public string BackgroundBottom = "#16102C";
        public string AccentColor = "#8C78FF";
        /// <summary>A named preset copied into the colour fields; empty or "Custom" means the colours
        /// below are used as they are (so settings written by an older version keep their custom look).</summary>
        public string Theme = "";
        /// <summary>Pick a different preset for every song. Useful at parties and for testing.</summary>
        public bool RandomTheme;
        public JapaneseMode Japanese = JapaneseMode.RomajiOnly;
        public bool ShowStars = true;
        /// <summary>A comet crossing the sky every so often.</summary>
        public bool ShowShootingStars = true;
        /// <summary>0.25 (few) to 2 (many).</summary>
        public double StarDensity = 1.0;
        public bool Glow = true;
        public bool GrowCurrentLine = true;
        /// <summary>A small burst of stars when a line is finished.</summary>
        public bool LineBursts = true;
        /// <summary>Party mode: open in fullscreen on playback, hide the cursor and keep the display awake.</summary>
        public bool PartyMode;
        /// <summary>In party mode, show the next track during the last seconds of the song.</summary>
        public bool ShowNextSong = true;
        /// <summary>0.5 (slow) to 2 (fast): scroll, fades and the line growing.</summary>
        public double TransitionSpeed = 1.0;
        /// <summary>Added to the lyrics' timing: positive shows them later.</summary>
        public int LyricsOffsetMs = 0;
        public bool ShowHeader = true;
        public bool ShowProgress = true;
        /// <summary>Fullscreen shows only the lyrics (no title, no progress bar).</summary>
        public bool FullscreenLyricsOnly = true;
        /// <summary>ffmpeg.exe for recording videos; empty: found on PATH or next to the plugin.</summary>
        public string FfmpegPath = "";
        /// <summary>Jump over the instrumental intro whenever a song starts.</summary>
        public bool AutoSkipIntro;
        /// <summary>Recorded videos start just before the first sung line (audio cut at the same point).</summary>
        public bool VideoSkipIntro;
        /// <summary>How long before the first sung line a skipped intro resumes.</summary>
        public int IntroLeadMs = 3000;
        /// <summary>Frame rate of the karaoke window: 0 follows the monitor's refresh rate.</summary>
        public int WindowFps = 0;
        public string VideoResolution = "1920x1080";
        public int VideoFps = 30;

        public double WindowLeft = double.NaN, WindowTop = double.NaN, WindowWidth = 1100, WindowHeight = 680;
        /// <summary>Device name of the monitor the window was last on (empty: current/primary).</summary>
        public string WindowMonitor = "";
        public bool Fullscreen;
        public bool WindowOpen;

        /// <summary>Off, only for word-timed lyrics, or for any synced lyrics. Defaults to word-timed,
        /// also for settings files written by 1.2: the window opens without taking the focus.</summary>
        public AutoOpenLyrics AutoOpenLyrics = AutoOpenLyrics.WordTimedOnly;
        public UnsupportedSongAction OnUnsupportedSong = UnsupportedSongAction.Keep;
        /// <summary>Bring the window to the front when auto-open shows it. Off by default so a song
        /// starting in MusicBee never interrupts another application.</summary>
        public bool AutoOpenFocus;

        /// <summary>LyricLoom.exe; empty means discover it automatically.</summary>
        public string LyricLoomPath = "";
        /// <summary>Written by this version so a later load can tell a 1.2 file from a current one.</summary>
        public int SettingsVersion = 1;

        public const string FileName = "mb_StarryKaraoke.xml";

        public static Settings Load(string folder, string fileName = FileName)
        {
            string warning;
            return LoadWithReport(folder, fileName, out warning);
        }

        /// <summary>Loads and validates settings. A file that cannot be parsed is kept as
        /// *.bad-&lt;timestamp&gt; and reported through <paramref name="warning"/> instead of being
        /// silently overwritten.</summary>
        public static Settings LoadWithReport(string folder, string fileName, out string warning)
        {
            warning = null;
            var path = Path.Combine(folder ?? "", fileName);
            if (!File.Exists(path)) return new Settings();

            try
            {
                var doc = new XmlDocument();
                using (var input = File.OpenRead(path)) doc.Load(input);
                SanitizeValues(doc);

                Settings settings;
                using (var sanitized = new MemoryStream())
                {
                    doc.Save(sanitized);
                    sanitized.Position = 0;
                    settings = (Settings)new XmlSerializer(typeof(Settings)).Deserialize(sanitized);
                }
                if (settings == null) throw new InvalidDataException("The settings file is empty.");

                settings.Validate();
                return settings;
            }
            catch (Exception e)
            {
                var bad = path + ".bad-" + DateTime.Now.ToString("yyyyMMdd-HHmmss-fff", CultureInfo.InvariantCulture);
                string kept = null;
                try
                {
                    if (File.Exists(bad)) File.Delete(bad);
                    File.Move(path, bad);
                    kept = bad;
                }
                catch (Exception moveError)
                {
                    try
                    {
                        File.Copy(path, bad, true);
                        kept = bad;
                    }
                    catch (Exception) { }
                    warning = kept != null
                        ? "Your Starry Karaoke settings could not be read, so they were reset. A copy of the old file was kept as " + kept + "."
                        : "Your Starry Karaoke settings could not be read (" + e.Message +
                          "), and the old file could not be moved or copied (" + moveError.Message + ").";
                    return AfterReadFailure();
                }
                warning = "Your Starry Karaoke settings could not be read, so they were reset. " +
                          "The old file was kept as " + kept + ".";
                return AfterReadFailure();
            }
        }

        /// <summary>A settings file existed but could not be read: start from the defaults.</summary>
        private static Settings AfterReadFailure() => new Settings();

        /// <summary>Deletes the files this plugin keeps in <paramref name="folder"/>: the settings, their
        /// backup, kept unreadable copies and leftover temp files. Used when the user uninstalls the
        /// plugin from MusicBee. Returns how many files were deleted; never throws.</summary>
        public static int DeleteFiles(string folder, string fileName = FileName)
        {
            if (string.IsNullOrEmpty(folder) || !Directory.Exists(folder)) return 0;
            var deleted = 0;
            var patterns = new[] { fileName, fileName + ".bak", fileName + ".bad-*", fileName + ".*.tmp" };
            foreach (var pattern in patterns)
            {
                string[] files;
                try { files = Directory.GetFiles(folder, pattern); }
                catch (Exception) { continue; }
                foreach (var file in files)
                {
                    try { File.Delete(file); deleted++; }
                    catch (Exception) { }
                }
            }
            return deleted;
        }

        public void Save(string folder, string fileName = FileName)
        {
            Validate();
            var path = Path.Combine(folder ?? "", fileName);
            var tmp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                using (var f = File.Create(tmp)) new XmlSerializer(typeof(Settings)).Serialize(f, this);
                if (!File.Exists(path))
                {
                    File.Move(tmp, path);
                    return;
                }

                var backup = path + ".bak";
                try { if (File.Exists(backup)) File.Delete(backup); } catch (Exception) { }
                try
                {
                    File.Replace(tmp, path, backup, true);
                }
                catch (Exception)
                {
                    // Some non-NTFS folders do not support File.Replace. Keep a backup and fall back to
                    // a move; restore the backup if the move itself fails.
                    if (File.Exists(path)) File.Copy(path, backup, true);
                    try
                    {
                        if (File.Exists(path)) File.Delete(path);
                        File.Move(tmp, path);
                    }
                    catch
                    {
                        if (!File.Exists(path) && File.Exists(backup)) File.Copy(backup, path, true);
                        throw;
                    }
                }
            }
            finally
            {
                try { if (File.Exists(tmp)) File.Delete(tmp); } catch (Exception) { }
            }
        }

        /// <summary>Clamps and repairs every numeric, enum and colour field. Called after Load and again
        /// before Save, so a hand-edited or partially migrated file cannot reach the UI.</summary>
        public void Validate()
        {
            if (string.IsNullOrWhiteSpace(FontFamily)) FontFamily = "Cascadia Mono, Consolas, Yu Gothic UI";
            TextScale = Clamp(TextScale, 0.4, 2.5, 1.0);
            StarDensity = Clamp(StarDensity, 0.25, 2.0, 1.0);
            TransitionSpeed = Clamp(TransitionSpeed, 0.3, 3.0, 1.0);
            LyricsOffsetMs = Math.Max(-10000, Math.Min(10000, LyricsOffsetMs));
            IntroLeadMs = Math.Max(0, Math.Min(10000, IntroLeadMs));
            WindowFps = Math.Max(0, Math.Min(240, WindowFps));
            VideoFps = Math.Max(10, Math.Min(240, VideoFps));

            if (double.IsInfinity(WindowLeft)) WindowLeft = double.NaN;
            if (double.IsInfinity(WindowTop)) WindowTop = double.NaN;
            WindowWidth = Clamp(WindowWidth, 100, 10000, 1100);
            WindowHeight = Clamp(WindowHeight, 100, 10000, 680);
            if (string.IsNullOrWhiteSpace(WindowMonitor)) WindowMonitor = "";

            if (!Enum.IsDefined(typeof(JapaneseMode), Japanese)) Japanese = JapaneseMode.RomajiOnly;
            if (!Enum.IsDefined(typeof(AutoOpenLyrics), AutoOpenLyrics)) AutoOpenLyrics = AutoOpenLyrics.WordTimedOnly;
            if (!Enum.IsDefined(typeof(UnsupportedSongAction), OnUnsupportedSong)) OnUnsupportedSong = UnsupportedSongAction.Keep;
            if (SettingsVersion < 1) SettingsVersion = 1;

            if (string.IsNullOrWhiteSpace(VideoResolution)) VideoResolution = "1920x1080";
            if (FfmpegPath == null) FfmpegPath = "";
            if (LyricLoomPath == null) LyricLoomPath = "";
            if (Theme == null) Theme = "";

            LitColor = ValidColor(LitColor, "#FFCE5C");
            HeadColor = ValidColor(HeadColor, "#FFFFEB");
            UnlitColor = ValidColor(UnlitColor, "#9496B2");
            DimColor = ValidColor(DimColor, "#4E5068");
            GlowColor = ValidColor(GlowColor, "#FFB43C");
            BackgroundTop = ValidColor(BackgroundTop, "#0A0A18");
            BackgroundBottom = ValidColor(BackgroundBottom, "#16102C");
            AccentColor = ValidColor(AccentColor, "#8C78FF");
        }

        private static double Clamp(double value, double min, double max, double fallback)
        {
            if (double.IsNaN(value) || double.IsInfinity(value)) value = fallback;
            return Math.Max(min, Math.Min(max, value));
        }

        private static string ValidColor(string value, string fallback)
        {
            try
            {
                ColorConverter.ConvertFromString(value);
                return value;
            }
            catch (Exception)
            {
                return fallback;
            }
        }

        /// <summary>Repairs values the XML serializer would reject before it sees them, so one unknown
        /// enum or a text value in a numeric field does not discard the rest of the file.</summary>
        private static void SanitizeValues(XmlDocument doc)
        {
            if (doc.DocumentElement == null) return;
            for (var i = doc.DocumentElement.ChildNodes.Count - 1; i >= 0; i--)
            {
                var element = doc.DocumentElement.ChildNodes[i] as XmlElement;
                if (element == null) continue;
                var value = element.InnerText;
                switch (element.Name)
                {
                    case "Japanese":
                        RepairEnum(element, typeof(JapaneseMode), JapaneseMode.RomajiOnly);
                        break;
                    case "AutoOpenLyrics":
                        RepairEnum(element, typeof(AutoOpenLyrics), AutoOpenLyrics.WordTimedOnly);
                        break;
                    case "OnUnsupportedSong":
                        RepairEnum(element, typeof(UnsupportedSongAction), UnsupportedSongAction.Keep);
                        break;
                    case "TextScale":
                    case "StarDensity":
                    case "TransitionSpeed":
                    case "WindowLeft":
                    case "WindowTop":
                    case "WindowWidth":
                    case "WindowHeight":
                        double d;
                        if (!double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out d))
                            doc.DocumentElement.RemoveChild(element);
                        break;
                    case "LyricsOffsetMs":
                    case "IntroLeadMs":
                    case "WindowFps":
                    case "VideoFps":
                    case "SettingsVersion":
                        int n;
                        if (!int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out n))
                            doc.DocumentElement.RemoveChild(element);
                        break;
                    case "RandomTheme":
                    case "ShowStars":
                    case "ShowShootingStars":
                    case "Glow":
                    case "GrowCurrentLine":
                    case "LineBursts":
                    case "PartyMode":
                    case "ShowNextSong":
                    case "ShowHeader":
                    case "ShowProgress":
                    case "FullscreenLyricsOnly":
                    case "AutoSkipIntro":
                    case "VideoSkipIntro":
                    case "Fullscreen":
                    case "WindowOpen":
                    case "AutoOpenFocus":
                        bool b;
                        if (!bool.TryParse(value, out b) && value != "0" && value != "1")
                            doc.DocumentElement.RemoveChild(element);
                        break;
                }
            }
        }

        private static void RepairEnum(XmlElement element, Type type, object fallback)
        {
            try
            {
                var parsed = Enum.Parse(type, element.InnerText);
                if (Enum.IsDefined(type, parsed)) return;
            }
            catch (Exception) { }
            element.InnerText = fallback.ToString();
        }

        public Settings Clone()
        {
            var c = (Settings)MemberwiseClone();
            return c;
        }

        public static Color ParseColor(string hex, Color fallback)
        {
            try { return (Color)ColorConverter.ConvertFromString(hex); }
            catch (Exception) { return fallback; }
        }

        public static string ToHex(Color c) => c.A == 255 ? $"#{c.R:X2}{c.G:X2}{c.B:X2}" : $"#{c.A:X2}{c.R:X2}{c.G:X2}{c.B:X2}";
    }
}
