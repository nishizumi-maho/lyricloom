"""Help > Diagnostics: a copyable snapshot of versions, paths, models and GPU settings.

The snapshot is deliberately built from fixed facts. It never reads an API key or the contents of
``assemblyai.key`` and never dumps arbitrary settings that could contain one.
"""
from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import PySide6
from PySide6.QtCore import qVersion
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from .. import VERSION, config, gpu_runtime, runtime

APP_LOG_NAME = "app.log"


def app_log_path() -> Path:
    return config.LOG_DIR / APP_LOG_NAME


def setup_app_logging() -> None:
    """Adds one rotating file handler for the whole app, once per process."""
    root = logging.getLogger()
    if getattr(root, "_lyricloom_file_handler", None) is not None:
        return
    try:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(app_log_path(), maxBytes=1_000_000, backupCount=2,
                                      encoding="utf-8")
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    root._lyricloom_file_handler = handler   # type: ignore[attr-defined]
    logging.getLogger(__name__).info("%s %s started", config.APP_NAME, VERSION)


def tail_app_log(limit: int = 200) -> str:
    path = app_log_path()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(no app log yet)"
    return "\n".join(lines[-limit:]) if lines else "(no app log yet)"


def assemblyai_state() -> str:
    """Whether cloud transcription is on and whether a key is set. Never returns the key itself."""
    enabled = "on" if config.assemblyai_enabled() else "off"
    if not config.has_assemblyai_key():
        return f"{enabled} (no key set)"
    origin = "environment variable" if os.environ.get("ASSEMBLYAI_API_KEY") else "key file"
    return f"{enabled} ({origin} set; value not shown)"


def _runtimes_state() -> str:
    found = [name for name in config.GPU_BACKENDS if gpu_runtime.installed(name)]
    return ", ".join(found) if found else "none installed"


def _torch_state() -> str:
    try:
        import torch   # noqa: PLC0415 - optional and slow; Diagnostics only

        cuda = "yes" if torch.cuda.is_available() else "no"
        return f"torch {torch.__version__} (CUDA available: {cuda})"
    except Exception as exc:  # noqa: BLE001 - optional dependency
        return f"torch unavailable ({type(exc).__name__})"


def diagnostics_text(library_root: Path | None = None) -> str:
    models = runtime.status()
    library = Path(library_root) if library_root is not None else config.library_root()
    lines = [
        f"{config.APP_NAME} {VERSION}",
        f"Python {platform.python_version()} ({sys.executable})",
        f"Qt {qVersion()} / PySide6 {PySide6.__version__}",
        f"OS {platform.platform()}",
        "",
        "Paths",
        f"  data          {config.APP_DATA}",
        f"  settings      {config.SETTINGS_FILE}",
        f"  library       {library}",
        f"  vocals cache  {config.vocals_root()}",
        f"  work cache    {config.WORK_ROOT}",
        f"  models        {config.MODELS}",
        f"  app log       {app_log_path()}",
        f"  whisper-cli   {config.WHISPER_CLI}",
        "",
        "Models",
        f"  whisper       {'ready' if models.get('whisper') else 'missing'}",
        f"  separator     {'ready' if models.get('separator') else 'missing'}",
        f"  mms           {'ready' if models.get('mms') else 'missing'}",
        f"  mtl           {'ready' if models.get('mtl') else 'missing'}",
        f"  nltk          {'ready' if runtime._nltk_ready() else 'missing'}",
        f"  ffmpeg        {'ready' if runtime.check_ffmpeg() else 'missing'}",
        "",
        "GPU and WSL",
        f"  separator device setting  {config.SEPARATOR_DEVICE}",
        f"  CPU threads               {config.CPU_THREADS}",
        f"  acceleration in use       {gpu_runtime.acceleration_text()}",
        f"  Windows GPU runtimes      {_runtimes_state()}",
        f"  WSL enabled               {config.SEPARATOR_WSL_ENABLED}",
        f"  WSL distro                {config.SEPARATOR_WSL_DISTRO or '(not set)'}",
        f"  WSL python                {config.SEPARATOR_WSL_PYTHON or '(not set)'}",
        f"  alignment device          {config.ALIGN_DEVICE}",
        f"  singing model enabled     {config.MTL_ENABLED}",
        f"  {_torch_state()}",
        "",
        "Optional cloud",
        f"  AssemblyAI    {assemblyai_state()}",
        "",
        f"App log, last 200 lines ({app_log_path()})",
        tail_app_log(),
    ]
    return "\n".join(lines)


def open_local_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


class DiagnosticsDialog(QDialog):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"{config.APP_NAME} diagnostics")
        self.setMinimumSize(760, 560)
        layout = QVBoxLayout(self)
        intro = QLabel("Copy this text into a bug report. API keys and the contents of assemblyai.key "
                       "are never included.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlainText(text)
        layout.addWidget(self.text, 1)
        buttons = QHBoxLayout()
        open_data = QPushButton("Open data folder")
        open_data.clicked.connect(lambda: open_local_folder(config.APP_DATA))
        open_log = QPushButton("Open log folder")
        open_log.clicked.connect(lambda: open_local_folder(config.LOG_DIR))
        copy = QPushButton("Copy to clipboard")
        copy.clicked.connect(self._copy)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(open_data)
        buttons.addWidget(open_log)
        buttons.addStretch(1)
        buttons.addWidget(copy)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.text.toPlainText())
        QMessageBox.information(self, "Diagnostics", "Diagnostics copied to the clipboard.")
