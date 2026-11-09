from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from . import VERSION, cache, config, models, runner, runtime

LEGACY_DOWNLOADS = ("all", "whisper", "separator", "mms", "mtl", "nltk")


def _show(r: runner.TrackResult) -> None:
    detail = r.error if r.status == "failed" else f"{r.conf:.2f} {r.source}"
    print(f"{r.status:8} {detail:28} {r.path}", flush=True)


def _print_models() -> None:
    rows = models.all_specs()
    print(f"{'stage':10} {'id':34} {'size':>9}  {'status':10} chosen for")
    for spec in rows:
        state = models.status(spec)
        chosen = models.choices_for(spec)
        if not chosen and spec.default:
            chosen = ["default (implicit)"]
        chosen_text = ", ".join(chosen)
        marker = " *" if spec.default else "  "
        print(f"{spec.stage:10} {spec.id + marker:34} {runtime.human_size(spec.total_size):>9}  "
              f"{state:10} {chosen_text}")
    if not any(spec.custom for spec in rows):
        print("\n* catalog default. Add a custom model with `lyricloom models add <stage> <path>`.")


def _download(args) -> int:
    what = list(getattr(args, "what", []) or [])
    if not what:
        what = ["all"]
    if what == ["all-defaults"] or what == ["all"]:
        results = runtime.download_all()
        for model_id, result in results.items():
            print(f"{model_id:34} {result}")
        return 0 if all(v in ("ready", "skipped") for v in results.values()) else 1
    if any(name in LEGACY_DOWNLOADS for name in what):
        results = {}
        for name in what:
            try:
                if name in ("all", "whisper"):
                    results["whisper"] = _dl(name, runtime.download_whisper)
                if name in ("all", "separator"):
                    results["separator"] = _dl(name, runtime.download_separator)
                if name in ("all", "mms"):
                    results["mms"] = _dl(name, runtime.download_mms)
                if name in ("all", "mtl"):
                    results["mtl"] = _dl(name, runtime.download_mtl)
                if name in ("all", "nltk"):
                    results["nltk"] = _dl(name, runtime.download_nltk)
            except Exception as exc:  # noqa: BLE001 - one failed download does not abort the rest
                results[name] = f"error: {exc}"
        for name, result in results.items():
            print(f"{name:34} {result}")
        return 0 if all(v == "ready" for v in results.values()) else 1
    failed = False
    for model_id in what:
        try:
            runtime.download_model(model_id)
            print(f"{model_id:34} ready")
        except Exception as exc:  # noqa: BLE001 - report, continue with the remaining ids
            failed = True
            print(f"{model_id:34} error: {exc}")
    return 1 if failed else 0


def _dl(name: str, func) -> str:
    func(lambda done, total: None)
    return "ready"


def _verify(args) -> int:
    what = list(getattr(args, "what", []) or [])
    specs = [models.find(model_id) for model_id in what] if what else models.all_specs()
    if any(spec is None for spec in specs):
        print("unknown model id; use `lyricloom models list`", file=sys.stderr)
        return 2
    bad = False
    for spec in specs:
        state = runtime.model_status(spec.id, verify=True)
        bad = bad or state not in ("ready", "unverified")
        print(f"{spec.id:34} {state}")
    return 1 if bad else 0


def _repair(args) -> int:
    what = list(getattr(args, "what", []) or [])
    if len(what) != 1:
        print("usage: lyricloom models repair <id>", file=sys.stderr)
        return 2
    spec = models.find(what[0])
    if spec is None:
        print(f"unknown model {what[0]!r}; use `lyricloom models list`", file=sys.stderr)
        return 2
    try:
        runtime.repair(spec)
    except Exception as exc:  # noqa: BLE001 - report the download failure to the user
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{spec.id:34} {models.status(spec)}")
    return 0


def _use(args) -> int:
    what = list(getattr(args, "what", []) or [])
    if len(what) != 2:
        print("usage: lyricloom models use <stage> <id> [--lang <code>]", file=sys.stderr)
        return 2
    stage, model_id = what
    try:
        models.use(stage, model_id, lang=args.lang)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    target = f"language {args.lang!r}" if args.lang else "the default"
    print(f"{stage} now uses {model_id} for {target}")
    return 0


def _add(args) -> int:
    what = list(getattr(args, "what", []) or [])
    if len(what) != 2:
        print("usage: lyricloom models add <stage> <path|name> [--label <label>]", file=sys.stderr)
        return 2
    stage, source = what
    try:
        spec = models.add(stage, source, label=args.label)
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"added {spec.id} ({stage}, {runtime.human_size(spec.total_size)}); "
          f"choose it with `lyricloom models use {stage} {spec.id}`")
    return 0


def _models(args) -> int:
    action = args.action
    if action == "status":
        print(f"models directory: {config.MODELS}")
        for name, ok in runtime.status().items():
            print(f"  {name:10} {'ready' if ok else 'missing'}")
        print(f"  nltk       {'ready' if runtime._nltk_ready() else 'missing'}")
        print(f"  ffmpeg     {'ready' if runtime.check_ffmpeg() else 'missing'}")
        return 0
    if action == "list":
        _print_models()
        return 0
    if action == "download":
        return _download(args)
    if action == "verify":
        return _verify(args)
    if action == "repair":
        return _repair(args)
    if action in ("use", "add"):
        return _use(args) if action == "use" else _add(args)
    return 2


def _cache(args) -> int:
    action = args.action
    if action == "status":
        report = cache.size_report()
        print(f"work cache: {report['files']} track folder(s), "
              f"{runtime.human_size(report['bytes'])} in {report['root']}")
        return 0
    max_bytes = int(args.max_gb * 1024 ** 3) if args.max_gb is not None else 0
    before = cache.size_report()
    result = cache.prune(max_bytes)
    print(f"work cache: removed {result['removed']} folder(s), freed "
          f"{runtime.human_size(result['freed'])}; {runtime.human_size(result['remaining'])} left "
          f"(was {runtime.human_size(before['bytes'])})")
    return 0


def _doctor() -> int:
    print(f"LyricLoom {VERSION}")
    print(f"python         {sys.version.split()[0]} ({sys.executable})")
    print(f"data           {config.APP_DATA}")
    print(f"library        {config.library_root()}")
    print(f"vocals cache   {config.vocals_root()}")
    print(f"models         {config.MODELS}")
    print(f"whisper-cli    {config.whisper_cli()} ({'ok' if config.whisper_cli().is_file() else 'missing'})")
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

    m = sub.add_parser("models", help="list, choose, verify, repair or download the optional models")
    m.add_argument("action",
                   choices=["list", "status", "download", "verify", "repair", "use", "add"])
    m.add_argument("what", nargs="*", default=[],
                   help="model id(s), <stage> <id>, <stage> <path|name>, or an old download name")
    m.add_argument("--lang", help="with `use`: write a per-language choice")
    m.add_argument("--label", help="with `add`: a display label for the custom model")

    sub.add_parser("doctor", help="print paths and check the installation")

    c = sub.add_parser("cache", help="report or clean the work cache")
    c.add_argument("action", nargs="?", choices=["status", "clean"], default="status",
                   help="status (default) or clean")
    c.add_argument("--max-gb", type=float,
                   help="with clean: keep at most this many gigabytes (default: remove all)")

    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if config.migrate_legacy_settings():
        print(f"migrated LyricsBoca settings and data to {config.APP_DATA}", file=sys.stderr)
    if args.cmd == "models":
        return _models(args)
    if args.cmd == "cache":
        return _cache(args)
    if args.cmd == "doctor":
        return _doctor()

    path = args.path.resolve()
    library = config.library_root().resolve()
    if path != library and library not in path.parents:
        print(f"error: {path} is outside the library {library}", file=sys.stderr)
        print("hint: set the library in the app, or point LYRICLOOM_DATA_DIR at a test profile", file=sys.stderr)
        return 2
    results = runner.process_all(runner.find_audio(path), args.force, args.stage, on_result=_show,
                                 allow_cloud=False if args.no_cloud else None)
    counts = Counter(r.status for r in results)
    print("summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if counts.get("failed"):
        for r in results:
            if r.status == "failed":
                print(f"failed: {r.path}: {r.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
