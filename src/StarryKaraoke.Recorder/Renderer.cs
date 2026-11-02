using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
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
        private int _framesDone;
        public event Action<int, int> Progress;     // frames done, total
        public event Action<string> Status;
        public event Action<Exception> Finished;    // null on success

        public Renderer(Job job) { _job = job; }
        public void Cancel() { _userCancel = true; _cancel = true; }

        public void Start() => new Thread(Run) { IsBackground = true, Name = "Starry Karaoke recorder" }.Start();

        private void Run()
        {
            var work = Path.Combine(Path.GetTempPath(), "StarryKaraoke", "rec-" + Guid.NewGuid().ToString("N").Substring(0, 8));
            var partial = _job.Out + ".part.mp4";
            try
            {
                Directory.CreateDirectory(work);
                if (!string.IsNullOrEmpty(_job.Dict)) RomajiCore.Romanizer.UseFirstExistingDictionary(_job.Dict);
                var s = _job.Settings;
                var lines = Timeline.Build(Lrc.Parse(File.ReadAllText(_job.Lrc)), _job.DurationMs, s.Japanese,
                                           x => { try { return RomajiCore.Romanizer.ToRomaji(x) ?? ""; } catch (Exception) { return ""; } });

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
                var workers = Math.Max(1, Math.Min(Math.Min(8, Environment.ProcessorCount / 3), total / (fps * 4)));
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
                if (File.Exists(_job.Out)) File.Delete(_job.Out);
                File.Move(partial, _job.Out);
                Finished?.Invoke(null);
            }
            catch (Exception e)
            {
                try { if (File.Exists(partial)) File.Delete(partial); } catch (Exception) { }
                Finished?.Invoke(e);
            }
            finally
            {
                try { Directory.Delete(work, true); } catch (Exception) { }
            }
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
                    RunFfmpeg($"-y -loglevel error -f lavfi -i color=black:s={_job.Width}x{_job.Height}:d=0.2 -c:v {enc} -pix_fmt yuv420p -f null -");
                    return enc;
                }
                catch (Exception) { }
            }
            return "libx264 -preset fast -crf 18";
        }

        private static string EncoderName(string enc) => enc.Split(' ')[0].Replace("h264_amf", "GPU AMD").Replace("h264_nvenc", "GPU NVIDIA").Replace("h264_qsv", "GPU Intel").Replace("libx264", "CPU");

        private void RunFfmpeg(string args)
        {
            var p = Process.Start(new ProcessStartInfo(_job.Ffmpeg, args)
            {
                UseShellExecute = false, RedirectStandardError = true, CreateNoWindow = true
            });
            var err = p.StandardError.ReadToEnd();
            p.WaitForExit();
            if (p.ExitCode != 0) throw new Exception("ffmpeg failed (code " + p.ExitCode + "):\n" + err.Trim());
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
            for (var i = warm; i < from; i++) scene.Update(1.0 / fps, LyricTime(i), size);

            var psi = new ProcessStartInfo(_job.Ffmpeg)
            {
                Arguments = $"-y -loglevel error -f rawvideo -pix_fmt bgra -s {w}x{h} -r {fps} -i - " +
                            $"-c:v {encoder} -pix_fmt yuv420p -an -f mp4 {Q(output)}",
                UseShellExecute = false, RedirectStandardInput = true, RedirectStandardError = true, CreateNoWindow = true
            };
            var ff = Process.Start(psi);
            var ffErr = "";
            ff.ErrorDataReceived += (o, e) => { if (e.Data != null && ffErr.Length < 4000) ffErr += e.Data + "\n"; };
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
                if (ff.ExitCode != 0) throw new Exception("ffmpeg failed (code " + ff.ExitCode + "):\n" + ffErr.Trim());
            }
            catch
            {
                try { if (!ff.HasExited) ff.Kill(); } catch (Exception) { }
                throw;
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
