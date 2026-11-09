using System;
using System.IO;

namespace StarryKaraoke.Tests
{
    /// <summary>A disposable folder under the system temp directory, kept short so tool paths fit.</summary>
    internal sealed class TempFolder : IDisposable
    {
        public string Path { get; }

        public TempFolder()
        {
            Path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "sk-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path);
        }

        public string File(string name) => System.IO.Path.Combine(Path, name);

        public void Dispose()
        {
            try { if (Directory.Exists(Path)) Directory.Delete(Path, true); }
            catch (Exception) { }
        }
    }
}
