using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using MusicBeePlugin;


namespace StarryKaraoke.Recorder
{
    /// <summary>
    /// Renders the song in contiguous segments on several STA threads at once (WPF's offscreen rendering is
    /// software only, so one thread is slow). Each segment is encoded by its own ffmpeg into a part file;
    /// the parts are then joined without re-encoding and the song's audio is added.
    /// The glow is drawn at a quarter of the size and blurred with a fast box blur instead of WPF's
    /// BlurEffect, which in software is most of a frame's cost.
    /// </summary>
    internal sealed class Renderer
    {
        private readonly Job _job;
        private volatile bool _cancel;
        private volatile bool _userCancel;
        private volatile JobObject _jobObject;
        private int _framesDone;
        public event Action<int, int> Progress;     // frames done, total
        public event Action<string> Status;
        public event Action<Exception> Finished;    // null on success

        public Renderer(Job job) { _job = job; }

        /// <summary>Asks every phase to stop at its next check: encoder probe, segment rendering,
        /// the final join and the commit. The join checks between short waits, so Cancel is not held
        /// until a minutes-long ffmpeg call finishes.</summary>
        public void Cancel() { _userCancel = true; _cancel = true; }

        /// <summary>Cancel and terminate the ffmpeg processes in the job object (Force stop).</summary>
        public void Kill()
        {
            _userCancel = true;
            _cancel = true;
            try { _jobObject?.KillAll(); } catch (Exception) { }
        }

        public void Start() => new Thread(Run) { IsBackground = true, Name = "Starry Karaoke recorder" }.Start();

        private void Run()
        {
            string work = null;
            string partial = null;
            try
            {
                work = RecorderTemp.CreateRunFolder();
                partial = OutputSafety.PartialPath(_job.Out);
                _jobObject = JobObject.Create();
                // Defence in depth: Job.FromArgs already refused this, but never let a manually
                // constructed Job write over the audio or any other input it reads.
                OutputSafety.ValidateOutput(_job.Out, _job.Audio, _job.Lrc, _job.SettingsPath, _job.Ffmpeg);
                if (!string.IsNullOrEmpty(_job.Dict)) RomajiCore.Romanizer.UseFirstExistingDictionary(_job.Dict);
                var s = _job.Settings;
                var lines = Timeline.Build(Lrc.Parse(_job.Lyrics), _job.DurationMs, s.Japanese,
                                           x => { try { return RomajiCore.Romanizer.ToRomaji(x) ?? ""; } catch (Exception) { return ""; } });
                ThrowIfCancelled();

                var fps = _job.Fps;
                // audio time the video starts at: 0, or just before the first sung line
                var startMs = 0.0;
                if (s.VideoSkipIntro && Timeline.IntroSkipTarget(lines, s.IntroLeadMs) is double skip)
                    startMs = Math.Max(0, skip + s.LyricsOffsetMs);
                startMs = Math.Min(startMs, Math.Max(0, _job.DurationMs - 1000));
                var total = (int)Math.Ceiling((_job.DurationMs - startMs) / 1000.0 * fps);
                if (total <= 0) throw new ArgumentException("The video would have no frames. Check the intro-skip setting and the song duration.");

                Status?.Invoke("Testing the video encoder...");
                var encoder = PickEncoder();
                var workers = WorkersFor(encoder, total, fps, Environment.ProcessorCount);
                Status?.Invoke($"Rendering in {workers} parts ({EncoderName(encoder)})...");

                var bounds = Enumerable.Range(0, workers + 1).Select(k => (int)((long)total * k / workers)).ToArray();
                var parts = Enumerable.Range(0, workers).Select(k => Path.Combine(work, $"part{k:00}.mp4")).ToArray();
                var errors = new Exception[workers];
                var threads = Enumerable.Range(0, workers).Select(k =>
                {
                    var th = new Thread(() =>
                    {
                        try { RenderSegment(lines, startMs, bounds[k], bounds[k + 1], parts[k], encoder, total); }
                        catch (Exception e) { errors[k] = e; _cancel = true; }
                    }) { IsBackground = true, Name = "segment " + k };
                    th.SetApartmentState(ApartmentState.STA);
                    th.Start();
                    return th;
                }).ToList();
                foreach (var th in threads) th.Join();

                if (_userCancel) throw new OperationCanceledException();
                var failed = errors.FirstOrDefault(e => e != null && !(e is OperationCanceledException));
                if (failed != null) throw failed;
                if (_cancel) throw new OperationCanceledException();

                Status?.Invoke("Joining the parts with the audio...");
                var list = Path.Combine(work, "parts.txt");
                File.WriteAllLines(list, parts.Select(p => "file '" + p.Replace("'", "'\\''") + "'"));
                var seek = startMs > 0 ? "-ss " + (startMs / 1000).ToString("0.000", CultureInfo.InvariantCulture) + " " : "";
                RunFfmpeg($"-y -loglevel error -f concat -safe 0 -i {Q(list)} {seek}-i {Q(_job.Audio)} -map 0:v:0 -map 1:a:0 " +
                          $"-c:v copy -c:a aac -b:a 256k -shortest -movflags +faststart -f mp4 {Q(partial)}");
                ThrowIfCancelled();

                // Never delete the target first: the partial file is complete and ffmpeg has exited,
                // then Commit swaps it in, keeping the old file until the swap succeeded.
                OutputSafety.Commit(partial, _job.Out);
                Finished?.Invoke(null);
            }
            catch (OperationCanceledException)
            {
                Finished?.Invoke(new OperationCanceledException("Recording cancelled."));
            }
            catch (Exception e)
            {
                Finished?.Invoke(e);
            }
            finally
            {
                try { if (File.Exists(partial)) File.Delete(partial); } catch (Exception) { }
                RecorderTemp.DeleteRunFolder(work);
                var jobObject = _jobObject;
                _jobObject = null;
                jobObject?.Dispose();
            }
        }

        private void ThrowIfCancelled()
        {
            if (_cancel || _userCancel) throw new OperationCanceledException();
        }

        /// <summary>At most two parts for a hardware encoder (driver session limits), and at most half
        /// the logical processors (minimum 1, maximum 8) for software encoding (R4-12).</summary>
        internal static int WorkersFor(string encoder, int totalFrames, int fps, int processorCount)
        {
            var hardware = !string.IsNullOrEmpty(encoder) &&
                           !encoder.TrimStart().StartsWith("libx264", StringComparison.OrdinalIgnoreCase);
            var half = Math.Max(1, Math.Min(8, Math.Max(0, processorCount) / 2));
            var cap = hardware ? Math.Min(2, half) : half;
            var byLength = fps > 0 ? Math.Max(1, totalFrames / (fps * 4)) : 1;
            return Math.Max(1, Math.Min(cap, byLength));
        }

        private static string Q(string p) => "\"" + p.Replace("\"", "\\\"") + "\"";

        // ---------------------------------------------------------------- encoder

        private string PickEncoder()
        {
            foreach (var enc in new[] { "h264_amf -quality quality -rc cqp -qp_i 18 -qp_p 20 -qp_b 22",
                                        "h264_nvenc -preset p5 -rc vbr -cq 19 -b:v 0",
                                        "h264_qsv -global_quality 20" })
            {
                try
                {
                    ThrowIfCancelled();
                    RunFfmpeg($"-y -loglevel error -f lavfi -i color=black:s={_job.Width}x{_job.Height}:d=0.2 -c:v {enc} -pix_fmt yuv420p -f null -");
                    return enc;
                }
                catch (OperationCanceledException) { throw; }
                catch (Exception) { }
            }
            return "libx264 -preset fast -crf 18";
        }

        private static string EncoderName(string enc) => enc.Split(' ')[0].Replace("h264_amf", "GPU AMD").Replace("h264_nvenc", "GPU NVIDIA").Replace("h264_qsv", "GPU Intel").Replace("libx264", "CPU");

        /// <summary>Runs ffmpeg while remaining cancellable. stderr is read asynchronously so the
        /// process cannot block on a full pipe; WaitForExit is polled so Cancel kills it promptly.</summary>
        private void RunFfmpeg(string args)
        {
            ThrowIfCancelled();
            using (var p = new Process
            {
                StartInfo = new ProcessStartInfo(_job.Ffmpeg, args)
                {
                    UseShellExecute = false, RedirectStandardError = true, CreateNoWindow = true
                }
            })
            {
                if (!p.Start()) throw new Exception("Could not start ffmpeg: " + _job.Ffmpeg);
                _jobObject?.Assign(p);

                var err = new StringBuilder();
                p.ErrorDataReceived += (o, e) =>
                {
                    if (e.Data == null) return;
                    lock (err) { if (err.Length < 8000) err.AppendLine(e.Data); }
                };
                p.BeginErrorReadLine();
                try
                {
                    while (!p.WaitForExit(100))
                    {
                        if (_cancel)
                        {
                            TryKill(p);
                            throw new OperationCanceledException();
                        }
                    }
                    p.WaitForExit();   // flush the asynchronous stderr handlers
                }
                finally
                {
                    if (_cancel) TryKill(p);
                }

                ThrowIfCancelled();
                string text;
                lock (err) text = err.ToString();
                if (p.ExitCode != 0) throw new Exception("ffmpeg failed (code " + p.ExitCode + "):\n" + text.Trim());
            }
        }

        private static void TryKill(Process p)
        {
            try
            {
                if (!p.HasExited) p.Kill();
                p.WaitForExit(2000);
            }
            catch (Exception) { }
        }

        // ---------------------------------------------------------------- one segment

        private void RenderSegment(List<KaraokeLine> lines, double startMs, int from, int to, string output, string encoder, int total)
        {
            var s = _job.Settings;
            var fps = _job.Fps;
            int w = _job.Width, h = _job.Height;
            var size = new Size(w, h);
            var scene = new KaraokeScene(s);
            scene.SetSong(lines, _job.Title, _job.DurationMs);

            double LyricTime(int frame) => startMs + frame * 1000.0 / fps - s.LyricsOffsetMs;

            // warm up: run the animation over the seconds before this segment so the scroll and fades are
            // exactly where they would be had the video been rendered in one go
            var warm = Math.Max(0, from - fps * 4);
            scene.Update(1.0, LyricTime(warm), size);
            for (var i = warm; i < from; i++)
            {
                if (_cancel) throw new OperationCanceledException();
                scene.Update(1.0 / fps, LyricTime(i), size);
            }

            var psi = new ProcessStartInfo(_job.Ffmpeg)
            {
                Arguments = $"-y -loglevel error -f rawvideo -pix_fmt bgra -s {w}x{h} -r {fps} -i - " +
                            $"-c:v {encoder} -pix_fmt yuv420p -an -f mp4 {Q(output)}",
                UseShellExecute = false, RedirectStandardInput = true, RedirectStandardError = true, CreateNoWindow = true
            };
            var ff = Process.Start(psi);
            if (ff == null) throw new Exception("Could not start ffmpeg: " + _job.Ffmpeg);
            _jobObject?.Assign(ff);
            var ffErr = new StringBuilder();
            ff.ErrorDataReceived += (o, e) =>
            {
                if (e.Data == null) return;
                lock (ffErr) { if (ffErr.Length < 4000) ffErr.AppendLine(e.Data); }
            };
            ff.BeginErrorReadLine();

            var gw = Math.Max(2, w / 4); var gh = Math.Max(2, h / 4);
            var glowRtb = new RenderTargetBitmap(gw, gh, 96, 96, PixelFormats.Pbgra32);
            var glowPx = new byte[gw * gh * 4];
            var tmp = new byte[glowPx.Length];
            var frameRtb = new RenderTargetBitmap(w, h, 96, 96, PixelFormats.Pbgra32);
            var framePx = new byte[w * h * 4];
            var blurRadius = Math.Max(2, (int)Math.Round(Math.Max(8, Math.Min(40, h / 26.0)) / 4 / 1.6));
            var stdin = ff.StandardInput.BaseStream;
            try
            {
                for (var i = from; i < to; i++)
                {
                    if (_cancel) throw new OperationCanceledException();
                    var t = LyricTime(i);
                    scene.Update(1.0 / fps, t, size);
                    scene.WallSeconds = (startMs + i * 1000.0 / fps) / 1000.0;

                    BitmapSource glow = null;
                    if (s.Glow)
                    {
                        var gv = new DrawingVisual();
                        TextOptions.SetTextHintingMode(gv, TextHintingMode.Animated);
                        TextOptions.SetTextFormattingMode(gv, TextFormattingMode.Ideal);
                        TextOptions.SetTextRenderingMode(gv, TextRenderingMode.Grayscale);
                        using (var dc = gv.RenderOpen())
                        {
                            dc.PushTransform(new ScaleTransform((double)gw / w, (double)gh / h));
                            scene.Render(KaraokeScene.Layer.Glow, dc, size, t);
                            dc.Pop();
                        }
                        glowRtb.Clear();
                        glowRtb.Render(gv);
                        glowRtb.CopyPixels(glowPx, gw * 4, 0);
                        BoxBlur.Blur(glowPx, tmp, gw, gh, blurRadius, 3);
                        glow = BitmapSource.Create(gw, gh, 96, 96, PixelFormats.Pbgra32, null, glowPx, gw * 4);
                    }

                    var fv = new DrawingVisual();
                    TextOptions.SetTextHintingMode(fv, TextHintingMode.Animated);
                    TextOptions.SetTextFormattingMode(fv, TextFormattingMode.Ideal);
                    TextOptions.SetTextRenderingMode(fv, TextRenderingMode.Grayscale);
                    using (var dc = fv.RenderOpen())
                    {
                        scene.Render(KaraokeScene.Layer.Sky, dc, size, t);
                        if (glow != null)
                        {
                            dc.PushOpacity(0.85);
                            dc.DrawImage(glow, new Rect(0, 0, w, h));
                            dc.Pop();
                        }
                        scene.Render(KaraokeScene.Layer.Text, dc, size, t);
                    }
                    frameRtb.Clear();
                    frameRtb.Render(fv);
                    frameRtb.CopyPixels(framePx, w * 4, 0);
                    stdin.Write(framePx, 0, framePx.Length);

                    var done = Interlocked.Increment(ref _framesDone);
                    if (done % 10 == 0 || done == total) Progress?.Invoke(done, total);
                }
                stdin.Close();
                ff.WaitForExit();
                ThrowIfCancelled();
                if (ff.ExitCode != 0)
                {
                    string text;
                    lock (ffErr) text = ffErr.ToString();
                    throw new Exception("ffmpeg failed (code " + ff.ExitCode + "):\n" + text.Trim());
                }
            }
            catch (OperationCanceledException)
            {
                try { if (!ff.HasExited) ff.Kill(); } catch (Exception) { }
                throw;
            }
            catch (Exception)
            {
                try { if (!ff.HasExited) ff.Kill(); } catch (Exception) { }
                if (_userCancel) throw new OperationCanceledException();
                throw;
            }
            finally
            {
                try { stdin.Dispose(); } catch (Exception) { }
                try { ff.Dispose(); } catch (Exception) { }
            }
        }
    }

    /// <summary>Repeated box blur on premultiplied BGRA (three passes look like a Gaussian).</summary>
    internal static class BoxBlur
    {
        public static void Blur(byte[] px, byte[] tmp, int w, int h, int r, int passes)
        {
            for (var p = 0; p < passes; p++)
            {
                Pass(px, tmp, w, h, r, true);
                Pass(tmp, px, w, h, r, false);
            }
        }

        private static void Pass(byte[] src, byte[] dst, int w, int h, int r, bool horizontal)
        {
            int lines = horizontal ? h : w, len = horizontal ? w : h;
            int step = horizontal ? 4 : w * 4;
            var div = 2 * r + 1;
            for (var l = 0; l < lines; l++)
            {
                var start = horizontal ? l * w * 4 : l * 4;
                for (var c = 0; c < 4; c++)
                {
                    var sum = 0;
                    for (var k = -r; k <= r; k++) sum += src[start + Clamp(k, len) * step + c];
                    for (var i = 0; i < len; i++)
                    {
                        dst[start + i * step + c] = (byte)(sum / div);
                        sum += src[start + Clamp(i + r + 1, len) * step + c] - src[start + Clamp(i - r, len) * step + c];
                    }
                }
            }
        }

        private static int Clamp(int i, int len) => i < 0 ? 0 : i >= len ? len - 1 : i;
    }
}
