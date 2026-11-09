import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from lyricloom.workers import WorkerCancelled, run_worker

TESTS = Path(__file__).resolve().parent


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True).stdout
        return re.search(rf"\b{pid}\b", out) is not None
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_cancel_kills_the_worker_process_tree(tmp_path):
    pidfile = tmp_path / "pids.txt"
    cancel = threading.Event()

    def stop_when_started():
        deadline = time.time() + 20
        while not pidfile.exists() and time.time() < deadline:
            time.sleep(0.02)
        time.sleep(0.2)
        cancel.set()

    threading.Thread(target=stop_when_started, daemon=True).start()
    started = time.monotonic()
    with pytest.raises(WorkerCancelled):
        run_worker("fake_worker", {"sleep": 30, "spawn_child": True, "pidfile": str(pidfile)},
                   python=sys.executable, cwd=TESTS, cancel=cancel)
    assert time.monotonic() - started < 20
    pids = [int(pid) for pid in pidfile.read_text(encoding="utf-8").split(",")]
    assert len(pids) == 2
    deadline = time.time() + 10
    while any(_alive(pid) for pid in pids) and time.time() < deadline:
        time.sleep(0.1)
    assert not any(_alive(pid) for pid in pids)


def test_timeout_still_raises_timeout_expired():
    with pytest.raises(subprocess.TimeoutExpired):
        run_worker("fake_worker", {"sleep": 10}, python=sys.executable, cwd=TESTS, timeout_s=1)


def test_cancel_before_start_does_not_launch():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(WorkerCancelled):
        run_worker("fake_worker", {}, python=sys.executable, cwd=TESTS, cancel=cancel)
