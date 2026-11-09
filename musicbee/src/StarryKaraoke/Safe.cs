using System;
using System.Windows.Threading;

namespace MusicBeePlugin
{
    /// <summary>
    /// Small guard used at every WPF/WinForms entry point. One bad settings value or render frame must
    /// not reach MusicBee's dispatcher, where an unhandled exception can close the whole application.
    /// </summary>
    internal static class Safe
    {
        public static void Run(Action action, Action<Exception> log)
        {
            if (action == null) return;
            try { action(); }
            catch (Exception e) { log?.Invoke(e); }
        }

        public static T Get<T>(Func<T> func, T fallback, Action<Exception> log)
        {
            if (func == null) return fallback;
            try { return func(); }
            catch (Exception e)
            {
                log?.Invoke(e);
                return fallback;
            }
        }

        public static Action Wrap(Action action, Action<Exception> log) => () => Run(action, log);

        /// <summary>Marks dispatcher exceptions handled after logging them. Returns false when there is
        /// no dispatcher to attach to.</summary>
        public static bool InstallDispatcherHandler(Dispatcher dispatcher, Action<Exception> log, Action<string> userMessage)
        {
            if (dispatcher == null) return false;
            dispatcher.UnhandledException += (s, e) =>
            {
                e.Handled = true;
                log?.Invoke(e.Exception);
                userMessage?.Invoke("Starry Karaoke recovered from an unexpected error. See mb_StarryKaraoke.log for details.");
            };
            return true;
        }
    }

    /// <summary>The plugin's own log, next to the DLL. It is rotated before it grows past the cap and
    /// contains diagnostics and paths only, never lyrics text.</summary>
    internal static class PluginLog
    {
        public const long MaxBytes = 1_000_000;

        public static void Append(string path, string message, long maxBytes = MaxBytes)
        {
            if (string.IsNullOrEmpty(path)) return;
            var folder = System.IO.Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(folder)) System.IO.Directory.CreateDirectory(folder);

            if (System.IO.File.Exists(path) && new System.IO.FileInfo(path).Length > maxBytes)
            {
                var old = path + ".old";
                if (System.IO.File.Exists(old)) System.IO.File.Delete(old);
                System.IO.File.Move(path, old);
            }
            System.IO.File.AppendAllText(path,
                $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} {message}{Environment.NewLine}");
        }
    }
}
