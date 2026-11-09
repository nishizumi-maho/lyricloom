import pytest

from lyricloom.app.main import CommandLine, parse_command_line, run


def test_process_parses_one_or_more_files_and_redo():
    cli = parse_command_line(["--process", "a.flac", "b.mp3", "--redo"])
    assert cli == CommandLine(process=["a.flac", "b.mp3"], open_file=None, redo=True)


def test_process_can_be_repeated():
    cli = parse_command_line(["--process", "a.flac", "--process", "b.flac"])
    assert cli.process == ["a.flac", "b.flac"] and cli.redo is False


def test_open_parses_one_file_without_processing():
    cli = parse_command_line(["--open", "song.flac"])
    assert cli == CommandLine(process=[], open_file="song.flac", redo=False)


def test_redo_needs_process():
    with pytest.raises(SystemExit):
        parse_command_line(["--redo"])


def test_open_cannot_be_combined_with_process():
    with pytest.raises(SystemExit):
        parse_command_line(["--open", "a.flac", "--process", "b.flac"])


def test_worker_path_is_untouched(monkeypatch):
    calls = []
    monkeypatch.setattr("lyricloom.workers.launcher.run", lambda name: calls.append(name))
    run(["LyricLoom.exe", "--worker", "align_ctc"])
    run(["--worker", "separate"])
    assert calls == ["align_ctc", "separate"]


def test_worker_without_a_name_is_not_treated_as_a_worker():
    # Only the existing two-argument form is a worker; anything else still goes through argparse.
    with pytest.raises(SystemExit):
        run(["LyricLoom.exe", "--worker"])
