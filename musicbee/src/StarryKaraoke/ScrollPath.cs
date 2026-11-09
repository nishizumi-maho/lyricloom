using System;

namespace MusicBeePlugin
{
    /// <summary>The vertical scroll as a pure function of song time. Each line has a glide window
    /// that normally starts 0.30 s/speed before the line and ends 0.10 s/speed after it; a gap
    /// shorter than that shrinks the window to the gap (still 3:1 lead:lag), and a window can never
    /// overlap the previous one. <see cref="Smootherstep"/> has zero velocity and acceleration at
    /// both ends, so a line settles without a jerk.</summary>
    internal sealed class ScrollPath
    {
        public const double LeadSeconds = 0.30;
        public const double LagSeconds = 0.10;
        /// <summary>Natural frequency of the critically damped residual, in radians per second.</summary>
        public const double ResidualOmega = 20.0;

        /// <summary>Where a time falls between two lines. From is -1 for the intro glide to line 0,
        /// -2 when no glide is running.</summary>
        public struct Phase
        {
            public double Position;
            public int From;
            public double U;
            public bool IsTransition => From != -2;
        }

        private struct Transition
        {
            public double Start, End;
            public double FromY, ToY;
        }

        private readonly double[] _centers;
        private readonly double[] _starts;
        private readonly Transition[] _transitions;
        private readonly double _introY;

        public ScrollPath(double[] centers, double[] starts, double speed, double introOffsetPx)
        {
            _centers = centers ?? new double[0];
            _starts = starts ?? new double[0];
            var n = Math.Min(_centers.Length, _starts.Length);
            if (n != _centers.Length || n != _starts.Length)
            {
                Array.Resize(ref _centers, n);
                Array.Resize(ref _starts, n);
            }
            speed = Math.Max(0.3, Math.Min(3.0, speed));
            var lead = LeadSeconds * 1000.0 / speed;
            var lag = LagSeconds * 1000.0 / speed;
            _introY = n > 0 ? _centers[0] - introOffsetPx : 0;
            _transitions = new Transition[n];
            var previousEnd = double.NegativeInfinity;
            for (var i = 0; i < n; i++)
            {
                double start, end;
                if (i == 0)
                {
                    start = _starts[0] - lead;
                    end = _starts[0] + lag;
                }
                else
                {
                    var gap = Math.Max(1.0, _starts[i] - _starts[i - 1]);
                    var leadHere = lead;
                    var lagHere = lag;
                    if (gap < lead + lag)
                    {
                        leadHere = gap * 0.75;
                        lagHere = gap * 0.25;
                    }
                    start = _starts[i] - leadHere;
                    end = _starts[i] + lagHere;
                    if (start < previousEnd)
                    {
                        // The previous glide cannot still be running: finish it where this one starts.
                        var previous = _transitions[i - 1];
                        previous.End = Math.Max(previous.Start, start);
                        _transitions[i - 1] = previous;
                        start = previous.End;
                    }
                }
                _transitions[i] = new Transition
                {
                    Start = start,
                    End = Math.Max(start, end),
                    FromY = i == 0 ? _introY : _centers[i - 1],
                    ToY = _centers[i]
                };
                previousEnd = _transitions[i].End;
            }
            PeakVelocity = 0;
            PeakAcceleration = 0;
            foreach (var tr in _transitions)
            {
                var seconds = (tr.End - tr.Start) / 1000.0;
                if (seconds <= 0) continue;
                var distance = Math.Abs(tr.ToY - tr.FromY);
                PeakVelocity = Math.Max(PeakVelocity, 1.875 * distance / seconds);
                PeakAcceleration = Math.Max(PeakAcceleration, 5.7735 * distance / (seconds * seconds));
            }
        }

        public int Count => _centers.Length;

        /// <summary>Largest speed of the path, in pixels per second.</summary>
        public double PeakVelocity { get; }

        /// <summary>Largest acceleration of the path, in pixels per second squared.</summary>
        public double PeakAcceleration { get; }

        public static double Smootherstep(double u)
        {
            u = Math.Max(0, Math.Min(1, u));
            return u * u * u * (u * (u * 6 - 15) + 10);
        }

        /// <summary>A critically damped spring's residual after <paramref name="seconds"/>. The
        /// initial velocity is clamped before use (see <see cref="ClampResidualVelocity"/>) so the
        /// residual never crosses zero.</summary>
        public static double ResidualAt(double residual, double velocity, double seconds)
        {
            if (seconds <= 0) return residual;
            var x = ResidualOmega * seconds;
            return (residual + (velocity + ResidualOmega * residual) * seconds) * Math.Exp(-x);
        }

        /// <summary>Keeps the spring's initial velocity on the side that decays towards zero instead
        /// of crossing it, so a discontinuity never overshoots the target.</summary>
        public static double ClampResidualVelocity(double residual, double velocity)
        {
            if (residual > 0) return Math.Max(velocity, -ResidualOmega * residual);
            if (residual < 0) return Math.Min(velocity, -ResidualOmega * residual);
            return 0;
        }

        public double PositionAt(double t) => PhaseAt(t).Position;

        /// <summary>The scroll position, and which glide (if any) is running, at song time t.</summary>
        public Phase PhaseAt(double t)
        {
            var n = _centers.Length;
            if (n == 0) return new Phase { From = -2, Position = 0 };
            var index = LastStartAtOrBefore(t);
            if (index < 0)
                return new Phase { From = -2, Position = _introY };
            var tr = _transitions[index];
            if (t < tr.End)
            {
                var span = tr.End - tr.Start;
                var u = span <= 0 ? 1 : (t - tr.Start) / span;
                u = Math.Max(0, Math.Min(1, u));
                return new Phase
                {
                    From = index - 1,
                    U = u,
                    Position = tr.FromY + (tr.ToY - tr.FromY) * Smootherstep(u)
                };
            }
            return new Phase { From = -2, Position = _centers[index] };
        }

        /// <summary>The path's velocity at t, in pixels per second (central difference).</summary>
        public double VelocityAt(double t)
        {
            const double h = 0.5;   // milliseconds
            return (PositionAt(t + h) - PositionAt(t - h)) / (2 * h / 1000.0);
        }

        private int LastStartAtOrBefore(double t)
        {
            int lo = 0, hi = _transitions.Length - 1, found = -1;
            while (lo <= hi)
            {
                var mid = (lo + hi) / 2;
                if (_transitions[mid].Start <= t)
                {
                    found = mid;
                    lo = mid + 1;
                }
                else
                {
                    hi = mid - 1;
                }
            }
            return found;
        }
    }
}
