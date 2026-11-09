using System;
using System.Collections.Generic;
using System.IO;
using StarryKaraoke.Recorder;
using Xunit;

namespace StarryKaraoke.Tests
{
    /// <summary>R4-01: never record over an input, and never destroy the previous video before
    /// the replacement has been produced and swapped in.</summary>
    public class RecorderSafetyTests
    {
        [Fact]
        public void Output_equal_to_the_source_audio_is_refused()
        {
            using (var folder = new TempFolder())
            {
                var audio = folder.File("song.wav");
                File.WriteAllText(audio, "audio");
                var ex = Assert.Throws<ArgumentException>(() =>
                    OutputSafety.ValidateOutput(audio, audio, folder.File("song.lrc")));
                Assert.Contains("input", ex.Message, StringComparison.OrdinalIgnoreCase);
            }
        }

        [Fact]
        public void Output_that_resolves_to_an_input_is_refused()
        {
            using (var folder = new TempFolder())
            {
                var audio = folder.File("song.wav");
                File.WriteAllText(audio, "audio");
                var sub = Directory.CreateDirectory(folder.File("sub"));
                var target = Path.Combine(sub.FullName, "..", "sonG.WAV");
                Assert.Throws<ArgumentException>(() =>
                    OutputSafety.ValidateOutput(target, audio, folder.File("song.lrc")));
            }
        }

        [Fact]
        public void Output_equal_to_the_lyrics_or_settings_is_refused()
        {
            using (var folder = new TempFolder())
            {
                var lrc = folder.File("song.lrc");
                var settings = folder.File("settings.xml");
                File.WriteAllText(lrc, "[00:01.00]one");
                File.WriteAllText(settings, "<Settings/>");
                var target = folder.File("video.mp4");

                Assert.Throws<ArgumentException>(() =>
                    OutputSafety.ValidateOutput(lrc, folder.File("song.wav"), lrc, settings));
                Assert.Throws<ArgumentException>(() =>
                    OutputSafety.ValidateOutput(settings, folder.File("song.wav"), lrc, settings));
                Assert.Throws<ArgumentException>(() =>
                    OutputSafety.ValidateOutput(settings, folder.File("song.wav"), lrc, settings));
                OutputSafety.ValidateOutput(target, folder.File("song.wav"), lrc, settings);
            }
        }

        [Fact]
        public void A_job_whose_output_is_the_audio_is_refused_before_reading_or_deleting_anything()
        {
            using (var folder = new TempFolder())
            {
                var audio = folder.File("song.wav");
                var lrc = folder.File("song.lrc");
                var ffmpeg = folder.File("ffmpeg.exe");
                File.WriteAllText(audio, "audio");
                File.WriteAllText(lrc, "[00:01.00]one");
                File.WriteAllText(ffmpeg, "not really ffmpeg");
                var args = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                {
                    ["lrc"] = lrc,
                    ["audio"] = audio,
                    ["out"] = audio,
                    ["duration"] = "60000",
                    ["ffmpeg"] = ffmpeg,
                    ["title"] = "Test"
                };

                Assert.Throws<ArgumentException>(() => Job.FromArgs(args));
                Assert.True(File.Exists(audio));
                Assert.True(File.Exists(lrc));
            }
        }

        [Fact]
        public void A_failed_encode_leaves_the_existing_video_intact()
        {
            using (var folder = new TempFolder())
            {
                var target = folder.File("video.mp4");
                File.WriteAllText(target, "previous video");
                var partial = OutputSafety.PartialPath(target);   // the encoder never got this far
                Assert.Throws<IOException>(() => OutputSafety.Commit(partial, target));
                Assert.Equal("previous video", File.ReadAllText(target));
            }
        }

        [Fact]
        public void A_failed_replace_leaves_the_existing_video_intact()
        {
            using (var folder = new TempFolder())
            {
                var target = folder.File("video.mp4");
                File.WriteAllText(target, "previous video");
                var partial = OutputSafety.PartialPath(target);
                File.WriteAllText(partial, "new video");

                // Hold the target without delete sharing so the atomic replace has to fail.
                using (File.Open(target, FileMode.Open, FileAccess.Read, FileShare.None))
                    Assert.ThrowsAny<IOException>(() => OutputSafety.Commit(partial, target));

                Assert.Equal("previous video", File.ReadAllText(target));
            }
        }

        [Fact]
        public void Commit_replaces_the_target_and_removes_the_backup()
        {
            using (var folder = new TempFolder())
            {
                var target = folder.File("video.mp4");
                File.WriteAllText(target, "previous video");
                var partial = OutputSafety.PartialPath(target);
                File.WriteAllText(partial, "new video");

                OutputSafety.Commit(partial, target);

                Assert.Equal("new video", File.ReadAllText(target));
                Assert.False(File.Exists(partial));
                Assert.Empty(Directory.GetFiles(folder.Path, "video.mp4.bak-*"));
            }
        }

        [Fact]
        public void Commit_creates_a_target_that_did_not_exist()
        {
            using (var folder = new TempFolder())
            {
                var target = folder.File("video.mp4");
                var partial = OutputSafety.PartialPath(target);
                File.WriteAllText(partial, "new video");

                OutputSafety.Commit(partial, target);

                Assert.Equal("new video", File.ReadAllText(target));
                Assert.Empty(Directory.GetFiles(folder.Path, "video.mp4.bak-*"));
            }
        }

        [Fact]
        public void Partial_file_lives_in_the_target_folder()
        {
            using (var folder = new TempFolder())
            {
                var target = folder.File("video.mp4");
                var partial = OutputSafety.PartialPath(target);
                Assert.Equal(Path.GetFullPath(folder.Path), Path.GetDirectoryName(partial));
                Assert.Contains(".part.mp4", Path.GetFileName(partial));
            }
        }

        private class ReplaceFails : FileOperations
        {
            private readonly System.Exception _error;
            public ReplaceFails(System.Exception error) { _error = error; }
            public override void Replace(string source, string destination, string backup) => throw _error;
        }

        [Theory]
        [MemberData(nameof(UnsupportedReplaceErrors))]
        public void FR_C_03_commit_falls_back_to_moves_when_file_replace_is_not_supported(System.Exception error)
        {
            using (var folder = new TempFolder())
            {
                var target = folder.File("video.mp4");
                File.WriteAllText(target, "previous video");
                var partial = OutputSafety.PartialPath(target);
                File.WriteAllText(partial, "new video");

                OutputSafety.Commit(partial, target, new ReplaceFails(error));

                Assert.Equal("new video", File.ReadAllText(target));
                Assert.False(File.Exists(partial));
                Assert.Empty(Directory.GetFiles(folder.Path, "video.mp4.bak-*"));
            }
        }

        public static TheoryData<System.Exception> UnsupportedReplaceErrors => new TheoryData<System.Exception>
        {
            new PlatformNotSupportedException("ReplaceFile is not supported on this volume"),
            new IOException("The parameter is incorrect")
        };

        private sealed class MoveFails : FileOperations
        {
            private readonly string _partial;
            public MoveFails(string partial) { _partial = partial; }
            public override void Replace(string source, string destination, string backup) =>
                throw new PlatformNotSupportedException("no ReplaceFile");
            public override void Move(string source, string destination)
            {
                if (string.Equals(source, _partial, System.StringComparison.OrdinalIgnoreCase))
                    throw new IOException("the partial file could not be moved");
                base.Move(source, destination);
            }
        }

        [Fact]
        public void FR_C_03_a_failed_fallback_move_restores_the_previous_video()
        {
            using (var folder = new TempFolder())
            {
                var target = folder.File("video.mp4");
                File.WriteAllText(target, "previous video");
                var partial = OutputSafety.PartialPath(target);
                File.WriteAllText(partial, "new video");

                Assert.Throws<IOException>(() => OutputSafety.Commit(partial, target, new MoveFails(Path.GetFullPath(partial))));

                Assert.Equal("previous video", File.ReadAllText(target));
                Assert.True(File.Exists(partial));
            }
        }
    }
}
