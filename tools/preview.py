"""Plays a track and shows its enhanced .lrc karaoke-style in the terminal, so word timing can be
judged by ear without opening the karaoke window.

Usage: python tools/preview.py <audio> [--from SECONDS] [--lrc OTHER.lrc]"""
import argparse
import sys
import time
from pathlib import Path

import sounddevice as sd
import soundfile as sf

from lyricloom.lrc import parse_lrc

DIM, BRIGHT, RESET = "\x1b[2m", "\x1b[1;96m", "\x1b[0m"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", type=Path)
    ap.add_argument("--from", dest="start", type=float, default=0.0)
    ap.add_argument("--lrc", type=Path, help="lyrics file to show (default: <audio>.lrc)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    doc = parse_lrc((args.lrc or args.audio.with_suffix(".lrc")).read_text(encoding="utf-8"))
    data, sr = sf.read(str(args.audio), dtype="float32")
    offset_ms = int(args.start * 1000)
    sd.play(data[int(args.start * sr):], sr)
    t0 = time.perf_counter()
    try:
        for line in doc.lines:
            if line.start_ms is None or (line.segments[-1].end_ms or line.start_ms) < offset_ms:
                continue
            timed = line.segments[0].start_ms is not None
            while (time.perf_counter() - t0) * 1000 + offset_ms < (line.start_ms or 0):
                time.sleep(0.005)
            if not timed:
                print(f"{BRIGHT}{line.text}{RESET}  (line only)")
                continue
            for i, seg in enumerate(line.segments):
                while (time.perf_counter() - t0) * 1000 + offset_ms < seg.start_ms:
                    time.sleep(0.005)
                sung = "".join(s.text for s in line.segments[: i + 1])
                rest = "".join(s.text for s in line.segments[i + 1:])
                print(f"\r{BRIGHT}{sung}{RESET}{DIM}{rest}{RESET}", end="", flush=True)
            print()
        sd.wait()
    except KeyboardInterrupt:
        sd.stop()


if __name__ == "__main__":
    main()
