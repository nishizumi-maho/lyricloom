using System;
using System.Globalization;
using System.IO;
using System.Text;
using System.Windows;
using MusicBeePlugin;

/// <summary>Drives the real KaraokeScene offscreen at 144 frames/s through a 20-second fixture with a
/// seek in the middle, writes the per-frame scroll/scale series to .work-smooth\scroll-series.csv,
/// and checks the continuity bounds from the smooth-motion design.</summary>
internal static class Program
{
    private const double Fps = 144.0;
    private const double FrameMs = 1000.0 / Fps;
    private const double SeekAtMs = 8000.0;
    private const double SeekToMs = 13000.0;

    [STAThread]
    private static int Main(string[] args)
    {
        var root = FindWorktreeRoot();
        var output = args.Length > 0 ? args[0] : Path.Combine(root, ".work-smooth");
        Directory.CreateDirectory(output);
        var lrcPath = Path.Combine(output, "frame-series.lrc");
        File.WriteAllText(lrcPath, FixtureLrc());

        var settings = new Settings
        {
            ShowStars = false, ShowProgress = false, ShowHeader = false,
            LineBursts = false, Glow = false, GrowCurrentLine = true
        };
        var lines = Timeline.Build(Lrc.Parse(File.ReadAllText(lrcPath)), 22000, JapaneseMode.RomajiOnly, null);
        var scene = new KaraokeScene(settings);
        scene.SetSong(lines, "Frame series", 22000);
        var size = new Size(1280, 720);

        var csv = new StringBuilder();
        csv.AppendLine("frame,real_ms,song_ms,scroll,scale,path,residual");
        var frames = (int)(20 * Fps);
        var seeked = false;
        var seekFrame = -1;
        var songTime = 0.0;
        double previous = double.NaN, previousVelocity = 0, maxStep = 0, maxVelocityJump = 0;
        double pathMaxStep = 0, pathMaxVelocityJump = 0;
        var settleFrames = -1;
        var overshoot = 0.0;
        double residualSign = 0;
        var seekJumps = true;
        for (var frame = 0; frame <= frames; frame++)
        {
            var real = frame * FrameMs;
            if (!seeked && real >= SeekAtMs)
            {
                // A jump in song time, exactly like a player seek between two frames.
                songTime = SeekToMs;
                seeked = true;
                seekFrame = frame;
            }
            scene.Update(1.0 / Fps, songTime, size);
            var scroll = scene.ScrollOffset;
            var residual = scene.ScrollResidual;
            var scale = scene.LineScale(scene.CurrentLine(songTime));
            var path = scroll - residual;
            csv.Append(frame.ToString(CultureInfo.InvariantCulture)).Append(',')
               .Append(real.ToString("0.###", CultureInfo.InvariantCulture)).Append(',')
               .Append(songTime.ToString("0.###", CultureInfo.InvariantCulture)).Append(',')
               .Append(scroll.ToString("0.#####", CultureInfo.InvariantCulture)).Append(',')
               .Append(scale.ToString("0.######", CultureInfo.InvariantCulture)).Append(',')
               .Append(path.ToString("0.#####", CultureInfo.InvariantCulture)).Append(',')
               .Append(residual.ToString("0.#####", CultureInfo.InvariantCulture)).AppendLine();

            if (!double.IsNaN(previous))
            {
                var step = Math.Abs(scroll - previous);
                maxStep = Math.Max(maxStep, step);
                var velocity = (scroll - previous) / (FrameMs / 1000.0);
                var jump = frame > 1 ? Math.Abs(velocity - previousVelocity) : 0;
                maxVelocityJump = Math.Max(maxVelocityJump, jump);
                if (songTime < SeekAtMs)
                {
                    pathMaxStep = Math.Max(pathMaxStep, step);
                    pathMaxVelocityJump = Math.Max(pathMaxVelocityJump, jump);
                }
                else if (frame == seekFrame && step > 0.000001)
                {
                    seekJumps = false;
                }
                previousVelocity = velocity;
            }
            previous = scroll;

            if (seeked && frame >= seekFrame)
            {
                if (residualSign == 0 && Math.Abs(residual) > 0.001) residualSign = Math.Sign(residual);
                if (residualSign != 0 && Math.Sign(residual) == -residualSign)
                    overshoot = Math.Max(overshoot, Math.Abs(residual));
                if (settleFrames < 0 && Math.Abs(residual) < 2) settleFrames = frame - seekFrame;
            }
            songTime += FrameMs;
        }

        var csvPath = Path.Combine(output, "scroll-series.csv");
        File.WriteAllText(csvPath, csv.ToString());
        var settle = settleFrames < 0 ? double.PositiveInfinity : settleFrames / Fps;
        Console.WriteLine($"CSV: {csvPath}");
        Console.WriteLine($"frames={frames + 1} peakVelocity={scene.ScrollPeakVelocity:0.###} px/s " +
                          $"peakAcceleration={scene.ScrollPeakAcceleration:0.###} px/s2");
        Console.WriteLine($"maxStep={maxStep:0.#####} px maxVelocityJump={maxVelocityJump:0.####} px/s " +
                          $"settle={settle:0.###} s overshoot={overshoot:0.####} px");
        Console.WriteLine($"pathOnly maxStep={pathMaxStep:0.#####} px maxVelocityJump={pathMaxVelocityJump:0.####} px/s");

        var failures = 0;
        var stepBound = scene.ScrollPeakVelocity / Fps * 1.02 + 0.001;
        if (pathMaxStep > stepBound)
        {
            Console.Error.WriteLine($"FAIL: path max step {pathMaxStep:0.#####} px exceeds {stepBound:0.#####} px");
            failures++;
        }
        var jumpBound = scene.ScrollPeakAcceleration / Fps * 1.05 + 0.1;
        if (pathMaxVelocityJump > jumpBound)
        {
            Console.Error.WriteLine($"FAIL: path velocity jump {pathMaxVelocityJump:0.####} px/s exceeds {jumpBound:0.####} px/s");
            failures++;
        }
        if (!seekJumps)
        {
            Console.Error.WriteLine("FAIL: the seek frame moved the scroll position");
            failures++;
        }
        if (settle > 0.4)
        {
            Console.Error.WriteLine($"FAIL: seek residual settled after {settle:0.###} s");
            failures++;
        }
        if (overshoot > 0.01)
        {
            Console.Error.WriteLine($"FAIL: seek residual overshot by {overshoot:0.####} px");
            failures++;
        }
        return failures == 0 ? 0 : 1;
    }

    private static string FixtureLrc()
    {
        var text = new StringBuilder();
        for (var i = 0; i < 10; i++)
            text.Append($"[00:{i * 2 + 1:00}.00]line {i + 1} of a made up frame-series song\n");
        return text.ToString();
    }

    private static string FindWorktreeRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir != null)
        {
            if (File.Exists(Path.Combine(dir.FullName, "musicbee.sln")))
                return dir.Parent?.FullName ?? dir.FullName;
            dir = dir.Parent;
        }
        return Directory.GetCurrentDirectory();
    }
}
