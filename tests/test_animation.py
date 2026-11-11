import random

import pytest

from lyricloom.animation import (LINE_SWEEP_DEFAULT_RATE, LINE_SWEEP_DELAY_MS, LineEmphasis, PlaybackClock,
                                 ScrollPath, effective_fps, line_sweeps, normalize_divisor, paused_fps,
                                 smootherstep, sung_weights, sweep_lit, target_fps, word_fill)


FRAME_MS = 1000.0 / 144.0


def test_playback_clock_tracks_jittered_ten_hz_samples_without_jumps_at_144_fps():
    """Design section 1: +-40 ms polls after one second stay within 25 ms, never go back and
    never step by more than one frame at the maximum correction rate."""
    clock = PlaybackClock()
    clock.sample(0, True, 0)
    rng = random.Random(12345)
    samples = []
    for k in range(1, 41):
        at = k * 100.0 + (rng.random() * 80.0 - 40.0)
        samples.append((at, at))
    samples.sort()

    next_sample = 0
    previous = float("-inf")
    max_error_after_one_second = 0.0
    max_step = 0.0
    for frame in range(0, 144 * 4 + 1):
        t = frame * FRAME_MS
        while next_sample < len(samples) and samples[next_sample][0] <= t:
            position, at = samples[next_sample]
            clock.sample(position, True, at)
            next_sample += 1
        now = clock.now_ms(t)
        if frame > 0:
            max_step = max(max_step, now - previous)
            assert now >= previous - 1e-9, f"the clock went back at {t:.1f} ms"
        if t >= 1000:
            max_error_after_one_second = max(max_error_after_one_second, abs(now - t))
        previous = now

    assert max_error_after_one_second < 25
    assert max_step <= FRAME_MS * 1.05 + 1


def test_a_two_second_seek_snaps_within_one_sample():
    clock = PlaybackClock()
    clock.sample(0, True, 0)
    for frame in range(0, int(500 / FRAME_MS) + 1):
        clock.now_ms(frame * FRAME_MS)

    clock.sample(2500, True, 500)
    now = clock.now_ms(500 + FRAME_MS)
    assert 2490 <= now <= 2515


def test_pause_freezes_and_resume_starts_from_the_reported_position():
    clock = PlaybackClock()
    clock.sample(0, True, 0)
    for frame in range(0, int(1000 / FRAME_MS) + 1):
        clock.now_ms(frame * FRAME_MS)

    clock.sample(1000, False, 1000)
    for frame in range(0, int(1000 / FRAME_MS) + 1):
        assert clock.now_ms(1000 + frame * FRAME_MS) == pytest.approx(1000)

    clock.sample(1000, True, 2000)
    resumed = clock.now_ms(2000 + FRAME_MS)
    assert 1005 <= resumed <= 1020
    assert clock.playing


def _ten_lines():
    centres = [200.0 + i * 120.0 + (i % 3) * 7.0 for i in range(10)]
    starts = [1000.0 + i * 2000.0 for i in range(10)]
    return ScrollPath(centres, starts, 1.0, 90.0)


def test_scroll_path_ten_lines_at_144_fps_has_no_step_or_velocity_jump_above_bounds():
    """Design section 3 at 144 frames/s: continuous position, steps within the path's peak
    velocity, and no velocity jump larger than one frame of the path's acceleration."""
    path = _ten_lines()
    end = 1000.0 + 9 * 2000.0 + 2000.0
    positions = []
    t = 0.0
    while t <= end:
        positions.append(path.position_at(t))
        t += FRAME_MS

    max_step = 0.0
    max_velocity_jump = 0.0
    previous_velocity = 0.0
    for i in range(1, len(positions)):
        step = abs(positions[i] - positions[i - 1])
        max_step = max(max_step, step)
        velocity = (positions[i] - positions[i - 1]) / (FRAME_MS / 1000.0)
        if i > 1:
            max_velocity_jump = max(max_velocity_jump, abs(velocity - previous_velocity))
        previous_velocity = velocity

    assert max_step <= path.peak_velocity * (FRAME_MS / 1000.0) + 0.000001
    assert max_velocity_jump <= path.peak_acceleration * (FRAME_MS / 1000.0) + 0.01


def test_every_line_is_centred_at_its_start_plus_lag():
    path = _ten_lines()
    for i in range(10):
        centre = 200.0 + i * 120.0 + (i % 3) * 7.0
        assert path.position_at(1000.0 + i * 2000.0 + 100.0) == pytest.approx(centre)


def test_close_lines_shrink_the_glide_to_the_gap_keeping_the_three_to_one_lead():
    path = ScrollPath([0.0, 200.0], [1000.0, 1100.0], 1.0, 90.0)
    assert path.position_at(1025.0) == pytest.approx(0.0)
    assert path.position_at(1125.0) == pytest.approx(200.0)
    assert path.position_at(1075.0) == pytest.approx(100.0)


def test_a_seek_residual_settles_within_400_ms_without_overshoot():
    residual = 300.0
    velocity = ScrollPath.clamp_residual_velocity(residual, -468.0)
    for ms in range(0, 401):
        value = ScrollPath.residual_at(residual, velocity, ms / 1000.0)
        assert value >= 0.0, f"residual crossed zero at {ms} ms"
    assert abs(ScrollPath.residual_at(residual, velocity, 0.4)) < 2.0


def test_smootherstep_has_zero_velocity_and_acceleration_at_both_ends():
    assert smootherstep(0.0) == 0.0
    assert smootherstep(1.0) == 1.0
    assert smootherstep(0.5) == pytest.approx(0.5)
    h = 1e-5
    assert (smootherstep(h) - smootherstep(0.0)) / h < 1e-9
    assert (smootherstep(1.0) - smootherstep(1.0 - h)) / h < 1e-9


def test_emphasis_grows_and_dims_with_the_same_eased_u_as_the_scroll():
    path = ScrollPath([100.0, 200.0], [1000.0, 2000.0], 1.0, 90.0)
    emphasis = LineEmphasis(2)

    assert emphasis.update(path.phase_at(700.0), -1) == [0.0, 0.0]
    intro = emphasis.update(path.phase_at(900.0), -1)
    assert intro[0] == pytest.approx(smootherstep(0.5))
    assert intro[1] == 0.0

    transition = emphasis.update(path.phase_at(1900.0), 1)
    assert transition[0] == pytest.approx(0.5)
    assert transition[1] == pytest.approx(0.5)

    steady = emphasis.update(path.phase_at(2500.0), 1)
    assert steady == [0.0, 1.0]

    # The incoming line's weight is exactly the scroll path's eased u: one motion, not two.
    phase = path.phase_at(1875.0)
    assert emphasis.update(phase, 1)[1] == pytest.approx(smootherstep(phase.u))


def test_word_fill_clamps_and_sweeps_from_start_to_end():
    assert word_fill(999, 1000, 2000) == 0.0
    assert word_fill(1500, 1000, 2000) == pytest.approx(0.5)
    assert word_fill(2000, 1000, 2000) == 1.0
    assert word_fill(3000, 1000, 2000) == 1.0


def test_word_fill_uses_a_sixty_ms_ramp_for_very_short_words():
    assert word_fill(1030, 1000, 1020) == pytest.approx(0.5)
    assert word_fill(1060, 1000, 1020) == 1.0
    assert word_fill(1015, 1000, None) == pytest.approx(0.25)
    assert word_fill(1015, None, 2000) == 0.0


def test_line_only_lyrics_sweep_the_whole_line_and_the_edge_moves_continuously():
    assert word_fill(2500, 2000, 4000) == pytest.approx(0.25)
    previous = 0.0
    for ms in range(2000, 4001):
        value = word_fill(ms, 2000, 4000)
        assert value >= previous - 1e-12
        assert value - previous <= 1.0 / 60.0 + 1e-12   # the shortest ramp never steps further
        previous = value


@pytest.mark.parametrize("divisor,hz,playing,expected", [
    (1, 144, True, 144), (2, 144, True, 72), (3, 144, True, 48),
    (1, 120, True, 120), (2, 120, True, 60), (3, 120, True, 40),
    (1, 60, True, 60), (2, 60, True, 30), (3, 60, True, 20),
    (1, 0, True, 60), (2, 0, True, 30), (3, 0, True, 20),
])
def test_divisor_targets_an_integer_division_of_the_monitor_refresh(divisor, hz, playing, expected):
    assert target_fps(divisor, hz) == expected
    assert effective_fps(divisor, hz, playing) == expected


def test_effective_fps_suspends_rendering_when_hidden_minimised_or_covered():
    assert effective_fps(1, 144, True, minimized=True) == 0
    assert effective_fps(1, 144, True, hidden=True) == 0
    assert effective_fps(1, 144, True, fully_covered=True) == 0


@pytest.mark.parametrize("hz,expected", [(144, 12), (120, 12), (60, 12), (30, 10), (165, 11)])
def test_paused_fps_is_a_slow_integer_divisor(hz, expected):
    assert paused_fps(hz) == expected
    assert effective_fps(1, hz, False) == expected


def test_invalid_divisors_fall_back_to_match_display():
    assert normalize_divisor(0) == 1
    assert normalize_divisor(4) == 1
    assert normalize_divisor("half") == 1
    assert normalize_divisor(3) == 3
    assert target_fps(4, 144) == 144


# ---------------------------------------------------------------- line-synced lyrics

def test_sung_weights_count_syllables_rather_than_letters():
    # "strength": one syllable in eight letters; "idea": three vowel groups... i-de-a is two
    # groups here ("ea" is one), the point is that letters alone do not decide the time.
    assert sum(sung_weights("strength")) == pytest.approx(8 * 0.25 + 1)
    assert sum(sung_weights("idea")) == pytest.approx(4 * 0.25 + 2)
    assert sung_weights("a b,") == [1.25, 0.0, 0.25, 0.0]
    # kana: one unit per mora, a small kana only extends the one before; kanji about 1.7
    assert sung_weights("きゃっと") == [1.0, 0.25, 1.0, 1.0]
    assert sung_weights("歌") == [1.7]


def _song(starts, unit_counts):
    estimate = [True] * len(starts)
    return line_sweeps(starts, unit_counts, estimate)


def test_line_sweeps_learn_the_pace_of_the_song():
    # eight lines of 10 units every 2.5 s: the pace is 10 units per 2.5 s (75th percentile)
    starts = [1000.0 + 2500.0 * i for i in range(8)]
    windows = _song(starts, [10.0] * 8)
    begin, end = windows[0]
    assert begin == pytest.approx(1000.0 + LINE_SWEEP_DELAY_MS)
    # 10 units at 4 units/s would be 2500 ms; it must leave a breath before the next line
    assert end <= starts[1] - 200.0
    assert end - begin > 1800.0


def test_line_sweeps_follow_a_slow_ballad_and_a_fast_rap_differently():
    slow = _song([5000.0 * i for i in range(6)], [10.0] * 6)       # 2 units/s
    fast = _song([1000.0 * i for i in range(6)], [10.0] * 6)       # 10 units/s
    slow_length = slow[0][1] - slow[0][0]
    fast_length = fast[0][1] - fast[0][0]
    assert slow_length > 3.5 * fast_length


def test_a_line_before_an_instrumental_is_not_stretched_over_it():
    starts = [0.0, 2500.0, 5000.0, 7500.0, 30000.0, 32500.0]       # 20 s break after line 3
    windows = _song(starts, [10.0] * 6)
    before_break = windows[3][1] - windows[3][0]
    regular = windows[1][1] - windows[1][0]
    assert before_break == pytest.approx(regular, rel=0.25)
    assert windows[3][1] < 11000.0


def test_line_sweeps_fall_back_to_a_default_pace_with_too_few_lines():
    windows = line_sweeps([1000.0, 60000.0], [8.6, 4.3], [True, True])
    begin, end = windows[1]                                         # the last line: no next line
    assert end - begin == pytest.approx(4.3 / LINE_SWEEP_DEFAULT_RATE)


def test_line_sweeps_skip_lines_that_have_word_times_or_no_time():
    windows = line_sweeps([1000.0, None, 5000.0], [5.0, 5.0, 5.0], [False, True, True])
    assert windows[0] is None and windows[1] is None and windows[2] is not None


def test_sweep_lit_starts_after_the_window_and_lights_spaces_with_their_letter():
    weights = sung_weights("ba da")
    window = (1000.0, 2000.0)
    assert sweep_lit(weights, 1000.0, window) == 0.0
    assert sweep_lit(weights, 2000.0, window) == pytest.approx(5.0)
    half = sweep_lit(weights, 1500.0, window)        # "ba" and "da" weigh the same
    assert half == pytest.approx(3.0)                # "ba" and its space are lit
    assert 0.0 < sweep_lit(weights, 1050.0, window) < 1.0
