"""Append-only JSONL journal of every cycle, plus per-day risk state."""

from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime, timezone
from pathlib import Path

from .risk import DailyState


def _default(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


class Journal:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.journal_file = self.data_dir / "journal.jsonl"
        self.daily_file = self.data_dir / "daily_state.json"

    def log(self, event: str, **payload) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **payload}
        with self.journal_file.open("a") as f:
            f.write(json.dumps(record, default=_default) + "\n")

    def load_daily(self, current_equity: float, today: date | None = None) -> DailyState:
        today_str = (today or date.today()).isoformat()
        if self.daily_file.exists():
            data = json.loads(self.daily_file.read_text())
            if data.get("date") == today_str:
                return DailyState(**data)
        state = DailyState(date=today_str, start_equity=current_equity)
        self.save_daily(state)
        return state

    def save_daily(self, state: DailyState) -> None:
        self.daily_file.write_text(json.dumps(dataclasses.asdict(state), indent=2))
