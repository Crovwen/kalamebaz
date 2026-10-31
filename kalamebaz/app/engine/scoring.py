from __future__ import annotations


def word_points(length: int, difficulty: int, is_main: bool) -> int:
    """امتیاز پایه: کلمه‌های بلندتر و سخت‌تر امتیاز بیشتری دارند."""
    base = length + (max(1, min(5, difficulty)) - 1)
    return base if is_main else max(1, length // 2)


def points_after_hints(base: int, revealed: int) -> int:
    """هر حرف آشکارشده یک امتیاز از همان کلمه کم می‌کند (حداقل ۱)."""
    return max(1, base - max(0, revealed))
