using System;
using System.Threading;
using System.Windows;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class DialogPlacementTests
    {
        /// <summary>FR-C-04: a dialog is topmost only when its karaoke owner is topmost, and the
        /// native-dialog helper lowers and restores that flag around the modal call.</summary>
        [Fact]
        public void FR_C_04_dialogs_follow_the_karaoke_windows_topmost_state()
        {
            Exception failure = null;
            var t = new Thread(() =>
            {
                try
                {
                    Assert.False(DialogPlacement.ShouldBeTopmost(null));

                    var w = new Window { Topmost = true };
                    Assert.True(DialogPlacement.ShouldBeTopmost(w));

                    var seenTopmost = DialogPlacement.AboveOwner(w, () => w.Topmost);
                    Assert.False(seenTopmost);
                    Assert.True(w.Topmost);

                    w.Topmost = false;
                    Assert.False(DialogPlacement.ShouldBeTopmost(w));
                    Assert.False(DialogPlacement.AboveOwner(w, () => w.Topmost));
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
