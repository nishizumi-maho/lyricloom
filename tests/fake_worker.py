"""Test-only worker: echoes its payload, or fails when asked to."""
import os
import subprocess
import sys
import time
from pathlib import Path

from lyricloom.workers import emit, read_payload

payload = read_payload()
if payload.get("fail"):
    print("boom from worker", file=sys.stderr)
    sys.exit(1)
if payload.get("env_probe"):
    emit({"env": {k: os.environ.get(k, "") for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS")}})
    sys.exit(0)
if payload.get("sleep"):
    # Long enough to be cancelled, with a child process of its own so the tree kill is observable.
    pids = [str(os.getpid())]
    if payload.get("spawn_child"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        pids.append(str(child.pid))
    if payload.get("pidfile"):
        Path(payload["pidfile"]).write_text(",".join(pids), encoding="utf-8")
    time.sleep(float(payload["sleep"]))
    emit({"slept": True})
    sys.exit(0)
print("some library chatter on stdout")
emit({"echo": payload})
print("more chatter after the result")
