"""Single PyInstaller entry point for the GUI and the frozen worker.

Both executables are built from the same Analysis so the worker modules are
present in the GUI executable too.  That matters on Linux: ``workers._worker_argv``
looks for a sibling ``LyricLoomWorker.exe`` (a Windows name) and otherwise falls
back to ``LyricLoom --worker <name>``.  Keeping one module graph makes that
fallback work without shipping a confusingly named ``.exe`` on Linux.

The executable name selects the mode:

* ``LyricLoom.exe`` / ``LyricLoom`` -> normal GUI (``lyricloom.app.main:run``),
  which already understands ``--worker <name>``.
* ``LyricLoomWorker.exe`` / ``LyricLoomWorker`` -> console worker
  (``lyricloom.workers.launcher:main``), with the worker name as argv[1].
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    executable = Path(sys.executable).stem.lower()
    if executable.endswith("worker"):
        from lyricloom.workers.launcher import main as worker_main

        worker_main()
        return

    from lyricloom.app.main import run

    run()


if __name__ == "__main__":
    main()
