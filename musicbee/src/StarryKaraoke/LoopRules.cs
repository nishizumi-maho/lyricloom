namespace MusicBeePlugin
{
    /// <summary>Which practice loop is active. Kept plain so the line/section switch can be tested
    /// without a window.</summary>
    internal enum LoopMode
    {
        Off = 0,
        Line = 1,
        Section = 2
    }

    internal static class LoopRules
    {
        /// <summary>`L` and the "loop current line" command toggle the line loop; pressing the same
        /// command again turns the loop off.</summary>
        public static LoopMode Toggle(LoopMode current, LoopMode requested) =>
            current == requested ? LoopMode.Off : requested;

        /// <summary>Menu commands that name a range ("Loop this section") always switch to that range,
        /// even when a different range is already looping.</summary>
        public static LoopMode Set(LoopMode current, LoopMode requested) => requested;

        public static LoopMode Off(LoopMode current) => LoopMode.Off;
    }
}
