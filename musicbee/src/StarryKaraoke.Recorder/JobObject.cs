using System;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace StarryKaraoke.Recorder
{
    /// <summary>Win32 job object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (R4-11). Every ffmpeg
    /// process is assigned to it, so even if the recorder crashes or is killed, closing the last
    /// handle to the job terminates the children instead of leaving ffmpeg writing files forever.</summary>
    internal sealed class JobObject : IDisposable
    {
        private const int JobObjectExtendedLimitInformation = 9;
        private const uint JobObjectLimitKillOnJobClose = 0x00002000;

        private IntPtr _handle;

        private JobObject(IntPtr handle) { _handle = handle; }

        public bool IsValid => _handle != IntPtr.Zero;

        public static JobObject Create()
        {
            var handle = CreateJobObject(IntPtr.Zero, null);
            if (handle == IntPtr.Zero) return new JobObject(IntPtr.Zero);
            try
            {
                var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION
                {
                    BasicLimitInformation = new JOBOBJECT_BASIC_LIMIT_INFORMATION
                    {
                        LimitFlags = JobObjectLimitKillOnJobClose
                    }
                };
                var length = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
                var ptr = Marshal.AllocHGlobal(length);
                try
                {
                    Marshal.StructureToPtr(info, ptr, false);
                    if (!SetInformationJobObject(handle, JobObjectExtendedLimitInformation, ptr, (uint)length))
                    {
                        CloseHandle(handle);
                        return new JobObject(IntPtr.Zero);
                    }
                }
                finally { Marshal.FreeHGlobal(ptr); }
            }
            catch (Exception)
            {
                CloseHandle(handle);
                return new JobObject(IntPtr.Zero);
            }
            return new JobObject(handle);
        }

        /// <summary>Adds a process to the job. Returns false when the process already exited or the
        /// caller is in a job that forbids nesting; cancellation still kills it explicitly.</summary>
        public bool Assign(Process process)
        {
            if (!IsValid || process == null) return false;
            try { return AssignProcessToJobObject(_handle, process.Handle); }
            catch (Exception) { return false; }
        }

        /// <summary>Terminates every process in the job immediately (used by Force stop).</summary>
        public void KillAll()
        {
            if (IsValid) TerminateJobObject(_handle, 1);
        }

        public void Dispose()
        {
            var handle = _handle;
            _handle = IntPtr.Zero;
            if (handle != IntPtr.Zero)
            {
                try { CloseHandle(handle); } catch (Exception) { }
            }
        }

        // ---------------------------------------------------------------- Win32

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObject(IntPtr securityAttributes, string name);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint infoLength);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateJobObject(IntPtr job, uint exitCode);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IO_COUNTERS
        {
            public ulong ReadOperationCount;
            public ulong WriteOperationCount;
            public ulong OtherOperationCount;
            public ulong ReadTransferCount;
            public ulong WriteTransferCount;
            public ulong OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }
    }
}
