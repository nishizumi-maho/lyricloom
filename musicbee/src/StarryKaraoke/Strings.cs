namespace MusicBeePlugin
{
    /// <summary>Every text the scene draws, in one place, so it can be translated without hunting
    /// through the drawing code (and so no Portuguese label sneaks back in).</summary>
    internal static class Strings
    {
        public const string NoSyncedLyrics = "no synced lyrics";
        public const string LoopBadge = "⟲  loop";
        public const string ThanksForSinging = "✦  thanks for singing  ✦";
        public const string CountdownDots = "·  ·  ·";
        public const string NextSongPrefix = "Next: ";

        public static string NextSongLabel(string nextSong) => NextSongPrefix + (nextSong ?? "");
    }
}
