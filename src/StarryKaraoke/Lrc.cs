using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace MusicBeePlugin
{
    /// <summary>One timed line of the LRC as written: start time and the text split at its word tags.</summary>
    internal sealed class RawLine
    {
        public double StartMs;
        /// <summary>Pieces of the line; StartMs is NaN for the piece before the first word tag.</summary>
        public List<(double StartMs, string Text)> Pieces = new List<(double, string)>();
        /// <summary>End of the last word when the line closes with an empty word tag, else NaN.</summary>
        public double EndTagMs = double.NaN;
        public string Text => string.Concat(Pieces.Select(p => p.Text));
        public bool HasWordTimes => Pieces.Any(p => !double.IsNaN(p.StartMs));
    }

    internal static class Lrc
    {
        private static readonly Regex TimeTag = new Regex(@"\G\[(\d+):(\d+(?:[.:]\d+)?)\]", RegexOptions.Compiled);
        private static readonly Regex WordTag = new Regex(@"<(\d+):(\d+(?:[.:]\d+)?)>", RegexOptions.Compiled);
        private static readonly Regex Offset = new Regex(@"^\[offset:\s*([+-]?\d+)\s*\]", RegexOptions.Compiled | RegexOptions.IgnoreCase);

        private static double Ms(string min, string sec) =>
            int.Parse(min, CultureInfo.InvariantCulture) * 60000.0 +
            double.Parse(sec.Replace(':', '.'), CultureInfo.InvariantCulture) * 1000.0;

        /// <summary>Timed lines sorted by start, with [offset:] applied (positive offset = lyrics earlier).
        /// Lines without a time tag (tags like [ti:], [#source:], plain text) are ignored.</summary>
        public static List<RawLine> Parse(string lrc)
        {
            var lines = new List<RawLine>();
            if (string.IsNullOrEmpty(lrc)) return lines;
            double offset = 0;
            foreach (var rawLine in lrc.Replace("\r\n", "\n").Replace('\r', '\n').Split('\n'))
            {
                var raw = rawLine.Trim().TrimStart('﻿');
                var om = Offset.Match(raw);
                if (om.Success) { offset = int.Parse(om.Groups[1].Value, CultureInfo.InvariantCulture); continue; }

                var stamps = new List<double>();
                var pos = 0;
                for (var m = TimeTag.Match(raw, pos); m.Success; m = TimeTag.Match(raw, pos))
                {
                    stamps.Add(Ms(m.Groups[1].Value, m.Groups[2].Value));
                    pos = m.Index + m.Length;
                }
                if (stamps.Count == 0) continue;
                var body = raw.Substring(pos);
                foreach (var t in stamps) lines.Add(ParseBody(t, body));
            }
            foreach (var l in lines)
            {
                l.StartMs -= offset;
                if (!double.IsNaN(l.EndTagMs)) l.EndTagMs -= offset;
                for (var i = 0; i < l.Pieces.Count; i++)
                    if (!double.IsNaN(l.Pieces[i].StartMs)) l.Pieces[i] = (l.Pieces[i].StartMs - offset, l.Pieces[i].Text);
            }
            return lines.OrderBy(l => l.StartMs).ToList();
        }

        private static RawLine ParseBody(double start, string body)
        {
            // A trailing closing tag is often followed by a space (LYRICS BOCA and some editors write
            // "<00:12.34> "). Without trimming, the tag becomes ordinary text and the last word stretches
            // until the next line instead of ending where the file says it does.
            body = (body ?? "").TrimEnd();
            var line = new RawLine { StartMs = start };
            var pos = 0;
            var pieceStart = double.NaN;
            foreach (Match m in WordTag.Matches(body))
            {
                if (m.Index > pos) line.Pieces.Add((pieceStart, body.Substring(pos, m.Index - pos)));
                pieceStart = Ms(m.Groups[1].Value, m.Groups[2].Value);
                pos = m.Index + m.Length;
            }
            if (pos < body.Length) line.Pieces.Add((pieceStart, body.Substring(pos)));
            else if (!double.IsNaN(pieceStart) && pos > 0) line.EndTagMs = pieceStart;
            return line;
        }

        public static bool IsJapanese(string s) => !string.IsNullOrEmpty(s) && s.Any(c =>
            (c >= '぀' && c <= 'ヿ') || (c >= '㐀' && c <= '鿿') || (c >= 'ｦ' && c <= 'ﾟ'));

        /// <summary>Full-width spaces and punctuation folded to ASCII, runs of spaces collapsed.</summary>
        public static string Tidy(string s) =>
            Regex.Replace((s ?? "").Normalize(NormalizationForm.FormKC), @"\s+", " ").Trim();
    }

    /// <summary>A line of text with, for each character, the time it finishes lighting.</summary>
    internal sealed class TimedText
    {
        public string Text = "";
        public double[] CharEndMs = new double[0];
        public double StartMs;

        /// <summary>How many characters are lit at time t, fractional while one is lighting.</summary>
        public double LitChars(double t)
        {
            var n = Text.Length;
            if (n == 0 || t <= StartMs) return 0;
            if (t >= CharEndMs[n - 1]) return n;
            // i = number of characters already done (end <= t); the one at i is lighting
            int lo = 0, hi = n;
            while (lo < hi)
            {
                var mid = (lo + hi) / 2;
                if (CharEndMs[mid] <= t) lo = mid + 1; else hi = mid;
            }
            var i = lo;
            var begin = i == 0 ? StartMs : CharEndMs[i - 1];
            var span = CharEndMs[i] - begin;
            return i + (span <= 0 ? 1 : Math.Max(0, Math.Min(1, (t - begin) / span)));
        }

        /// <summary>Lights the non-space characters of [from, to) evenly between tFrom and tTo; a space
        /// lights together with the character before it.</summary>
        public static void Spread(double[] ends, string text, int from, int to, double tFrom, double tTo)
        {
            var idx = new List<int>();
            for (var i = from; i < to; i++) if (text[i] != ' ') idx.Add(i);
            for (var k = 0; k < idx.Count; k++) ends[idx[k]] = tFrom + (tTo - tFrom) * (k + 1) / idx.Count;
            for (var i = from; i < to; i++)
                if (text[i] == ' ') ends[i] = i > from ? ends[i - 1] : tFrom;
        }

        /// <summary>Builds the timing from marks (char index, time a word starts) up to lineEnd.</summary>
        public static TimedText FromMarks(string text, double lineStart, double lineEnd, List<(int Index, double Ms)> marks)
        {
            var tt = new TimedText { Text = text, CharEndMs = new double[text.Length], StartMs = lineStart };
            if (text.Length == 0) return tt;
            var ms = (marks ?? new List<(int, double)>()).Where(m => m.Index >= 0 && m.Index < text.Length)
                                                         .OrderBy(m => m.Index).ToList();
            // keep times moving forward
            for (var k = 1; k < ms.Count; k++)
                if (ms[k].Ms < ms[k - 1].Ms) ms[k] = (ms[k].Index, ms[k - 1].Ms);
            if (ms.Count == 0 || ms[0].Index > 0) ms.Insert(0, (0, lineStart));
            ms.Add((text.Length, Math.Max(lineEnd, ms[ms.Count - 1].Ms + 50)));
            for (var k = 0; k + 1 < ms.Count; k++)
                Spread(tt.CharEndMs, text, ms[k].Index, ms[k + 1].Index, ms[k].Ms, Math.Max(ms[k + 1].Ms, ms[k].Ms + 30));
            for (var i = 1; i < tt.CharEndMs.Length; i++)
                if (tt.CharEndMs[i] < tt.CharEndMs[i - 1]) tt.CharEndMs[i] = tt.CharEndMs[i - 1];
            return tt;
        }
    }

    public enum JapaneseMode { RomajiOnly = 0, JapaneseAndRomaji = 1, JapaneseOnly = 2 }

    /// <summary>A line as the karaoke window shows it: the main text and, optionally, a smaller one under it.</summary>
    internal sealed class KaraokeLine
    {
        public double StartMs, EndMs, NextMs;
        public TimedText Main, Sub;
        public bool IsBreak => string.IsNullOrEmpty(Main.Text);
    }

    internal static class Timeline
    {
        /// <summary>Turns parsed lines into karaoke lines. romanize converts Japanese text (null: no romaji).</summary>
        public static List<KaraokeLine> Build(List<RawLine> raw, double songMs, JapaneseMode mode, Func<string, string> romanize)
        {
            var result = new List<KaraokeLine>();
            for (var i = 0; i < raw.Count; i++)
            {
                var r = raw[i];
                var next = i + 1 < raw.Count ? raw[i + 1].StartMs : Math.Max(songMs, r.StartMs + 8000);
                var original = Lrc.Tidy(r.Text);
                var jp = romanize != null && Lrc.IsJapanese(original);
                var romaji = jp ? Lrc.Tidy(romanize(r.Text)) : null;
                if (jp && romaji.Length == 0) { jp = false; romaji = null; }   // romaji engine unavailable

                var letters = (romaji ?? original).Count(c => c != ' ');
                if (!jp && Lrc.IsJapanese(original)) letters = (int)(letters * 2.5);
                var end = Math.Min(next - 100, r.StartMs + Math.Max(1400, letters * 85 + 600));
                if (!double.IsNaN(r.EndTagMs)) end = Math.Min(next - 30, r.EndTagMs);
                else if (r.HasWordTimes) end = Math.Min(next - 50, LastWordEnd(r));
                end = Math.Max(end, r.StartMs + 300);

                var line = new KaraokeLine { StartMs = r.StartMs, EndMs = end, NextMs = next };
                var originalTimed = Timed(r, original, end, null);
                if (!jp || mode == JapaneseMode.JapaneseOnly) line.Main = originalTimed;
                else
                {
                    var romajiTimed = Timed(r, romaji, end, romanize);
                    if (mode == JapaneseMode.RomajiOnly) line.Main = romajiTimed;
                    else { line.Main = originalTimed; line.Sub = romajiTimed; }
                }
                result.Add(line);
            }
            return result;
        }

        /// <summary>When the last word of a word-timed line stops being sung. Word tags only mark where each
        /// word starts (LYRICS BOCA writes no closing tag), so the last word gets about as long as the line's
        /// other words took, adjusted for its length. Lighting it until the next line would stretch it over
        /// any instrumental in between.</summary>
        internal static double LastWordEnd(RawLine r)
        {
            var words = r.Pieces.Where(p => !double.IsNaN(p.StartMs) && p.Text.Trim().Length > 0).ToList();
            var last = words[words.Count - 1];
            var gaps = new List<double>();
            for (var k = 1; k < words.Count; k++)
            {
                var g = words[k].StartMs - words[k - 1].StartMs;
                if (g > 0) gaps.Add(g);
            }
            gaps.Sort();
            var typical = gaps.Count > 0 ? gaps[gaps.Count / 2] : 500;
            var letters = Lrc.Tidy(last.Text).Count(c => c != ' ');
            var byLength = letters * (Lrc.IsJapanese(last.Text) ? 180 : 75);
            return last.StartMs + Math.Max(250, Math.Min(1500, Math.Max(typical, byLength)));
        }

        /// <summary>Times `text` (the line itself, or its romaji when romanize is given) from the word tags.
        /// Romaji of syllable-sized pieces alone reads badly, so the romaji is of the whole line, and each
        /// piece starts at its share of the romaji letters.</summary>
        private static TimedText Timed(RawLine r, string text, double end, Func<string, string> romanize)
        {
            if (!r.HasWordTimes) return TimedText.FromMarks(text, r.StartMs, end, null);
            var pieces = r.Pieces.Select(p => (p.StartMs, Text: Lrc.Tidy(p.Text), Raw: p.Text)).ToList();
            var weights = pieces.Select(p => p.Text.Length == 0 ? 0
                : romanize == null ? p.Text.Count(c => c != ' ')
                : Math.Max(1, Lrc.Tidy(romanize(p.Raw)).Count(c => c != ' '))).ToList();
            var letterIdx = Enumerable.Range(0, text.Length).Where(i => text[i] != ' ').ToList();
            if (letterIdx.Count == 0) return TimedText.FromMarks(text, r.StartMs, end, null);
            double total = Math.Max(1, weights.Sum()), acc = 0;
            var marks = new List<(int, double)>();
            for (var k = 0; k < pieces.Count; k++)
            {
                if (!double.IsNaN(pieces[k].StartMs) && weights[k] > 0)
                {
                    var li = Math.Min(letterIdx.Count - 1, (int)Math.Round(acc / total * letterIdx.Count));
                    marks.Add((letterIdx[li], pieces[k].StartMs));
                }
                acc += weights[k];
            }
            return TimedText.FromMarks(text, r.StartMs, end, marks);
        }

        /// <summary>Where a skipped intro resumes: leadMs before the first line with text, or null when the
        /// intro is too short to be worth skipping.</summary>
        public static double? IntroSkipTarget(IReadOnlyList<KaraokeLine> lines, double leadMs)
        {
            foreach (var l in lines)
            {
                if (l.IsBreak) continue;
                var target = l.StartMs - Math.Max(0, leadMs);
                return target > 1500 ? target : (double?)null;
            }
            return null;
        }

        /// <summary>Index of the line playing at t (the last one started), -1 before the first.</summary>
        public static int CurrentIndex(IReadOnlyList<KaraokeLine> lines, double t)
        {
            int lo = 0, hi = lines.Count - 1, found = -1;
            while (lo <= hi)
            {
                var mid = (lo + hi) / 2;
                if (lines[mid].StartMs <= t) { found = mid; lo = mid + 1; }
                else hi = mid - 1;
            }
            return found;
        }
    }
}
