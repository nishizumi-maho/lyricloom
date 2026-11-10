using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace MusicBeePlugin
{
    /// <summary>What the transport bar can ask the player to do.</summary>
    internal sealed class PlayerControls
    {
        public Action PlayPause, Previous, Next;
        public Action<double> Seek;          // ms
        public Action<float> SetVolume;      // 0..1
        public Action<bool> SetMute;
    }

    /// <summary>Play/pause, ±10 s, previous/next and a seek bar along the bottom of the karaoke window.
    /// It fades in when the mouse comes near the bottom and fades out a moment after the mouse stops.</summary>
    internal sealed class TransportBar : Border
    {
        private const double HideAfterSec = 2.5;
        private readonly PlayerControls _controls;
        private readonly SeekBar _seek;
        private readonly TextBlock _played = TimeText(), _length = TimeText();
        private readonly Button _playPause, _mute;
        private readonly Slider _volume;
        private readonly TextBlock _offsetText;
        private readonly System.Windows.Threading.DispatcherTimer _hideTimer;
        private readonly Action<Exception> _log;
        private double _positionMs, _durationMs;
        private bool _shown, _playing, _muteState;
        private bool _updatingVolume;
        private string _offsetShown = "";

        public TransportBar(PlayerControls controls, Color accent, Action<Exception> log = null)
        {
            _controls = controls;
            _log = log;
            VerticalAlignment = VerticalAlignment.Bottom;
            Padding = new Thickness(28, 26, 28, 18);
            Opacity = 0;
            IsHitTestVisible = false;
            Background = new LinearGradientBrush(Color.FromArgb(0, 6, 6, 16), Color.FromArgb(215, 6, 6, 16), 90);

            _seek = new SeekBar(accent) { Height = 22, Margin = new Thickness(10, 0, 10, 0) };
            _seek.SeekRequested += f => Safe.Run(() => { if (_durationMs > 0) _controls.Seek?.Invoke(f * _durationMs); }, _log);
            _volume = new Slider
            {
                Minimum = 0, Maximum = 1, Value = 1, Width = 72, Height = 22, Focusable = false,
                IsMoveToPointEnabled = true, ToolTip = Strings.VolumeTip, VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(2, 0, 2, 0)
            };
            _volume.ValueChanged += (s, e) => Safe.Run(() =>
            {
                if (!_updatingVolume) _controls.SetVolume?.Invoke((float)e.NewValue);
            }, _log);
            _mute = IconButton("\uE767", Strings.MuteTip, 13, () => _controls.SetMute?.Invoke(!_muteState), _log);
            _offsetText = new TextBlock
            {
                Text = "", Foreground = new SolidColorBrush(Color.FromRgb(255, 206, 92)), FontSize = 12,
                VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(4, 0, 8, 0),
                ToolTip = Strings.SongDelayTip
            };
            var volumeRow = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            volumeRow.Children.Add(_offsetText);
            volumeRow.Children.Add(_mute);
            volumeRow.Children.Add(_volume);

            var seekRow = new DockPanel();
            DockPanel.SetDock(_played, Dock.Left);
            DockPanel.SetDock(_length, Dock.Right);
            seekRow.Children.Add(_played);
            seekRow.Children.Add(_length);
            DockPanel.SetDock(volumeRow, Dock.Right);
            seekRow.Children.Add(volumeRow);
            seekRow.Children.Add(_seek);

            _playPause = IconButton("", Strings.PlayPauseTip, 30, () => _controls.PlayPause?.Invoke(), _log);
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0, 6, 0, 0) };
            buttons.Children.Add(IconButton("", Strings.PreviousTrackTip, 20, () => _controls.Previous?.Invoke(), _log));
            buttons.Children.Add(IconButton("", Strings.BackTenSecondsTip, 20, () => Jump(-10000), _log));
            buttons.Children.Add(_playPause);
            buttons.Children.Add(IconButton("", Strings.ForwardTenSecondsTip, 20, () => Jump(10000), _log));
            buttons.Children.Add(IconButton("", Strings.NextTrackTip, 20, () => _controls.Next?.Invoke(), _log));

            var stack = new StackPanel();
            stack.Children.Add(seekRow);
            stack.Children.Add(buttons);
            Child = stack;

            _hideTimer = new System.Windows.Threading.DispatcherTimer { Interval = TimeSpan.FromSeconds(HideAfterSec) };
            _hideTimer.Tick += (s, e) => Safe.Run(() => { if (!IsMouseOver && !_seek.Dragging) Show(false); }, _log);
        }

        public bool IsShown => _shown;

        /// <summary>The seek fill follows the current theme's accent colour.</summary>
        public void SetAccent(Color accent) => _seek.SetAccent(accent);

        public void Jump(double deltaMs)
        {
            if (_durationMs <= 0) return;
            _controls.Seek?.Invoke(Math.Max(0, Math.Min(_durationMs - 500, _positionMs + deltaMs)));
        }

        /// <summary>The per-song delay is shown next to the volume controls whenever it is not zero.</summary>
        public void SetSongOffset(int offsetMs)
        {
            var text = offsetMs == 0 ? "" : Strings.TransportDelayLabel(offsetMs);
            if (text == _offsetShown) return;
            _offsetShown = text;
            _offsetText.Text = text;
        }

        /// <summary>Called by the window every frame with the player's state.</summary>
        public void Update(double positionMs, double durationMs, bool playing, float volume, bool mute,
                           int songOffsetMs = 0)
        {
            _positionMs = positionMs;
            _durationMs = durationMs;
            SetSongOffset(songOffsetMs);
            if (playing != _playing)
            {
                _playing = playing;
                ((TextBlock)_playPause.Content).Text = playing ? "" : "";
            }
            if (mute != _muteState)
            {
                _muteState = mute;
                ((TextBlock)_mute.Content).Text = mute ? "\uE74F" : "\uE767";
            }
            if (!_volume.IsMouseCaptureWithin)
            {
                if (float.IsNaN(volume) || float.IsInfinity(volume)) volume = 1;
                _updatingVolume = true;
                _volume.Value = Math.Max(0, Math.Min(1, volume));
                _updatingVolume = false;
            }
            if (!_shown) return;
            _seek.Fraction = durationMs > 0 ? positionMs / durationMs : 0;
            _played.Text = Clock(_seek.Dragging ? _seek.Fraction * durationMs : positionMs);
            _length.Text = Clock(durationMs);
        }

        /// <summary>Mouse moved over the window: show near the bottom, and restart the hide countdown.</summary>
        public void OnWindowMouseMove(Point p, double windowHeight)
        {
            if (p.Y > windowHeight * 0.7 || IsMouseOver) Show(true);
            if (_shown) { _hideTimer.Stop(); _hideTimer.Start(); }
        }

        public void Show(bool on)
        {
            if (on == _shown) return;
            _shown = on;
            IsHitTestVisible = on;
            BeginAnimation(OpacityProperty, new DoubleAnimation(on ? 1 : 0, TimeSpan.FromMilliseconds(on ? 160 : 450))
            {
                EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseOut }
            });
            if (on) { _hideTimer.Stop(); _hideTimer.Start(); } else _hideTimer.Stop();
        }

        private static TextBlock TimeText() => new TextBlock
        {
            Foreground = new SolidColorBrush(Color.FromRgb(170, 172, 200)), FontSize = 13, VerticalAlignment = VerticalAlignment.Center,
            FontFamily = new FontFamily("Cascadia Mono, Consolas"), MinWidth = 44, TextAlignment = TextAlignment.Center
        };

        private static string Clock(double ms)
        {
            var s = (int)Math.Max(0, ms / 1000);
            return $"{s / 60}:{s % 60:00}";
        }

        private static readonly ControlTemplate RoundTemplate = (ControlTemplate)XamlReader.Parse(
            "<ControlTemplate xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation' TargetType='Button'>" +
            "  <Border x:Name='bg' xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml' CornerRadius='30' Background='Transparent'>" +
            "    <ContentPresenter HorizontalAlignment='Center' VerticalAlignment='Center'/>" +
            "  </Border>" +
            "  <ControlTemplate.Triggers>" +
            "    <Trigger Property='IsMouseOver' Value='True'><Setter TargetName='bg' Property='Background' Value='#2EFFFFFF'/></Trigger>" +
            "    <Trigger Property='IsPressed' Value='True'><Setter TargetName='bg' Property='Background' Value='#50FFFFFF'/></Trigger>" +
            "  </ControlTemplate.Triggers>" +
            "</ControlTemplate>");

        private static Button IconButton(string glyph, string tip, double size, Action click, Action<Exception> log)
        {
            var b = new Button
            {
                Template = RoundTemplate, Width = size * 2.1, Height = size * 2.1, Margin = new Thickness(6, 0, 6, 0),
                ToolTip = tip, Focusable = false, Cursor = Cursors.Hand,
                Content = new TextBlock
                {
                    Text = glyph, FontSize = size, Foreground = Brushes.White,
                    FontFamily = new FontFamily("Segoe Fluent Icons, Segoe MDL2 Assets")
                }
            };
            b.Click += (s, e) => Safe.Run(click, log);
            return b;
        }

        /// <summary>Thin progress line; click or drag to seek (the seek happens on release).</summary>
        private sealed class SeekBar : FrameworkElement
        {
            private Brush _fill;
            private readonly Brush _track = new SolidColorBrush(Color.FromArgb(70, 255, 255, 255)), _thumb = Brushes.White;
            private double _fraction;
            public bool Dragging { get; private set; }
            public event Action<double> SeekRequested;

            public SeekBar(Color accent)
            {
                SetAccent(accent);
                Cursor = Cursors.Hand;
            }

            public void SetAccent(Color accent)
            {
                var brush = new SolidColorBrush(accent);
                brush.Freeze();
                _fill = brush;
                InvalidateVisual();
            }

            public double Fraction
            {
                get => _fraction;
                set { if (!Dragging) { _fraction = Math.Max(0, Math.Min(1, value)); InvalidateVisual(); } }
            }

            protected override void OnRender(DrawingContext dc)
            {
                dc.DrawRectangle(Brushes.Transparent, null, new Rect(RenderSize));   // whole height is clickable
                var y = RenderSize.Height / 2;
                var w = RenderSize.Width;
                var thick = IsMouseOver || Dragging ? 5 : 3;
                dc.DrawRoundedRectangle(_track, null, new Rect(0, y - thick / 2.0, w, thick), thick / 2.0, thick / 2.0);
                dc.DrawRoundedRectangle(_fill, null, new Rect(0, y - thick / 2.0, w * _fraction, thick), thick / 2.0, thick / 2.0);
                if (IsMouseOver || Dragging) dc.DrawEllipse(_thumb, null, new Point(w * _fraction, y), 7, 7);
            }

            private double At(MouseEventArgs e) => ActualWidth > 0 ? Math.Max(0, Math.Min(1, e.GetPosition(this).X / ActualWidth)) : 0;

            protected override void OnMouseLeftButtonDown(MouseButtonEventArgs e)
            {
                Dragging = true;
                CaptureMouse();
                _fraction = At(e);
                InvalidateVisual();
                e.Handled = true;
            }

            protected override void OnMouseMove(MouseEventArgs e)
            {
                if (Dragging) { _fraction = At(e); InvalidateVisual(); }
                else InvalidateVisual();
            }

            protected override void OnMouseLeftButtonUp(MouseButtonEventArgs e)
            {
                if (!Dragging) return;
                Dragging = false;
                ReleaseMouseCapture();
                SeekRequested?.Invoke(At(e));
                e.Handled = true;
            }

            protected override void OnMouseLeave(MouseEventArgs e) => InvalidateVisual();
        }
    }
}
