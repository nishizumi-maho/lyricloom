"""``python -m lyricloom`` starts the GUI; with CLI arguments it behaves like ``lyricloom``."""
from __future__ import annotations

import sys

if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
    from .workers.launcher import run

    run(sys.argv[2])
elif len(sys.argv) > 1:
    from .cli import main

    sys.exit(main())
else:
    from .app.main import run

    run()
