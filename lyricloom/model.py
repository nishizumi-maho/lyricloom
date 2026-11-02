from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TrackMeta:
    path: Path
    artist: str
    title: str
    album: str
    duration_s: float
    lang: str  # "ja" | "pt" | "en" | "other"


@dataclass
class Segment:
    text: str
    start_ms: int | None
    end_ms: int | None
    conf: float = 1.0


@dataclass
class Line:
    start_ms: int | None
    segments: list[Segment]
    conf: float = 1.0

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.segments)


@dataclass
class Candidate:
    source: str
    text: str
    score: float = 0.0
    synced: list[Line] | None = None
    url: str = ""


@dataclass
class Word:
    text: str
    start_ms: int
    end_ms: int
    prob: float


@dataclass
class Transcript:
    lang: str
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class LrcDoc:
    meta: dict[str, str] = field(default_factory=dict)
    lines: list[Line] = field(default_factory=list)
