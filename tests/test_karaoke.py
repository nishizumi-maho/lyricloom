import os
import time
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricloom import config  # noqa: E402
from lyricloom.app.karaoke import KaraokeWindow  # noqa: E402
from lyricloom.app.media import default_script_path, script_candidates  # noqa: E402
from lyricloom.lrc import parse_lrc  # noqa: E402
from lyricloom.stages.write import japanese_path, romaji_path  # noqa: E402

LRC = ("[00:01.00]<00:01.00>eu <00:01.50>vou<00:02.00>\n"
       "[00:03.00]<00:03.00>de <00:03.40>novo<00:04.00>\n")


def _app():
    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout=10.0):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return condition()


class FakePlayer:
    def __init__(self):
        self.position_ms = 0
        self.positions = []
        self.plays = 0

    def position(self):
        return self.position_ms

    def setPosition(self, value):
        self.position_ms = int(value)
        self.positions.append(int(value))

    def playbackState(self):
        return QMediaPlayer.PausedState

    def play(self):
        self.plays += 1

    def stop(self):
        pass


class FakeKaraoke:
    made = []

    def __init__(self, audio, lyrics, **kwargs):
        self.audio = Path(audio)
        self.lyrics = Path(lyrics)
        self.kwargs = kwargs
        self.shown = False
        FakeKaraoke.made.append(self)

    def show(self):
        self.shown = True

    def close(self):
        pass

    def reload_lyrics(self):
        self.reloaded = getattr(self, "reloaded", 0) + 1


def test_current_line_index():
    lines = parse_lrc(LRC).lines
    assert KaraokeWindow._current_line_index(lines, 999) == -1
    assert KaraokeWindow._current_line_index(lines, 1000) == 0
    assert KaraokeWindow._current_line_index(lines, 2999) == 0
    assert KaraokeWindow._current_line_index(lines, 3000) == 1
    assert KaraokeWindow._current_line_index(lines, 99999) == 1


def _audio(tmp_path, text="romaji line"):
    audio = tmp_path / "Artist" / "Album" / "01 - Song.flac"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    audio.with_suffix(".lrc").write_text(f"[00:01.00]{text}\n", encoding="utf-8")
    return audio


def test_karaoke_window_starts_at_the_given_position(monkeypatch, tmp_path):
    _app()
    audio = _audio(tmp_path)
    monkeypatch.setattr(KaraokeWindow, "_set_source", lambda self: None)
    window = KaraokeWindow(audio, audio.with_suffix(".lrc"), start_ms=65000)
    fake = FakePlayer()
    window.player = fake
    try:
        assert window._pending_seek == 65000 and window._pending_play
        window._media_status(QMediaPlayer.LoadedMedia)
        assert fake.positions[-1] == 65000
        assert fake.plays == 1
    finally:
        window.player = FakePlayer()
        window.close()


def test_karaoke_follows_the_chosen_script_and_switches(monkeypatch, tmp_path):
    _app()
    audio = _audio(tmp_path, "romaji line")
    japanese_path(audio).write_text("[00:01.00]試験の歌\n", encoding="utf-8")
    romaji_path(audio).write_text("[00:01.00]romaji line\n", encoding="utf-8")
    config.set_japanese_script("romaji")
    monkeypatch.setattr(KaraokeWindow, "_set_source", lambda self: None)
    window = KaraokeWindow(audio, default_script_path(audio, "romaji"),
                           script_paths=script_candidates(audio, "romaji"))
    try:
        assert window.lyrics_path == audio.with_suffix(".lrc")   # the main .lrc follows the setting
        assert window.doc.lines[0].text == "romaji line"
        labels = [window.script.itemText(i) for i in range(window.script.count())]
        assert labels == ["Main (.lrc)", "Japanese", "Romaji"]
        window.script.setCurrentIndex(labels.index("Japanese"))
        assert window.doc.lines[0].text == "試験の歌"
    finally:
        window.player = FakePlayer()
        window.close()


def test_karaoke_next_and_previous_actions_call_the_callbacks(monkeypatch, tmp_path):
    _app()
    audio = _audio(tmp_path)
    called = []
    monkeypatch.setattr(KaraokeWindow, "_set_source", lambda self: None)
    window = KaraokeWindow(audio, audio.with_suffix(".lrc"),
                           on_next=lambda: called.append("next"),
                           on_prev=lambda: called.append("prev"))
    try:
        window.btn_next.click()
        window.btn_prev.click()
        window._next_track()
        window._previous_track()
        assert called == ["next", "prev", "next", "prev"]
        assert not window.btn_next.isHidden() and not window.btn_prev.isHidden()
    finally:
        window.player = FakePlayer()
        window.close()

    window = KaraokeWindow(audio, audio.with_suffix(".lrc"))
    try:
        assert window.btn_next.isHidden() and window.btn_prev.isHidden()
    finally:
        window.player = FakePlayer()
        window.close()


def test_karaoke_reload_lyrics_reads_a_saved_edit(monkeypatch, tmp_path):
    _app()
    audio = _audio(tmp_path, "old line")
    monkeypatch.setattr(KaraokeWindow, "_set_source", lambda self: None)
    window = KaraokeWindow(audio, audio.with_suffix(".lrc"))
    try:
        assert window.doc.lines[0].text == "old line"
        audio.with_suffix(".lrc").write_text("[00:01.00]new line\n", encoding="utf-8")
        window.reload_lyrics()
        assert window.doc.lines[0].text == "new line"
    finally:
        window.player = FakePlayer()
        window.close()


def test_main_window_passes_position_scripts_and_navigation(monkeypatch, tmp_path):
    app = _app()
    from lyricloom.app.main import MainWindow

    audio = _audio(tmp_path, "line")
    window = MainWindow(tmp_path)
    try:
        FakeKaraoke.made.clear()
        monkeypatch.setattr("lyricloom.app.main.KaraokeWindow", FakeKaraoke)
        window.timer.stop()

        class Player:
            def position(self):
                return 42000

            def pause(self):
                pass

            def playbackState(self):
                return QMediaPlayer.PausedState

        window.player = Player()
        window.audio = audio
        window.open_karaoke()
        made = FakeKaraoke.made[-1]
        assert made.shown and made.audio == audio
        assert made.kwargs["start_ms"] == 42000
        assert made.kwargs["on_next"] is not None and made.kwargs["on_prev"] is not None
        assert made.kwargs["script_paths"]
    finally:
        window.karaoke_window = None
        window.dirty = False
        window.close()
        app.processEvents()


def test_karaoke_next_selects_the_next_library_track(monkeypatch, tmp_path):
    app = _app()
    from lyricloom.app.main import MainWindow

    first = tmp_path / "Alpha" / "Album" / "01 - First.flac"
    second = tmp_path / "Beta" / "Album" / "02 - Second.flac"
    for audio in (first, second):
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"x")
        audio.with_suffix(".lrc").write_text("[00:01.00]line\n", encoding="utf-8")

    window = MainWindow(tmp_path)
    try:
        end = time.time() + 10
        while window.proxy.rowCount() != 2 and time.time() < end:
            app.processEvents()
            time.sleep(0.01)
        window.timer.stop()
        assert window.proxy.rowCount() == 2

        window.audio = first
        window.karaoke_window = FakeKaraoke(first, first.with_suffix(".lrc"))
        opened = []
        monkeypatch.setattr(window, "open_karaoke", lambda: opened.append(window.audio))
        window._karaoke_step(1)
        end = time.time() + 10
        while not opened and time.time() < end:
            app.processEvents()
            time.sleep(0.01)
        assert opened and window.audio == second
    finally:
        window.karaoke_window = None
        window.dirty = False
        window.close()
        app.processEvents()


def test_saving_in_the_main_window_reloads_an_open_karaoke_window(monkeypatch, tmp_path):
    app = _app()
    from lyricloom.app.main import MainWindow

    audio = _audio(tmp_path, "line")
    window = MainWindow(tmp_path)
    try:
        end = time.time() + 10
        while window.proxy.rowCount() != 1 and time.time() < end:
            app.processEvents()
            time.sleep(0.01)
        window.timer.stop()
        window.load(audio)
        fake = FakeKaraoke(audio, audio.with_suffix(".lrc"))
        window.karaoke_window = fake
        window.doc.lines[0].segments[0].text = "edited"
        window._set_dirty(True)

        assert window.save()
        assert fake.reloaded == 1
    finally:
        window.karaoke_window = None
        window.dirty = False
        window.close()
        app.processEvents()


def test_karaoke_window_plays_seeks_pauses_and_closes_a_silent_wav(tmp_path):
    """Gate G4: the real window and player open a fixture LRC and a short silent WAV, play,
    seek, pause and close without a playback error."""
    app = _app()
    audio = tmp_path / "Artist" / "Album" / "01 - Song.wav"
    audio.parent.mkdir(parents=True)
    with wave.open(str(audio), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(b"\x00\x00\x00\x00" * 88200)   # two silent seconds
    lyrics = audio.with_suffix(".lrc")
    lyrics.write_text("[00:00.20]<00:00.20>hello <00:00.60>world<00:01.00>\n"
                      "[00:01.20]<00:01.20>second line<00:01.80>\n", encoding="utf-8")

    window = KaraokeWindow(audio, lyrics, start_ms=0)
    try:
        # The WAV is silent and a headless CI machine may have no audio device: the real media
        # pipeline (decode, position, seek, pause) is what this gate exercises.
        window.player.setAudioOutput(None)
        window.show()
        assert _wait(app, lambda: window.player.playbackState() == QMediaPlayer.PlayingState, timeout=10)
        window.player.setPosition(400)
        _wait(app, lambda: window.player.position() >= 300, timeout=5)
        window.player.pause()
        _wait(app, lambda: window.player.playbackState() == QMediaPlayer.PausedState, timeout=5)
        assert "Playback error" not in window.hint.text()
        assert window.doc is not None and len(window.doc.lines) == 2
        window.lyrics.advance(window.lyrics.elapsed_ms())
        assert window.lyrics._lines and window.lyrics.current_line_text()
    finally:
        window.close()
        app.processEvents()
