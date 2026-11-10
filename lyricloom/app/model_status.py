"""Model-status checks used by the GUI.

``models.status`` may hash a multi-gigabyte file when its verification sidecar is missing, so a
GUI slot must never call it directly.  Every caller runs :func:`snapshot` inside a worker and
receives a plain ``{model id: state}`` mapping back in the GUI thread (FRB-04).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from .. import models

LOG = logging.getLogger(__name__)

OK_STATES = ("ready", "unverified")


def snapshot(specs: Iterable[models.ModelSpec], *, root: Path | None = None,
             cancel=None) -> dict[str, str]:
    """Checks each spec and returns ``{id: status}``; never raises for one bad model.

    ``cancel`` is an optional ``threading.Event``; the check stops between models so closing a
    window or the app does not have to wait for a whole sweep.
    """
    states: dict[str, str] = {}
    for spec in specs:
        if cancel is not None and cancel.is_set():
            break
        try:
            states[spec.id] = (models.status(spec) if root is None
                               else models.status(spec, root=root))
        except Exception as exc:  # noqa: BLE001 - one unreadable model must not break the sweep
            states[spec.id] = f"error:{type(exc).__name__}"
            LOG.warning("could not check model %s: %s", spec.id, exc)
    return states


def usable(state: str | None) -> bool:
    """True when processing accepts the model (``unverified`` is accepted, as the engine does)."""
    return state is not None and state not in ("missing", "corrupt") \
        and not str(state).startswith("error")
