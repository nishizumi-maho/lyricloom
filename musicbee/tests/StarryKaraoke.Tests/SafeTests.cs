using System;
using MusicBeePlugin;
using Xunit;

namespace StarryKaraoke.Tests
{
    public class SafeTests
    {
        /// <summary>FR-C-08: the dispatcher safety net must not swallow another WPF plugin's crash
        /// and report it as Starry Karaoke's. Only stacks naming a MusicBeePlugin type are ours.</summary>
        [Fact]
        public void FR_C_08_the_dispatcher_safety_net_handles_only_this_plugins_exceptions()
        {
            Exception plugin = null;
            Safe.Get<int>(() => throw new InvalidOperationException("inside the plugin"), 0, e => plugin = e);
            Assert.NotNull(plugin);
            Assert.True(Safe.IsFromPlugin(plugin));

            Exception other = null;
            try { throw new InvalidOperationException("another plugin"); }
            catch (Exception e) { other = e; }
            Assert.False(Safe.IsFromPlugin(other));

            var logged = 0;
            var messages = 0;
            Assert.True(Safe.HandleDispatcherException(plugin, _ => logged++, _ => messages++));
            Assert.Equal(1, logged);
            Assert.Equal(1, messages);

            Assert.False(Safe.HandleDispatcherException(other, _ => logged++, _ => messages++));
            Assert.Equal(1, logged);
            Assert.Equal(1, messages);
        }

        [Fact]
        public void FR_C_08_an_inner_plugin_exception_is_recognised()
        {
            Exception inner = null;
            Safe.Get<int>(() => throw new InvalidOperationException("inside the plugin"), 0, e => inner = e);
            Assert.NotNull(inner);
            Assert.True(Safe.IsFromPlugin(new InvalidOperationException("wrapper", inner)));
            Assert.False(Safe.IsFromPlugin(new InvalidOperationException("plain")));
        }
    }
}
