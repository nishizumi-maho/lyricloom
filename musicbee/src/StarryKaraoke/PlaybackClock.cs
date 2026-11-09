using System;
using System.Diagnostics;

namespace MusicBeePlugin
{
    /// <summary>Song position between polls. A player sample is timestamped when the player is
    /// asked (not when a frame reads it), extrapolated to the frame's monotonic time, and followed
    /// with a slightly adjusted rate instead of jumping on every poll. The output moves only
    /// forwards while playing and snaps only for a seek, a play/pause change or a new song.</summary>
    internal sealed class PlaybackClock
    {
        /// <summary>How long the low-pass error takes to follow a change, in milliseconds.</summary>
        private const double ErrorTauMs = 300.0;
        /// <summary>An error of this size doubles the correction: +-1 means the +-5% rate limit.</summary>
        private const double RateErrorMs = 500.0;
        private const double MaxRateError = 0.05;
        /// <summary>Larger corrections are a seek, not drift.</summary>
        private const double SnapMs = 250.0;
        /// <summary>Advance the output in short steps so a long frame cannot overshoot the rate.</summary>
        private const double MaxStepMs = 10.0;

        private bool _hasOutput;
        private bool _hasSample;
        private bool _playing;
        private double _samplePos, _sampleAt;
        private bool _samplePlaying;
        private double _output, _outputAt;
        private double _ema;

        /// <summary>True while the latest sample says the player is playing.</summary>
        public bool Playing => _playing;

        /// <summary>Monotonic milliseconds on the Stopwatch time base, for samples and frames.</summary>
        public static double TimestampMs() => Stopwatch.GetTimestamp() * (1000.0 / Stopwatch.Frequency);

        /// <summary>Forget everything; the next sample starts the clock at its reported position.</summary>
        public void Reset()
        {
            _hasOutput = false;
            _hasSample = false;
            _playing = false;
            _output = _outputAt = 0;
            _ema = 0;
        }

        /// <summary>A player reading taken at <paramref name="sampledAtMs"/> (same time base as
        /// <see cref="TimestampMs"/>). Out-of-order samples are ignored.</summary>
        public void Sample(double positionMs, bool playing, double sampledAtMs)
        {
            if (!_hasOutput)
            {
                _output = positionMs;
                _outputAt = sampledAtMs;
                _playing = playing;
                _samplePos = positionMs;
                _sampleAt = sampledAtMs;
                _samplePlaying = playing;
                _hasSample = true;
                _hasOutput = true;
                _ema = 0;
                return;
            }
            if (_hasSample && sampledAtMs <= _sampleAt + 0.0001) return;

            // A frame usually runs before the poll timer's next tick, so the sample may be a little
            // older than the last frame. Evaluate it at the later of the two times without moving
            // the (already shown) output backwards.
            var evalAt = Math.Max(sampledAtMs, _outputAt);
            AdvanceTo(evalAt);
            var newExtrapolated = playing ? positionMs + (evalAt - sampledAtMs) : positionMs;
            var error = newExtrapolated - _output;
            var stateChanged = playing != _playing;

            if (stateChanged || Math.Abs(error) > SnapMs)
            {
                // Seek, pause/resume or a new song: a discontinuity is allowed here.
                _output = newExtrapolated;
                _outputAt = evalAt;
                _ema = 0;
            }
            else
            {
                var dt = sampledAtMs - _sampleAt;
                if (dt > 0)
                {
                    var alpha = 1 - Math.Exp(-dt / ErrorTauMs);
                    _ema += alpha * (error - _ema);
                }
            }

            _playing = playing;
            _samplePos = positionMs;
            _sampleAt = sampledAtMs;
            _samplePlaying = playing;
            _hasSample = true;
        }

        /// <summary>The estimated player position in milliseconds at a monotonic frame time.</summary>
        public double NowMs(double frameTimeMs)
        {
            if (!_hasOutput) return 0;
            AdvanceTo(frameTimeMs);
            return _output;
        }

        private void AdvanceTo(double timeMs)
        {
            while (_outputAt < timeMs)
            {
                var step = Math.Min(MaxStepMs, timeMs - _outputAt);
                _outputAt += step;
                if (!_playing) continue;

                var sample = _hasSample
                    ? (_samplePlaying ? _samplePos + (_outputAt - _sampleAt) : _samplePos)
                    : _output;
                var error = sample - _output;
                var alpha = 1 - Math.Exp(-step / ErrorTauMs);
                _ema += alpha * (error - _ema);
                var rate = 1 + Math.Max(-MaxRateError, Math.Min(MaxRateError, _ema / RateErrorMs));
                _output += step * rate;
            }
        }
    }
}
