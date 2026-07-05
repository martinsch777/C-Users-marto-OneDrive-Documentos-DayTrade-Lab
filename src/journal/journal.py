from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class JournalEntry:
    date: str
    asset: str
    setup: str
    entry: float | None
    stop: float | None
    take_profit: float | None
    size: float | None
    risk: float | None
    result: float | None
    entry_reason: str
    exit_reason: str = ""
    rules_followed: bool = True
    blocked: bool = False
    block_reason: str = ""
    screenshot_path: str = ""
    manual_notes: str = ""
    emotion_before: str = ""
    emotion_after: str = ""
    mistakes: str = ""


class Journal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, entry: JournalEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.exists() and self.path.stat().st_size > 0
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[item.name for item in fields(JournalEntry)],
            )
            if not exists:
                writer.writeheader()
            writer.writerow(asdict(entry))
