from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RWord:
    id: int  # شناسه ردیف round_words
    word_id: int
    norm: str
    display: str
    is_main: bool
    base_points: int
    revealed: int = 0
    found_by: int | None = None
    found_name: str | None = None
    points: int = 0


@dataclass
class RoundState:
    id: int
    chat_id: int
    number: int
    letters: list[str]
    ends_at: datetime
    hints_max: int
    words: dict[str, RWord]
    message_id: int | None = None
    hints_used: int = 0
    last_event: str | None = None
    players: dict[int, list] = field(default_factory=dict)  # uid -> [name, points, count]
    dirty: bool = False
    last_edit: float = 0.0
    last_text: str = ""
    finished: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def mains(self) -> list[RWord]:
        return [w for w in self.words.values() if w.is_main]

    @property
    def bonuses(self) -> list[RWord]:
        return [w for w in self.words.values() if not w.is_main]

    @property
    def found_mains(self) -> int:
        return sum(1 for w in self.mains if w.found_by is not None)

    @property
    def all_found(self) -> bool:
        return all(w.found_by is not None for w in self.mains)
