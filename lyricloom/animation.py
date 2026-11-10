"""Time-driven animation for smooth lyrics, with no Qt imports.

The pieces the widgets share:

* :class:`PlaybackClock` turns occasional, jittery player samples into a continuous song time.
* :class:`ScrollPath` is the pure vertical path of the lyric column, plus the critically damped
  residual that absorbs a seek or a resize without a jump.
* :func:`word_fill` is the sub-pixel progress of one word (or a whole line when it has no word
  timing), and :class:`LineEmphasis` is the eased growth/dimming of a line.

The frame-rate helpers keep every lower rate an integer divisor of the display refresh rate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

ERROR_TAU_MS = 300.0
"""Time constant of the low-pass error, in milliseconds."""

RATE_ERROR_MS = 500.0
"""An error of this size doubles the correction: +-1 is the +-5 % rate limit."""

MAX_RATE_ERROR = 0.05
"""Largest relative rate correction while playing."""

SNAP_MS = 250.0
"""A larger error is a seek (or a new song), where a discontinuity is allowed."""

MAX_STEP_MS = 10.0
"""Advance the clock output in short steps so one long frame cannot overshoot the rate."""

DEFAULT_REFRESH_HZ = 60.0
"""Fallback refresh rate when the display does not report one."""

PAUSED_MIN_FPS = 10.0
PAUSED_MAX_FPS = 15.0
"""A paused window still ticks slowly, at an integer divisor of the refresh rate."""

DIVISORS = (1, 2, 3)
"""Match display, half refresh or third refresh."""


class PlaybackClock:
    """Song position between polls.

    A player sample is timestamped when the player was asked (not when a frame reads it),
    extrapolated to the frame's monotonic time, and followed with a slightly adjusted rate instead
    of jumping on every poll. The output moves only forwards while playing and snaps only for a
    seek, a play/pause change or a new song.
    """

    def __init__(self) -> None:
        self._has_output = False
        self._has_sample = False
        self._playing = False
        self._sample_pos = 0.0
        self._sample_at = 0.0
        self._sample_playing = False
        self._output = 0.0
        self._output_at = 0.0
        self._ema = 0.0

    @property
    def playing(self) -> bool:
        """True while the latest sample says the player is playing."""
        return self._playing

    def reset(self) -> None:
        """Forget everything; the next sample starts the clock at its reported position."""
        self._has_output = False
        self._has_sample = False
        self._playing = False
        self._output = self._output_at = 0.0
        self._ema = 0.0

    def sample(self, position_ms: float, playing: bool, sampled_at_ms: float) -> None:
        """A player reading taken at ``sampled_at_ms`` (same monotonic time base as the frames)."""
        if not self._has_output:
            self._output = float(position_ms)
            self._output_at = float(sampled_at_ms)
            self._playing = bool(playing)
            self._sample_pos = float(position_ms)
            self._sample_at = float(sampled_at_ms)
            self._sample_playing = bool(playing)
            self._has_sample = True
            self._has_output = True
            self._ema = 0.0
            return
        if self._has_sample and sampled_at_ms <= self._sample_at + 0.0001:
            return

        # A frame usually runs before the poll timer's next tick, so the sample may be a little
        # older than the last frame. Evaluate it at the later of the two times without moving the
        # already shown output backwards.
        eval_at = max(float(sampled_at_ms), self._output_at)
        self._advance_to(eval_at)
        new_extrapolated = (float(position_ms) + (eval_at - float(sampled_at_ms))
                            if playing else float(position_ms))
        error = new_extrapolated - self._output
        state_changed = bool(playing) != self._playing

        if state_changed or abs(error) > SNAP_MS:
            # Seek, pause/resume or a new song: a discontinuity is allowed here.
            self._output = new_extrapolated
            self._output_at = eval_at
            self._ema = 0.0
        else:
            dt = float(sampled_at_ms) - self._sample_at
            if dt > 0:
                alpha = 1.0 - math.exp(-dt / ERROR_TAU_MS)
                self._ema += alpha * (error - self._ema)

        self._playing = bool(playing)
        self._sample_pos = float(position_ms)
        self._sample_at = float(sampled_at_ms)
        self._sample_playing = bool(playing)
        self._has_sample = True

    def now_ms(self, frame_time_ms: float) -> float:
        """The estimated player position in milliseconds at a monotonic frame time."""
        if not self._has_output:
            return 0.0
        self._advance_to(float(frame_time_ms))
        return self._output

    def _advance_to(self, time_ms: float) -> None:
        while self._output_at < time_ms:
            step = min(MAX_STEP_MS, time_ms - self._output_at)
            self._output_at += step
            if not self._playing:
                continue
            sample = (self._sample_pos + (self._output_at - self._sample_at)
                      if self._sample_playing else self._sample_pos)
            error = sample - self._output
            alpha = 1.0 - math.exp(-step / ERROR_TAU_MS)
            self._ema += alpha * (error - self._ema)
            rate = 1.0 + max(-MAX_RATE_ERROR, min(MAX_RATE_ERROR, self._ema / RATE_ERROR_MS))
            self._output += step * rate


def smootherstep(u: float) -> float:
    """Clamped ``u^3 (u (6u - 15) + 10)``: zero velocity and acceleration at both ends."""
    u = max(0.0, min(1.0, u))
    return u * u * u * (u * (u * 6.0 - 15.0) + 10.0)


@dataclass(frozen=True)
class ScrollPhase:
    """Where a song time falls between two lines."""

    position: float
    from_index: int
    u: float

    @property
    def is_transition(self) -> bool:
        """True while a glide (including the intro glide) is running."""
        return self.from_index != -2


@dataclass
class _Transition:
    start: float
    end: float
    from_y: float
    to_y: float


class ScrollPath:
    """The vertical scroll as a pure function of song time.

    Each line has a glide window that normally starts 0.30 s/speed before the line and ends
    0.10 s/speed after it; a gap shorter than that shrinks the window to the gap (still 3:1
    lead:lag), and a window never overlaps the previous one. ``smootherstep`` has zero velocity
    and acceleration at both ends, so a line settles without a jerk.
    """

    LEAD_SECONDS = 0.30
    LAG_SECONDS = 0.10
    RESIDUAL_OMEGA = 20.0

    def __init__(self, centres: list[float] | tuple[float, ...],
                 starts_ms: list[float] | tuple[float, ...], speed: float = 1.0,
                 intro_offset_px: float = 90.0) -> None:
        n = min(len(centres), len(starts_ms))
        self._centres = [float(value) for value in centres[:n]]
        self._starts = [float(value) for value in starts_ms[:n]]
        speed = max(0.3, min(3.0, float(speed)))
        lead = self.LEAD_SECONDS * 1000.0 / speed
        lag = self.LAG_SECONDS * 1000.0 / speed
        self._intro_y = self._centres[0] - float(intro_offset_px) if n else 0.0
        self._transitions: list[_Transition] = []
        previous_end = float("-inf")
        for i in range(n):
            if i == 0:
                start = self._starts[0] - lead
                end = self._starts[0] + lag
            else:
                gap = max(1.0, self._starts[i] - self._starts[i - 1])
                lead_here, lag_here = lead, lag
                if gap < lead + lag:
                    lead_here = gap * 0.75
                    lag_here = gap * 0.25
                start = self._starts[i] - lead_here
                end = self._starts[i] + lag_here
                if start < previous_end:
                    # The previous glide cannot still be running: finish it where this one starts.
                    previous = self._transitions[i - 1]
                    previous.end = max(previous.start, start)
                    start = previous.end
            transition = _Transition(start=start, end=max(start, end),
                                     from_y=self._intro_y if i == 0 else self._centres[i - 1],
                                     to_y=self._centres[i])
            self._transitions.append(transition)
            previous_end = transition.end

        self.peak_velocity = 0.0
        self.peak_acceleration = 0.0
        for transition in self._transitions:
            seconds = (transition.end - transition.start) / 1000.0
            if seconds <= 0:
                continue
            distance = abs(transition.to_y - transition.from_y)
            self.peak_velocity = max(self.peak_velocity, 1.875 * distance / seconds)
            self.peak_acceleration = max(self.peak_acceleration,
                                         5.7735 * distance / (seconds * seconds))

    def __len__(self) -> int:
        return len(self._centres)

    def position_at(self, t_ms: float) -> float:
        return self.phase_at(t_ms).position

    def phase_at(self, t_ms: float) -> ScrollPhase:
        """The scroll position, and which glide (if any) is running, at song time t."""
        n = len(self._centres)
        if n == 0:
            return ScrollPhase(0.0, -2, 0.0)
        index = self._last_start_at_or_before(float(t_ms))
        if index < 0:
            return ScrollPhase(self._intro_y, -2, 0.0)
        transition = self._transitions[index]
        if t_ms < transition.end:
            span = transition.end - transition.start
            u = 1.0 if span <= 0 else (float(t_ms) - transition.start) / span
            u = max(0.0, min(1.0, u))
            position = transition.from_y + (transition.to_y - transition.from_y) * smootherstep(u)
            return ScrollPhase(position, index - 1, u)
        return ScrollPhase(self._centres[index], -2, 0.0)

    def velocity_at(self, t_ms: float) -> float:
        """The path's velocity at t, in pixels per second (central difference)."""
        h = 0.5  # milliseconds
        return (self.position_at(t_ms + h) - self.position_at(t_ms - h)) / (2.0 * h / 1000.0)

    def _last_start_at_or_before(self, t_ms: float) -> int:
        lo, hi, found = 0, len(self._transitions) - 1, -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._transitions[mid].start <= t_ms:
                found = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return found

    @staticmethod
    def residual_at(residual: float, velocity: float, seconds: float) -> float:
        """A critically damped spring's residual after ``seconds``."""
        if seconds <= 0:
            return residual
        x = ScrollPath.RESIDUAL_OMEGA * seconds
        return ((residual + (velocity + ScrollPath.RESIDUAL_OMEGA * residual) * seconds)
                * math.exp(-x))

    @staticmethod
    def clamp_residual_velocity(residual: float, velocity: float) -> float:
        """Keep the spring's initial velocity on the side that decays towards zero."""
        if residual > 0:
            return max(velocity, -ScrollPath.RESIDUAL_OMEGA * residual)
        if residual < 0:
            return min(velocity, -ScrollPath.RESIDUAL_OMEGA * residual)
        return 0.0


class LineEmphasis:
    """Per-line growth/brightness weights, following the scroll path's eased ``u``.

    A line grows in while it glides to the centre, and the outgoing line dims over the same
    interval. The list is reused so a frame allocates nothing.
    """

    def __init__(self, count: int = 0) -> None:
        self._values = [0.0] * max(0, int(count))

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, index: int) -> float:
        return self._values[index]

    @property
    def values(self) -> list[float]:
        return self._values

    def reset(self, count: int) -> None:
        count = max(0, int(count))
        if len(self._values) != count:
            self._values = [0.0] * count
        else:
            for i in range(count):
                self._values[i] = 0.0

    def update(self, phase: ScrollPhase, current_index: int) -> list[float]:
        """Set every line's emphasis for ``phase``; returns the reused list."""
        values = self._values
        for i in range(len(values)):
            values[i] = 0.0
        if phase.is_transition:
            eased = smootherstep(phase.u)
            if phase.from_index < 0:
                if values:
                    values[0] = eased
            else:
                if 0 <= phase.from_index < len(values):
                    values[phase.from_index] = 1.0 - eased
                if 0 <= phase.from_index + 1 < len(values):
                    values[phase.from_index + 1] = eased
        elif 0 <= current_index < len(values):
            values[current_index] = 1.0
        return values


def word_fill(t_ms: float, start_ms: float | None, end_ms: float | None) -> float:
    """Fill progress of one word, clamped to [0, 1].

    Words shorter than 60 ms (or with a missing end) use a 60 ms ramp so they cannot flash.
    A line without word timing passes the line's own start and end, which sweeps the whole line.
    """
    if start_ms is None:
        return 0.0
    if end_ms is None or end_ms <= start_ms:
        span = 60.0
    else:
        span = max(60.0, float(end_ms) - float(start_ms))
    return max(0.0, min(1.0, (float(t_ms) - float(start_ms)) / span))


def normalize_divisor(divisor: int) -> int:
    """1 = match display, 2 = half refresh, 3 = third refresh."""
    try:
        value = int(divisor)
    except (TypeError, ValueError):
        return 1
    return value if value in DIVISORS else 1


def target_fps(divisor: int, monitor_hz: float) -> int:
    """Frames per second for an integer divisor of the monitor refresh rate."""
    hz = int(round(float(monitor_hz))) if monitor_hz else int(DEFAULT_REFRESH_HZ)
    if hz <= 0:
        hz = int(DEFAULT_REFRESH_HZ)
    return max(1, hz // normalize_divisor(divisor))


def paused_fps(monitor_hz: float) -> int:
    """A slow tick while paused, still an exact divisor of the refresh rate, kept at 10-15 fps."""
    hz = int(round(float(monitor_hz))) if monitor_hz else 0
    if hz <= 0:
        return 12
    best, best_distance = 12, float("inf")
    for divisor in range(1, hz + 1):
        if hz % divisor != 0:
            continue
        fps = hz // divisor
        if fps < PAUSED_MIN_FPS or fps > PAUSED_MAX_FPS:
            continue
        distance = abs(fps - 12.0)
        if distance < best_distance:
            best, best_distance = fps, distance
    return best


def effective_fps(divisor: int, monitor_hz: float, playing: bool, minimized: bool = False,
                  hidden: bool = False, fully_covered: bool = False) -> int:
    """Repaints per second, or 0 when rendering must stop entirely."""
    if minimized or hidden or fully_covered:
        return 0
    return target_fps(divisor, monitor_hz) if playing else paused_fps(monitor_hz)
