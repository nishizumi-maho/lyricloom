using System;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;
using MusicBeePlugin;

// Renders the karaoke scene to PNGs at given song times, without MusicBee.
// Usage: Preview.exe <lyrics.lrc> <out folder> <mode 0|1|2> <ms> [ms...]
//        Preview.exe strip <lyrics.lrc> <out.png> <start ms> [count] [every n frames]
internal static class Program
{
    private const double StepSeconds = 1.0 / 144.0;

    private sealed class Layer : FrameworkElement
    {
        private readonly KaraokeScene _scene; private readonly KaraokeScene.Layer _layer; public double T;
        public Layer(KaraokeScene s, KaraokeScene.Layer l)
        {
            _scene = s; _layer = l;
            TextOptions.SetTextHintingMode(this, TextHintingMode.Animated);
            TextOptions.SetTextFormattingMode(this, TextFormattingMode.Ideal);
            TextOptions.SetTextRenderingMode(this, TextRenderingMode.Grayscale);
            UseLayoutRounding = false;
            SnapsToDevicePixels = false;
        }
        protected override void OnRender(DrawingContext dc) => _scene.Render(_layer, dc, RenderSize, T);
    }

    [STAThread]
    private static int Main(string[] args)
    {
        var dic = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "MusicBee", "Plugins", "RomajiLyrics", "IpaDic");
        RomajiCore.Romanizer.UseFirstExistingDictionary(dic);
        return args.Length > 0 && args[0] == "strip" ? RenderStrip(args) : RenderFrames(args);
    }

    private static Settings MakeSettings(int mode) => new Settings
    {
        Japanese = (JapaneseMode)mode,
        Theme = Environment.GetEnvironmentVariable("PREVIEW_THEME") ?? "",
        RandomTheme = Environment.GetEnvironmentVariable("PREVIEW_RANDOM") == "1"
    };

    private static int RenderFrames(string[] args)
    {
        var settings = MakeSettings(int.Parse(args[2]));
        var lines = Timeline.Build(Lrc.Parse(File.ReadAllText(args[0])), 60000, settings.Japanese,
                                   s => RomajiCore.Romanizer.ToRomaji(s) ?? "");
        var scene = new KaraokeScene(settings);
        scene.SetSong(lines, "Sample Song   —   Test Artist", 60000);
        var size = new Size(1280, 720);
        Directory.CreateDirectory(args[1]);
        for (var i = 3; i < args.Length; i++)
        {
            var t = double.Parse(args[i]);
            // run the animation up to t so the path and fades have settled the way they would live
            for (var tt = Math.Max(0, t - 3000); tt <= t; tt += 16) scene.Update(0.016, tt, size);
            SavePng(RenderScene(scene, t, size), Path.Combine(args[1], $"frame_{t:000000}.png"));
        }
        return 0;
    }

    /// <summary>A horizontal strip of thumbnails, every n-th frame of a line change at 144 fps.</summary>
    private static int RenderStrip(string[] args)
    {
        var lrc = args[1];
        var output = args[2];
        var start = args.Length > 3 ? double.Parse(args[3]) : 0;
        var count = args.Length > 4 ? int.Parse(args[4]) : 16;
        var every = args.Length > 5 ? Math.Max(1, int.Parse(args[5])) : 4;
        var settings = MakeSettings(0);
        var lines = Timeline.Build(Lrc.Parse(File.ReadAllText(lrc)), 60000, settings.Japanese,
                                   s => RomajiCore.Romanizer.ToRomaji(s) ?? "");
        var scene = new KaraokeScene(settings);
        scene.SetSong(lines, "Sample Song   —   Test Artist", 60000);
        var size = new Size(1280, 720);

        for (var t = 0.0; t < start; t += StepSeconds * 1000.0) scene.Update(StepSeconds, t, size);
        var frames = new BitmapSource[count];
        var now = start;
        for (var k = 0; k < count * every; k++)
        {
            scene.Update(StepSeconds, now, size);
            if (k % every == 0) frames[k / every] = RenderScene(scene, now, size);
            now += StepSeconds * 1000.0;
        }

        const int thumbWidth = 320, thumbHeight = 180;
        var strip = new RenderTargetBitmap(thumbWidth * count, thumbHeight, 96, 96, PixelFormats.Pbgra32);
        var visual = new DrawingVisual();
        using (var dc = visual.RenderOpen())
        {
            for (var i = 0; i < frames.Length; i++)
                dc.DrawImage(frames[i], new Rect(i * thumbWidth, 0, thumbWidth, thumbHeight));
        }
        strip.Render(visual);
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output)));
        SavePng(strip, output);
        return 0;
    }

    private static RenderTargetBitmap RenderScene(KaraokeScene scene, double t, Size size)
    {
        var grid = new Grid { Width = size.Width, Height = size.Height };
        foreach (var kind in new[] { KaraokeScene.Layer.Sky, KaraokeScene.Layer.Glow, KaraokeScene.Layer.Text })
        {
            var l = new Layer(scene, kind) { T = t };
            if (kind == KaraokeScene.Layer.Glow) { l.Effect = new BlurEffect { Radius = 26 }; l.Opacity = 0.85; }
            grid.Children.Add(l);
        }
        if (Environment.GetEnvironmentVariable("PREVIEW_TRANSPORT") == "1")
        {
            var bar = new TransportBar(new PlayerControls(), scene.Accent);
            bar.Show(true);
            bar.BeginAnimation(UIElement.OpacityProperty, null);
            bar.Opacity = 1;
            bar.Update(t, 60000, true, 0.7f, false);
            grid.Children.Add(bar);
            scene.HideProgress = true;
        }
        grid.Measure(size);
        grid.Arrange(new Rect(size));
        var bmp = new RenderTargetBitmap((int)size.Width, (int)size.Height, 96, 96, PixelFormats.Pbgra32);
        bmp.Render(grid);
        return bmp;
    }

    private static void SavePng(BitmapSource bmp, string path)
    {
        var enc = new PngBitmapEncoder();
        enc.Frames.Add(BitmapFrame.Create(bmp));
        using (var f = File.Create(path)) enc.Save(f);
    }
}
