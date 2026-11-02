from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from pathlib import Path

from . import VERSION, config, runner, runtime


def _show(r: runner.TrackResult) -> None:
    detail = r.error if r.status == "failed" else f"{r.conf:.2f} {r.source}"
    print(f"{r.status:8} {detail:28} {r.path}", flush=True)


def _models(args) -> int:
    if args.action == "status":
        print(f"models directory: {config.MODELS}")
        for name, ok in runtime.status().items():
            print(f"  {name:10} {'ready' if ok else 'missing'}")
        print(f"  nltk       {'ready' if runtime._nltk_ready() else 'missing'}")
        print(f"  ffmpeg     {'ready' if runtime.check_ffmpeg() else 'missing'}")
        return 0
    what = args.what
    if what in ("all", "whisper"):
        print("whisper model (about 3 GB)…", flush=True)
        runtime.download_whisper(lambda done, total: None)
    if what in ("all", "separator"):
        print("vocal separator model (about 0.9 GB)…", flush=True)
        runtime.download_separator()
    if what in ("all", "mms"):
        print("forced-alignment model (about 1.2 GB)…", flush=True)
        runtime.download_mms()
    if what in ("all", "mtl"):
        print("English singing model (about 66 MB)…", flush=True)
        runtime.download_mtl(lambda done, total: None)
    if what in ("all", "nltk"):
        print("NLTK data…", flush=True)
        runtime.download_nltk()
    print("done")
    return 0


def _doctor() -> int:
    print(f"LyricLoom {VERSION}")
    print(f"python         {sys.version.split()[0]} ({sys.executable})")
    print(f"data           {config.APP_DATA}")
    print(f"library        {config.library_root()}")
    print(f"vocals cache   {config.vocals_root()}")
    print(f"models         {config.MODELS}")
    print(f"whisper-cli    {config.WHISPER_CLI} ({'ok' if Path(config.WHISPER_CLI).is_file() else 'missing'})")
    print(f"ffmpeg         {'ok' if runtime.check_ffmpeg() else 'missing'}")
    print(f"separator      {'ok' if runtime.separator_status() else 'missing'}")
    print(f"mms            {'ok' if runtime.mms_status() else 'missing'}")
    print(f"mtl            {'ok' if runtime.mtl_status() else 'missing'}")
    if config.IS_WINDOWS:
        print(f"wsl enabled    {config.SEPARATOR_WSL_ENABLED}")
        if config.SEPARATOR_WSL_ENABLED:
            print(f"wsl distro     {config.SEPARATOR_WSL_DISTRO}")
            print(f"wsl python     {config.SEPARATOR_WSL_PYTHON}")
    try:
        import torch

        print(f"torch          {torch.__version__} (cuda={torch.cuda.is_available()})")
    except Exception as exc:  # noqa: BLE001
        print(f"torch          missing ({exc})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lyricloom")
    ap.add_argument("--version", action="version", version=f"LyricLoom {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("process", help="write word-timed .lrc files next to the audio")
    p.add_argument("path", type=Path)
    p.add_argument("--force", action="store_true", help="reprocess tracks already done by this engine version")
    p.add_argument("--stage", choices=runner.STAGES, help="recompute this stage and the ones after it")
    p.add_argument("--no-cloud", action="store_true", help="never send audio to AssemblyAI")

    m = sub.add_parser("models", help="check or download the optional models")
    m.add_argument("action", choices=["status", "download"])
    m.add_argument("what", nargs="?", default="all",
                   choices=["all", "whisper", "separator", "mms", "mtl", "nltk"])

    sub.add_parser("doctor", help="print paths and check the installation")

    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    config.migrate_legacy_settings()
    if args.cmd == "models":
        return _models(args)
    if args.cmd == "doctor":
        return _doctor()

    path = args.path.resolve()
    library = config.library_root().resolve()
    if path != library and library not in path.parents:
        print(f"error: {path} is outside the library {library}", file=sys.stderr)
        print("hint: set the library in the app, or point LYRICLOOM_DATA_DIR at a test profile", file=sys.stderr)
        return 2
    if args.no_cloud:
        config.ASSEMBLYAI_ENABLED = False
    results = runner.process_all(runner.find_audio(path), args.force, args.stage, on_result=_show)
    counts = Counter(r.status for r in results)
    print("summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
