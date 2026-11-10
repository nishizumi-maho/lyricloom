using System;
using System.IO;
using System.Text;

namespace MusicBeePlugin
{
    /// <summary>Text read from a lyrics file and the encoding that was used. The encoding name is safe
    /// to log; the text is never logged.</summary>
    internal sealed class DecodedLyrics
    {
        public string Text = "";
        public string EncodingName = "";
        public string Warning;
    }

    /// <summary>
    /// Reads sidecar .lrc files written by older tools. Detection order: BOM, strict UTF-8, the system
    /// ANSI code page, then CP932 (Shift-JIS). CP932 is chosen over a Western ANSI interpretation when
    /// the bytes decode cleanly as Japanese, which is what makes files from Japanese Windows tools
    /// display correctly on an English Windows install.
    /// </summary>
    internal static class LyricsFile
    {
        public static DecodedLyrics Read(string path) => Decode(File.ReadAllBytes(path));

        public static DecodedLyrics Decode(byte[] bytes, Encoding ansiFallback = null)
        {
            bytes = bytes ?? new byte[0];

            DecodedLyrics bom;
            if (TryBom(bytes, out bom)) return bom;

            var utf8 = new UTF8Encoding(false, true);
            try { return Result(utf8.GetString(bytes), "UTF-8", false); }
            catch (DecoderFallbackException) { }

            var ansi = ansiFallback ?? Encoding.Default;
            var ansiStrict = Strict(ansi);
            string ansiText = null;
            try { ansiText = ansiStrict.GetString(bytes); } catch (DecoderFallbackException) { }

            if (ansi.CodePage != 932)
            {
                Encoding cp932 = null;
                try { cp932 = Strict(Encoding.GetEncoding(932)); } catch (Exception) { }
                string cp932Text = null;
                if (cp932 != null)
                {
                    try { cp932Text = cp932.GetString(bytes); } catch (DecoderFallbackException) { }
                }

                if (cp932Text != null && LooksJapanese(cp932Text) && (ansiText == null || !LooksJapanese(ansiText)))
                    return Result(cp932Text, "Shift-JIS (CP932)", true);

                if (ansiText != null) return Result(ansiText, ansi.WebName, true);
                if (cp932Text != null) return Result(cp932Text, "Shift-JIS (CP932)", true);
            }
            else if (ansiText != null)
            {
                return Result(ansiText, "Shift-JIS (CP932)", true);
            }

            // Neither strict decoder accepted the bytes: show the ANSI replacement characters rather
            // than losing the file. The warning tells the user why.
            var fallback = ansi.GetString(bytes);
            return Result(fallback, ansi.WebName + " (with replacement characters)", true);
        }

        private static DecodedLyrics Result(string text, string name, bool nonUtf8)
        {
            return new DecodedLyrics
            {
                Text = text ?? "",
                EncodingName = name,
                Warning = nonUtf8 ? "The lyrics file is not UTF-8; it was read as " + name + "." : null
            };
        }

        private static Encoding Strict(Encoding encoding) =>
            Encoding.GetEncoding(encoding.CodePage, EncoderFallback.ExceptionFallback, DecoderFallback.ExceptionFallback);

        private static bool TryBom(byte[] b, out DecodedLyrics result)
        {
            result = null;
            if (b.Length >= 4 && b[0] == 0xFF && b[1] == 0xFE && b[2] == 0x00 && b[3] == 0x00)
            {
                result = Result(new UTF32Encoding(false, true).GetString(b, 4, b.Length - 4), "UTF-32 LE", false);
                return true;
            }
            if (b.Length >= 4 && b[0] == 0x00 && b[1] == 0x00 && b[2] == 0xFE && b[3] == 0xFF)
            {
                result = Result(new UTF32Encoding(true, true).GetString(b, 4, b.Length - 4), "UTF-32 BE", false);
                return true;
            }
            if (b.Length >= 3 && b[0] == 0xEF && b[1] == 0xBB && b[2] == 0xBF)
            {
                result = Result(new UTF8Encoding(false, true).GetString(b, 3, b.Length - 3), "UTF-8 (BOM)", false);
                return true;
            }
            if (b.Length >= 2 && b[0] == 0xFF && b[1] == 0xFE)
            {
                result = Result(new UnicodeEncoding(false, true).GetString(b, 2, b.Length - 2), "UTF-16 LE", false);
                return true;
            }
            if (b.Length >= 2 && b[0] == 0xFE && b[1] == 0xFF)
            {
                result = Result(new UnicodeEncoding(true, true).GetString(b, 2, b.Length - 2), "UTF-16 BE", false);
                return true;
            }
            return false;
        }

        /// <summary>A clean CP932 decode with kana (or several kanji) is Japanese text rather than a
        /// Western code page's accented letters.</summary>
        private static bool LooksJapanese(string text)
        {
            if (string.IsNullOrEmpty(text)) return false;
            var kana = 0;
            var cjk = 0;
            foreach (var c in text)
            {
                if ((c >= '\u3040' && c <= '\u30FF') || (c >= '\uFF66' && c <= '\uFF9F')) kana++;
                else if (c >= '\u3400' && c <= '\u9FFF') cjk++;
            }
            return kana >= 1 || cjk >= 3;
        }
    }
}
