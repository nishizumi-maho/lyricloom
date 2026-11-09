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
internal static class Program
{
    private sealed class Layer : FrameworkElement
    {
        private readonly KaraokeScene _scene; private readonly KaraokeScene.Layer _layer; public double T;
        public Layer(KaraokeScene s, KaraokeScene.Layer l) { _scene = s; _layer = l; }
        protected override void OnRender(DrawingContext dc) => _scene.Render(_layer, dc, RenderSize, T);
    }

    [STAThread]
    private static int Main(string[] args)
    {
        var dic = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "MusicBee", "Plugins", "RomajiLyrics", "IpaDic");
        RomajiCore.Romanizer.UseFirstExistingDictionary(dic);
        var settings = new Settings
        {
            Japanese = (JapaneseMode)int.Parse(args[2]),
            Theme = Environment.GetEnvironmentVariable("PREVIEW_THEME") ?? "",
            RandomTheme = Environment.GetEnvironmentVariable("PREVIEW_RANDOM") == "1"
        };
        var lines = Timeline.Build(Lrc.Parse(File.ReadAllText(args[0])), 60000, settings.Japanese,
                                   s => RomajiCore.Romanizer.ToRomaji(s) ?? "");
        var scene = new KaraokeScene(settings);
        scene.SetSong(lines, "Sample Song   —   Test Artist", 60000);
        var size = new Size(1280, 720);
        Directory.CreateDirectory(args[1]);
        for (var i = 3; i < args.Length; i++)
        {
            var t = double.Parse(args[i]);
            // run the animation up to t so springs and fades have settled the way they would live
            for (var tt = Math.Max(0, t - 3000); tt <= t; tt += 16) scene.Update(0.016, tt, size);
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
            var enc = new PngBitmapEncoder();
            enc.Frames.Add(BitmapFrame.Create(bmp));
            using (var f = File.Create(Path.Combine(args[1], $"frame_{t:000000}.png"))) enc.Save(f);
        }
        return 0;
    }
}
