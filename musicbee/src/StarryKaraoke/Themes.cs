using System;

namespace MusicBeePlugin
{
    /// <summary>A named set of colours. Applying one copies its values into the settings, so the colour
    /// fields stay the single source of truth for the scene.</summary>
    internal sealed class ThemePalette
    {
        public string Name;
        public string Lit, Head, Unlit, Dim, Glow, BackgroundTop, BackgroundBottom, Accent;

        public void CopyTo(Settings s)
        {
            s.Theme = Name;
            s.LitColor = Lit;
            s.HeadColor = Head;
            s.UnlitColor = Unlit;
            s.DimColor = Dim;
            s.GlowColor = Glow;
            s.BackgroundTop = BackgroundTop;
            s.BackgroundBottom = BackgroundBottom;
            s.AccentColor = Accent;
        }
    }

    internal static class Themes
    {
        public const string Custom = "Custom";

        private static readonly ThemePalette[] Presets =
        {
            new ThemePalette
            {
                Name = "Starry",
                Lit = "#FFCE5C", Head = "#FFFFEB", Unlit = "#9496B2", Dim = "#4E5068",
                Glow = "#FFB43C", BackgroundTop = "#0A0A18", BackgroundBottom = "#16102C", Accent = "#8C78FF"
            },
            new ThemePalette
            {
                Name = "Aurora",
                Lit = "#7CF7D4", Head = "#E9FFF9", Unlit = "#7FA6B8", Dim = "#3E5C6E",
                Glow = "#3DE0B0", BackgroundTop = "#04121A", BackgroundBottom = "#0A2430", Accent = "#79D7FF"
            },
            new ThemePalette
            {
                Name = "Sakura",
                Lit = "#FFA6C9", Head = "#FFF0F6", Unlit = "#C9A6B8", Dim = "#6E4A5E",
                Glow = "#FF7FB0", BackgroundTop = "#1A0A14", BackgroundBottom = "#2A1220", Accent = "#FFD1E6"
            },
            new ThemePalette
            {
                Name = "Neon",
                Lit = "#FF4FD8", Head = "#FFFFFF", Unlit = "#8F7BB8", Dim = "#4A3A6E",
                Glow = "#FF2BD6", BackgroundTop = "#05030F", BackgroundBottom = "#120A2A", Accent = "#4FF7FF"
            },
            new ThemePalette
            {
                Name = "Sunset",
                Lit = "#FFB15C", Head = "#FFF2D6", Unlit = "#C28E7A", Dim = "#6E4A44",
                Glow = "#FF6B3D", BackgroundTop = "#1A0A0A", BackgroundBottom = "#2B1320", Accent = "#FF7A9C"
            },
            new ThemePalette
            {
                Name = "Snow",
                Lit = "#C8E8FF", Head = "#FFFFFF", Unlit = "#8FA6BC", Dim = "#46586C",
                Glow = "#7FC8FF", BackgroundTop = "#071018", BackgroundBottom = "#101C2A", Accent = "#B8D8FF"
            }
        };

        public static readonly string[] Names = BuildNames();

        private static string[] BuildNames()
        {
            var names = new string[Presets.Length + 1];
            for (var i = 0; i < Presets.Length; i++) names[i] = Presets[i].Name;
            names[Presets.Length] = Custom;
            return names;
        }

        public static ThemePalette Get(string name)
        {
            if (string.IsNullOrEmpty(name) || name == Custom) return null;
            foreach (var p in Presets)
                if (string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase)) return p;
            return null;
        }

        /// <summary>A preset that stays the same for the same song, so the sky does not change on every
        /// poll while a random theme is on.</summary>
        public static ThemePalette ForSong(string title)
        {
            if (string.IsNullOrEmpty(title)) return Presets[0];
            unchecked
            {
                var hash = 17;
                foreach (var c in title) hash = hash * 31 + c;
                return Presets[(hash & 0x7fffffff) % Presets.Length];
            }
        }
    }
}
