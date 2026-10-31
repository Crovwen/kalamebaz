"""ساخت متن پیام مرحله (HTML تلگرام)."""
from __future__ import annotations

from datetime import datetime
from html import escape

from app.engine.state import RoundState, RWord
from app.text.normalize import fa

LINE = "━━━━━━━━━━━━"
REASONS = {
    "completed": "🎉 همه کلمات پیدا شد!",
    "time": "⏰ زمان مرحله تمام شد.",
    "stopped": "⏹ بازی متوقف شد.",
    "skipped": "⏭ این مرحله رد شد.",
}


def mmss(seconds: float) -> str:
    s = max(0, int(seconds))
    return fa(f"{s // 60:02d}:{s % 60:02d}")


def _spaced(norm: str) -> str:
    return " ".join(norm)


def _cell(w: RWord) -> str:
    if w.found_by is not None:
        return f"{_spaced(w.norm)} ✅"
    shown = list(w.norm[: w.revealed]) + ["□"] * (len(w.norm) - w.revealed)
    return " ".join(shown)


def _sorted_mains(state: RoundState) -> list[RWord]:
    return sorted(state.mains, key=lambda w: (len(w.norm), w.norm))


def render_round(state: RoundState, now: datetime) -> str:
    left = (state.ends_at - now).total_seconds()
    out = [
        f"🧩 <b>کلمه‌باز | مرحله {fa(state.number)}</b>",
        "",
        "با حروف زیر کلمات مخفی را پیدا کنید:",
        "",
        "🔤 <b>" + " • ".join(state.letters) + "</b>",
        "",
        "کلمات این مرحله:",
        "",
    ]
    for w in _sorted_mains(state):
        out.append(f"{fa(len(w.norm))} حرفی: {_cell(w)}")
    out += [
        "",
        LINE,
        "",
        f"🔎 پیشرفت: {fa(state.found_mains)} از {fa(len(state.mains))}",
        f"⏳ زمان باقی‌مانده: {mmss(left)}",
    ]
    if state.hints_max > 0:
        out.append(f"💡 راهنمایی: {fa(state.hints_max - state.hints_used)} از {fa(state.hints_max)}")
    if state.bonuses:
        found = sum(1 for w in state.bonuses if w.found_by is not None)
        out.append(f"➕ کلمات اضافی پیداشده: {fa(found)}")
    if state.last_event:
        out += ["", state.last_event]
    out += ["", "🏆 برای کسب امتیاز، کلمه موردنظر را مستقیماً داخل گروه ارسال کنید."]
    return "\n".join(out)


def render_final(state: RoundState, reason: str, show_board: bool = True) -> str:
    out = [f"🏁 <b>پایان مرحله {fa(state.number)}</b>", REASONS.get(reason, ""), ""]
    for w in _sorted_mains(state):
        if w.found_by is not None:
            out.append(f"✅ {escape(w.display)} — {escape(w.found_name or '')} (+{fa(w.points)})")
        else:
            out.append(f"❌ {escape(w.display)}")
    bonus = [w for w in state.bonuses if w.found_by is not None]
    if bonus:
        out += ["", "➕ اضافی: " + "، ".join(escape(w.display) for w in bonus)]
    if show_board and state.players:
        out += ["", "🏆 نتیجه مرحله:"]
        medals = ["🥇", "🥈", "🥉"]
        ranked = sorted(state.players.values(), key=lambda p: (-p[1], p[0]))[:5]
        for i, (name, pts, cnt) in enumerate(ranked):
            out.append(f"{medals[i] if i < 3 else '▫️'} {escape(name)} — {fa(pts)} امتیاز ({fa(cnt)} کلمه)")
    elif not state.players:
        out += ["", "این مرحله کسی کلمه‌ای پیدا نکرد."]
    return "\n".join(out)
