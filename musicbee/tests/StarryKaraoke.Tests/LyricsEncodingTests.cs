using System;
using System.Linq;
using System.Text;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class LyricsEncodingTests
    {
        private const string Japanese = "[00:01.00]<00:01.00>こんにちは <00:02.00>世界\n";
        private const string Western = "[00:01.00]café déjà vu\n";

        private static byte[] WithPreamble(Encoding encoding, string text) =>
            encoding.GetPreamble().Concat(encoding.GetBytes(text)).ToArray();

        [Fact]
        public void Utf8_with_bom_is_decoded()
        {
            var decoded = LyricsFile.Decode(WithPreamble(new UTF8Encoding(true), Japanese));
            Assert.Equal(Japanese, decoded.Text);
            Assert.Contains("UTF-8", decoded.EncodingName);
            Assert.Null(decoded.Warning);
        }

        [Fact]
        public void Utf8_without_bom_is_decoded()
        {
            var decoded = LyricsFile.Decode(new UTF8Encoding(false).GetBytes(Japanese));
            Assert.Equal(Japanese, decoded.Text);
            Assert.Equal("UTF-8", decoded.EncodingName);
            Assert.Null(decoded.Warning);
        }

        [Fact]
        public void Utf16_le_with_bom_is_decoded()
        {
            var decoded = LyricsFile.Decode(WithPreamble(new UnicodeEncoding(false, true), Japanese));
            Assert.Equal(Japanese, decoded.Text);
            Assert.Contains("UTF-16 LE", decoded.EncodingName);
        }

        [Fact]
        public void Utf16_be_with_bom_is_decoded()
        {
            var decoded = LyricsFile.Decode(WithPreamble(new UnicodeEncoding(true, true), Japanese));
            Assert.Equal(Japanese, decoded.Text);
            Assert.Contains("UTF-16 BE", decoded.EncodingName);
        }

        [Fact]
        public void Cp932_is_decoded_even_on_a_western_ansi_code_page()
        {
            var bytes = Encoding.GetEncoding(932).GetBytes(Japanese);
            var decoded = LyricsFile.Decode(bytes, Encoding.GetEncoding(1252));
            Assert.Equal(Japanese, decoded.Text);
            Assert.Contains("932", decoded.EncodingName);
            Assert.NotNull(decoded.Warning);
        }

        [Fact]
        public void Western_ansi_is_still_decoded_as_ansi()
        {
            var decoded = LyricsFile.Decode(Encoding.GetEncoding(1252).GetBytes(Western), Encoding.GetEncoding(1252));
            Assert.Equal(Western, decoded.Text);
            Assert.Contains("1252", decoded.EncodingName);
        }

        [Fact]
        public void Empty_file_is_an_empty_utf8_text()
        {
            var decoded = LyricsFile.Decode(Array.Empty<byte>());
            Assert.Equal("", decoded.Text);
            Assert.Equal("UTF-8", decoded.EncodingName);
        }
    }
}
