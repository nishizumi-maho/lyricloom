"""``python -m lyricloom`` starts the GUI; with CLI arguments it behaves like ``lyricloom``."""
from __future__ import annotations

import sys

if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
    from .workers.launcher import run

    run(sys.argv[2])
elif len(sys.argv) > 1 and sys.argv[1] in ("--process", "--open", "--redo"):
    # These are desktop-app options; the engine subcommands (process, models, doctor) stay below.
    from .app.main import run as run_gui

    run_gui()
elif len(sys.argv) > 1:
    from .cli import main

    sys.exit(main())
else:
    from .app.main import run

    run()
