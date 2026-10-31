"""هسته‌ی بازی: شروع/پایان مرحله، حدس، راهنمایی، تایمر و بازیابی بعد از ری‌استارت."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict
from datetime import datetime, timezone
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbidden, TelegramRetryAfter

from app.bot import keyboards as kb
from app.config import Config
from app.db import repo
from app.engine.levelgen import generate_level
from app.engine.render import mmss, render_final, render_round
from app.engine.scoring import points_after_hints
from app.engine.state import RoundState
from app.keywords import RESERVED
from app.text.normalize import fa, normalize

log = logging.getLogger(__name__)
EDIT_MIN_GAP = 2.0      # حداقل فاصله دو ویرایش پیام مرحله (ثانیه)
EDIT_TIMER_GAP = 30.0   # بازخوانی دوره‌ای زمان باقی‌مانده


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def display_name(u) -> str:
    return (u.full_name or u.username or str(u.id)).strip()[:40]


class GameService:
    def __init__(self, bot: Bot, pool, cfg: Config):
        self.bot, self.pool, self.cfg = bot, pool, cfg
        self.active: dict[int, RoundState] = {}
        self.allow_names = cfg.allow_names
        self.rng = random.Random()
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._admin_cache: dict[tuple[int, int], tuple[float, bool]] = {}
        self._cool: dict[tuple[int, str], float] = {}
        self._warned: dict[int, float] = {}
        self._tasks: set[asyncio.Task] = set()

    # ---------- ابزار ----------
    def cooldown(self, chat_id: int, key: str, secs: float = 8.0) -> bool:
        """True یعنی هنوز در فاصله‌ی ممنوعیت است (پاسخ ندهیم)."""
        now = time.monotonic()
        if now - self._cool.get((chat_id, key), 0) < secs:
            return True
        self._cool[(chat_id, key)] = now
        return False

    async def is_admin(self, chat_id: int, user_id: int, anonymous: bool = False) -> bool:
        if anonymous or user_id == self.cfg.owner_id:
            return True
        hit = self._admin_cache.get((chat_id, user_id))
        if hit and time.monotonic() - hit[0] < 60:
            return hit[1]
        try:
            m = await self.bot.get_chat_member(chat_id, user_id)
            ok = m.status in ("creator", "administrator")
        except Exception:
            ok = False
        self._admin_cache[(chat_id, user_id)] = (time.monotonic(), ok)
        return ok

    async def settings_for(self, chat_id: int, title: str = "") -> dict:
        return await repo.ensure_chat(self.pool, chat_id, title)

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def warn_if_blind(self, chat_id: int) -> None:
        """اگر ربات پیام‌های عادی گروه را نمی‌بیند، راهنمای تنظیم به مدیر نمایش بده."""
        if time.monotonic() - self._warned.get(chat_id, -1e9) < 3600:
            return
        try:
            me = await self.bot.me()
            if me.can_read_all_group_messages:
                return
            m = await self.bot.get_chat_member(chat_id, me.id)
            if m.status == "administrator":
                return
        except Exception:
            return
        self._warned[chat_id] = time.monotonic()
        await self.bot.send_message(
            chat_id,
            "⚠️ <b>ربات نمی‌تواند حدس‌های شما را ببیند.</b>\n"
            "یکی از دو کار زیر را انجام دهید:\n"
            "۱) ربات را در همین گروه <b>مدیر</b> کنید (ساده‌ترین راه)؛\n"
            "۲) در BotFather دستور /setprivacy را بزنید، ربات را انتخاب و <b>Disable</b> کنید؛ "
            "سپس ربات را از گروه حذف و دوباره اضافه کنید.",
        )

    # ---------- شروع مرحله ----------
    async def start_round(self, chat_id: int, title: str = "") -> str | None:
        """None یعنی موفق؛ در غیر این صورت متن خطا."""
        async with self._locks[chat_id]:
            if chat_id in self.active:
                return "یک مرحله در حال اجراست. برای دیدن آن «وضعیت بازی» را بفرستید."
            s = await self.settings_for(chat_id, title)
            if not s["enabled"]:
                return "بازی در این گروه غیرفعال است. مدیر می‌تواند از «تنظیمات بازی» آن را روشن کند."
            seeds, words = await repo.recent_ids(self.pool, chat_id)
            level = await generate_level(
                lambda n, lo, hi, ex, lim: repo.fetch_seeds(self.pool, n, lo, hi, ex, self.allow_names, lim),
                lambda sigs: repo.fetch_candidates(self.pool, sigs, self.allow_names),
                letters=s["letters"], difficulty=s["difficulty"], main_count=s["main_count"],
                use_bonus=s["bonus"], recent_seed_ids=seeds, recent_word_ids=words,
                reserved=RESERVED, rng=self.rng,
            )
            if level is None:
                return "بانک واژگان برای ساخت مرحله کافی نیست. مالک ربات باید واژگان بیشتری وارد کند."
            state = await repo.create_round(self.pool, chat_id, level, s["duration"], s["hints"])
            try:
                msg = await self.bot.send_message(
                    chat_id, render_round(state, utcnow()), reply_markup=kb.running_kb(state.hints_max)
                )
            except (TelegramForbidden, TelegramBadRequest) as e:
                await repo.finish_round(self.pool, state, "stopped")
                log.warning("ارسال پیام مرحله ناموفق (%s): %s", chat_id, e)
                return "ربات اجازه‌ی ارسال پیام در این گروه را ندارد."
            state.message_id = msg.message_id
            state.last_edit = time.monotonic()
            state.last_text = render_round(state, utcnow())
            await repo.set_message(self.pool, state.id, msg.message_id)
            self.active[chat_id] = state
        self._spawn(self.warn_if_blind(chat_id))
        return None

    # ---------- حدس ----------
    async def handle_guess(self, chat_id: int, user, text: str) -> None:
        state = self.active.get(chat_id)
        if state is None or state.finished:
            return
        norm = normalize(text)
        w = state.words.get(norm)
        if w is None or w.found_by is not None:
            return
        if utcnow() >= state.ends_at:
            await self.finish(state, "time")
            return
        name = display_name(user)
        pts = points_after_hints(w.base_points, w.revealed)
        ok = await repo.claim_word(self.pool, w.id, chat_id, user.id, name, user.username, pts)
        if not ok:
            return
        w.found_by, w.found_name, w.points = user.id, name, pts
        p = state.players.setdefault(user.id, [name, 0, 0])
        p[0], p[1], p[2] = name, p[1] + pts, p[2] + 1
        extra = "" if w.is_main else " (کلمه اضافی)"
        state.last_event = f"🏅 {escape(name)} کلمه «{escape(w.display)}»{extra} را پیدا کرد و {fa(pts)} امتیاز گرفت."
        state.dirty = True
        if state.all_found:
            await self.finish(state, "completed")
        elif time.monotonic() - state.last_edit >= EDIT_MIN_GAP:
            await self._edit(state)

    # ---------- راهنمایی ----------
    async def use_hint(self, state: RoundState, user) -> str:
        if state.hints_max <= 0:
            return "راهنمایی در این گروه غیرفعال است."
        if state.hints_used >= state.hints_max:
            return "راهنمایی‌های این مرحله تمام شده است."
        cands = [w for w in state.mains if w.found_by is None and w.revealed < len(w.norm) - 1]
        if not cands:
            return "راهنمایی بیشتری ممکن نیست."
        low = min(w.revealed for w in cands)
        w = self.rng.choice([c for c in cands if c.revealed == low])
        w.revealed += 1          # بدون await بین بررسی و افزایش → رقابت ایجاد نمی‌شود
        state.hints_used += 1
        state.dirty = True
        await repo.record_hint(self.pool, state, w, user.id, display_name(user), user.username)
        if time.monotonic() - state.last_edit >= EDIT_MIN_GAP:
            await self._edit(state)
        return f"💡 یک حرف از یک کلمه‌ی {fa(len(w.norm))} حرفی آشکار شد."

    # ---------- ویرایش پیام ----------
    async def _edit(self, state: RoundState) -> None:
        async with state.lock:
            if state.finished or state.message_id is None:
                return
            text = render_round(state, utcnow())
            state.dirty = False
            state.last_edit = time.monotonic()
            if text == state.last_text:
                return
            try:
                await self.bot.edit_message_text(
                    text, chat_id=state.chat_id, message_id=state.message_id,
                    reply_markup=kb.running_kb(state.hints_max),
                )
                state.last_text = text
            except TelegramRetryAfter as e:
                state.dirty = True
                state.last_edit = time.monotonic() + e.retry_after
            except TelegramBadRequest as e:
                msg = str(e).lower()
                if "not modified" in msg:
                    state.last_text = text
                elif "not found" in msg or "can't be edited" in msg:
                    m = await self.bot.send_message(state.chat_id, text, reply_markup=kb.running_kb(state.hints_max))
                    state.message_id = m.message_id
                    state.last_text = text
                    await repo.set_message(self.pool, state.id, m.message_id)
                else:
                    log.warning("ویرایش پیام ناموفق: %s", e)
            except TelegramForbidden:
                state.finished = True
                self.active.pop(state.chat_id, None)
                await repo.finish_round(self.pool, state, "stopped")

    # ---------- پایان مرحله ----------
    async def finish(self, state: RoundState, reason: str) -> None:
        if state.finished:
            return
        state.finished = True
        self.active.pop(state.chat_id, None)
        try:
            await repo.finish_round(self.pool, state, reason)
        except Exception:
            log.exception("ثبت پایان مرحله ناموفق")
        s = await self.settings_for(state.chat_id)
        text = render_final(state, reason, s["show_board"])
        try:
            await self.bot.edit_message_text(
                text, chat_id=state.chat_id, message_id=state.message_id, reply_markup=kb.finished_kb()
            )
        except TelegramBadRequest:
            try:
                await self.bot.send_message(state.chat_id, text, reply_markup=kb.finished_kb())
            except Exception:
                log.warning("ارسال نتیجه مرحله ناموفق", exc_info=True)
        except (TelegramForbidden, TelegramRetryAfter):
            return
        if reason in ("time", "completed") and s["auto_next"] and s["enabled"]:
            self._spawn(self._auto_next(state.chat_id, s["interval"]))

    async def _auto_next(self, chat_id: int, delay: int) -> None:
        await asyncio.sleep(delay)
        if chat_id not in self.active:
            err = await self.start_round(chat_id)
            if err:
                log.info("شروع خودکار انجام نشد (%s): %s", chat_id, err)

    async def stop(self, chat_id: int, reason: str = "stopped") -> bool:
        state = self.active.get(chat_id)
        if not state:
            return False
        await self.finish(state, reason)
        return True

    # ---------- حلقه‌ی زمان‌بندی و بازیابی ----------
    async def recover(self) -> None:
        for st in await repo.load_active(self.pool):
            self.active[st.chat_id] = st
        log.info("مراحل فعال بازیابی‌شده: %d", len(self.active))

    async def run(self) -> None:
        """هر ۲ ثانیه: پایان مراحل منقضی، ویرایش‌های عقب‌افتاده و بازخوانی زمان."""
        while True:
            await asyncio.sleep(2)
            now_m = time.monotonic()
            for st in list(self.active.values()):
                try:
                    if utcnow() >= st.ends_at:
                        await self.finish(st, "time")
                    elif (st.dirty and now_m - st.last_edit >= EDIT_MIN_GAP) or now_m - st.last_edit >= EDIT_TIMER_GAP:
                        await self._edit(st)
                except Exception:
                    log.exception("خطا در حلقه‌ی زمان‌بندی")

    # ---------- متن‌های اطلاعاتی ----------
    def status_text(self, chat_id: int) -> str:
        st = self.active.get(chat_id)
        if not st:
            return "الان مرحله‌ی فعالی نیست. برای شروع بنویسید: <b>شروع بازی</b>"
        left = (st.ends_at - utcnow()).total_seconds()
        return (
            f"📊 مرحله {fa(st.number)} | پیشرفت {fa(st.found_mains)} از {fa(len(st.mains))} | "
            f"زمان باقی‌مانده {mmss(left)}"
        )

    async def me_text(self, chat_id: int, user) -> str:
        s = await repo.user_stats(self.pool, chat_id, user.id, utcnow())
        name = escape(display_name(user))
        if not s:
            return f"{name}، هنوز امتیازی ندارید. اولین کلمه را پیدا کنید! 🧩"
        c, g, p = s["chat"], s["global"], s["per"]
        return (
            f"👤 <b>{name}</b>\n"
            f"🏆 امتیاز در این گروه: {fa(c['points'])} (رتبه {fa(s['crank'])})\n"
            f"🌍 امتیاز کل: {fa(g['total_points'])} (رتبه جهانی {fa(s['grank'])})\n"
            f"🔤 کلمات پیداشده: {fa(g['words_found'])} | مراحل: {fa(g['rounds_played'])} | بردها: {fa(g['wins'])}\n"
            f"📅 امروز {fa(p['day'])} | این هفته {fa(p['week'])} | این ماه {fa(p['month'])}"
        )

    async def top_text(self, chat_id: int) -> str:
        rows = await repo.top_chat(self.pool, chat_id)
        if not rows:
            return "هنوز جدولی ساخته نشده است."
        medals = ["🥇", "🥈", "🥉"]
        lines = ["🏆 <b>برترین‌های گروه</b>", ""]
        for i, r in enumerate(rows):
            lines.append(f"{medals[i] if i < 3 else fa(i + 1) + '.'} {escape(r['name'])} — {fa(r['points'])}")
        return "\n".join(lines)

    async def global_text(self) -> str:
        rows = await repo.top_global(self.pool)
        if not rows:
            return "هنوز رتبه‌بندی جهانی خالی است."
        medals = ["🥇", "🥈", "🥉"]
        lines = ["🌍 <b>رتبه جهانی</b>", ""]
        for i, r in enumerate(rows):
            lines.append(f"{medals[i] if i < 3 else fa(i + 1) + '.'} {escape(r['name'])} — {fa(r['points'])}")
        return "\n".join(lines)

    async def stats_text(self, chat_id: int) -> str:
        r = await repo.chat_stats(self.pool, chat_id)
        return (
            "📈 <b>آمار گروه</b>\n"
            f"🧩 مراحل برگزارشده: {fa(r['rounds'])}\n"
            f"🔤 کلمات پیداشده: {fa(r['words'])}\n"
            f"👥 بازیکنان: {fa(r['players'])}"
        )

    HELP = (
        "🧩 <b>راهنمای کلمه‌باز</b>\n\n"
        "ربات چند حرف نشان می‌دهد؛ با آن‌ها کلمات مخفی را پیدا کنید. کافی است کلمه را "
        "<b>مستقیم در گروه</b> بنویسید؛ لازم نیست چیز دیگری اضافه کنید. اولین نفر امتیاز می‌گیرد.\n\n"
        "دستورات (بدون اسلش):\n"
        "• شروع بازی  • توقف بازی  • مرحله بعد\n"
        "• امتیاز من  • برترین‌ها  • رتبه جهانی\n"
        "• آمار بازی  • وضعیت بازی  • تنظیمات بازی\n\n"
        "💡 «راهنمایی» یک حرف آشکار می‌کند و ۱ امتیاز از همان کلمه کم می‌کند.\n"
        "توقف، مرحله بعد و تنظیمات مخصوص مدیران است."
    )
