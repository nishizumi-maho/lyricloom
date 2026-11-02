"""Test-only worker: echoes its payload, or fails when asked to."""
import os
import sys

from lyricloom.workers import emit, read_payload

payload = read_payload()
if payload.get("fail"):
    print("boom from worker", file=sys.stderr)
    sys.exit(1)
if payload.get("env_probe"):
    emit({"env": {k: os.environ.get(k, "") for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS")}})
    sys.exit(0)
print("some library chatter on stdout")
emit({"echo": payload})
print("more chatter after the result")
