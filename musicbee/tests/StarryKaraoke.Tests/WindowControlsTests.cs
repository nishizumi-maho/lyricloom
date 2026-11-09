using System;
using System.Threading;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class WindowControlsTests
    {
        /// <summary>Each window command reaches the plugin's command exactly once (a seek that called
        /// itself overflowed the stack and took MusicBee down).</summary>
        [Fact]
        public void Window_commands_call_the_player_once()
        {
            int seeks = 0, plays = 0, prev = 0, next = 0, volumes = 0, mutes = 0;
            double seekedTo = -1;
            float volume = -1;
            bool mute = false;
            Exception failure = null;
            var t = new Thread(() =>
            {
                try
                {
                    var player = new PlayerControls
                    {
                        Seek = ms => { seeks++; seekedTo = ms; },
                        PlayPause = () => plays++,
                        Previous = () => prev++,
                        Next = () => next++,
                        SetVolume = v => { volumes++; volume = v; },
                        SetMute = m => { mutes++; mute = m; }
                    };
                    var w = new KaraokeWindow(new Settings(), () => (0.0, false, 1f, false), player);
                    w.Controls.Seek(42000);
                    w.Controls.PlayPause();
                    w.Controls.Previous();
                    w.Controls.Next();
                    w.Controls.SetVolume(0.5f);
                    w.Controls.SetMute(true);
                    w.Close();
                }
                catch (Exception e) { failure = e; }
            });
            t.SetApartmentState(ApartmentState.STA);
            t.Start();
            t.Join();
            Assert.Null(failure);
            Assert.Equal(1, seeks);
            Assert.Equal(42000, seekedTo);
            Assert.Equal(1, plays);
            Assert.Equal(1, prev);
            Assert.Equal(1, next);
            Assert.Equal(1, volumes);
            Assert.Equal(0.5f, volume);
            Assert.Equal(1, mutes);
            Assert.True(mute);
        }

        [Fact]
        public void Settings_preview_is_debounced_instead_of_rebuilt_on_every_change()
        {
            Exception failure = null;
            var previews = 0;
            var t = new Thread(() =>
            {
                try
                {
                    var w = new SettingsWindow(new Settings(), _ => previews++);
                    w.ChangeForTest(s => s.TextScale = 1.3);
                    Assert.Equal(0, previews);          // the 150 ms timer has not fired yet
                    Assert.True(w.HasPendingPreview);
                    w.Close();
                }
                catch (Exception e) { failure = e; }
            });
            t.SetApartmentState(ApartmentState.STA);
            t.Start();
            t.Join();
            Assert.Null(failure);
        }

        [Fact]
        public void Settings_window_constructs_with_the_theme_section()
        {
            Exception failure = null;
            var t = new Thread(() =>
            {
                try
                {
                    var w = new SettingsWindow(new Settings(), _ => { });
                    w.Close();
                }
                catch (Exception e) { failure = e; }
            });
            t.SetApartmentState(ApartmentState.STA);
            t.Start();
            t.Join();
            Assert.Null(failure);
        }

        [Fact]
        public void The_scene_uses_the_windows_dpi_for_text_layout()
        {
            Exception failure = null;
            var t = new Thread(() =>
            {
                try
                {
                    var w = new KaraokeWindow(new Settings(), () => (0.0, false, 1f, false), new PlayerControls());
                    var expected = System.Windows.Media.VisualTreeHelper.GetDpi(w).PixelsPerDip;
                    Assert.Equal(expected, w.ScenePixelsPerDip);
                    w.Close();
                }
                catch (Exception e) { failure = e; }
            });
            t.SetApartmentState(ApartmentState.STA);
            t.Start();
            t.Join();
            Assert.Null(failure);
        }

        [Fact]
        public void The_LyricLoom_waiting_status_replaces_the_hint_until_it_is_cleared()
        {
            Exception failure = null;
            var t = new Thread(() =>
            {
                try
                {
                    var w = new KaraokeWindow(new Settings(), () => (0.0, false, 1f, false), new PlayerControls());
                    w.SetWordTimingAvailable(hasWordTiming: false, canCreateLyrics: true);
                    Assert.True(w.IsHintVisible);
                    Assert.False(w.IsLyricLoomStatusVisible);

                    w.ShowLyricLoomPending();
                    Assert.True(w.IsLyricLoomStatusVisible);
                    Assert.False(w.IsHintVisible);

                    w.ClearLyricLoomPending();
                    Assert.False(w.IsLyricLoomStatusVisible);
                    Assert.True(w.IsHintVisible);
                    w.Close();
                }
                catch (Exception e) { failure = e; }
            });
            t.SetApartmentState(ApartmentState.STA);
            t.Start();
            t.Join();
            Assert.Null(failure);
        }
    }
}
