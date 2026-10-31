"""مسیریابی پیام‌ها: ابتدا کلمات کلیدی مدیریتی، سپس حدس کلمه (بی‌صدا)."""
from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from app.bot import keyboards as kb
from app.config import Config
from app.engine.service import GameService, display_name
from app.keywords import ADMIN_ONLY, match_command, parse_suggestion
from app.settings_schema import CHOICES, DEFAULTS, cycle
from app.db import repo
from app.text.normalize import is_persian_word, normalize, normalize_display

log = logging.getLogger(__name__)
GROUP = {"group", "supergroup"}
SETTINGS_TITLE = "⚙️ <b>تنظیمات بازی</b>\nروی هر مورد بزنید تا مقدارش تغییر کند."


def build_router(svc: GameService, cfg: Config) -> Router:
    r = Router()

    async def _is_admin_msg(m: Message) -> bool:
        anon = bool(m.sender_chat and m.sender_chat.id == m.chat.id)
        return await svc.is_admin(m.chat.id, m.from_user.id if m.from_user else 0, anon)

    async def _can_start(chat_id: int, user_id: int, anonymous: bool = False) -> bool:
        s = await svc.settings_for(chat_id)
        return s["start_policy"] == "all" or await svc.is_admin(chat_id, user_id, anonymous)

    # ---------- چت خصوصی ----------
    @r.message(CommandStart(), F.chat.type == "private")
    async def start_private(m: Message):
        me = await m.bot.me()
        text = (
            "🧩 <b>به کلمه‌باز خوش آمدید!</b>\n\n"
            "بازی گروهی حدس کلمه با حروف فارسی.\n\n"
            "<b>راه‌اندازی:</b>\n"
            "۱) ربات را به گروه اضافه کنید.\n"
            "۲) ربات را <b>مدیر</b> گروه کنید تا حدس‌ها را ببیند "
            "(یا Privacy Mode را در BotFather خاموش کنید).\n"
            "۳) در گروه بنویسید: <b>شروع بازی</b>\n\n"
            "راهنمای کامل را با نوشتن «راهنمای بازی» در گروه ببینید."
        )
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        try:
            btn = InlineKeyboardButton(
                text="➕ افزودن به گروه", url=f"https://t.me/{me.username}?startgroup=true", style="success"
            )
        except Exception:
            btn = InlineKeyboardButton(text="➕ افزودن به گروه", url=f"https://t.me/{me.username}?startgroup=true")
        await m.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn]]))

    # ---------- افزوده‌شدن ربات به گروه ----------
    @r.my_chat_member(F.chat.type.in_(GROUP))
    async def added(ev: ChatMemberUpdated):
        if ev.new_chat_member.status in ("member", "administrator"):
            await svc.settings_for(ev.chat.id, ev.chat.title or "")
            await ev.bot.send_message(
                ev.chat.id,
                "🧩 <b>کلمه‌باز آماده است!</b>\nبرای شروع بنویسید: <b>شروع بازی</b>\nراهنما: «راهنمای بازی»",
                reply_markup=kb.idle_kb(),
            )
            await svc.warn_if_blind(ev.chat.id)

    # ---------- پیام‌های گروه ----------
    @r.message(F.chat.type.in_(GROUP), F.text)
    async def group_text(m: Message):
        if m.from_user is None or m.from_user.is_bot:
            if not (m.sender_chat and m.sender_chat.id == m.chat.id):
                return
        text = m.text or ""
        cmd = match_command(text)          # ۱) کلمات مدیریتی همیشه قبل از حدس
        if cmd:
            await run_command(m, cmd)
            return
        sug = parse_suggestion(text)       # ۲) پیشنهاد کلمه
        if sug:
            await suggest(m, sug)
            return
        if m.from_user is not None and not m.from_user.is_bot:        # ۳) حدس تک‌کلمه‌ای؛ هیچ واکنش اضافی
            await svc.handle_guess(m.chat.id, m.from_user, text)

    async def run_command(m: Message, cmd: str):
        cid = m.chat.id
        user = m.from_user
        anon = bool(m.sender_chat and m.sender_chat.id == cid)
        if cmd in ADMIN_ONLY and not await _is_admin_msg(m):
            if not svc.cooldown(cid, "deny"):
                await m.reply("این دستور مخصوص مدیران گروه است.")
            return
        if cmd == "start":
            if not await _can_start(cid, user.id if user else 0, anon):
                if not svc.cooldown(cid, "deny"):
                    await m.reply("در این گروه فقط مدیران می‌توانند بازی را شروع کنند.")
                return
            err = await svc.start_round(cid, m.chat.title or "")
            if err and not svc.cooldown(cid, "err", 5):
                await m.reply(err)
        elif cmd == "stop":
            if not await svc.stop(cid):
                if not svc.cooldown(cid, "none"):
                    await m.reply("مرحله‌ی فعالی وجود ندارد.")
        elif cmd == "next":
            await svc.stop(cid, "skipped")
            err = await svc.start_round(cid, m.chat.title or "")
            if err and not svc.cooldown(cid, "err", 5):
                await m.reply(err)
        elif cmd == "settings":
            s = await svc.settings_for(cid, m.chat.title or "")
            await m.answer(SETTINGS_TITLE, reply_markup=kb.settings_kb(s))
        elif svc.cooldown(cid, cmd):       # دستورهای اطلاعاتی: ضدشلوغی
            return
        elif cmd == "help":
            await m.reply(svc.HELP, reply_markup=kb.help_kb())
        elif cmd == "me" and user:
            await m.reply(await svc.me_text(cid, user))
        elif cmd == "top":
            await m.reply(await svc.top_text(cid))
        elif cmd == "global":
            await m.reply(await svc.global_text())
        elif cmd == "stats":
            await m.reply(await svc.stats_text(cid))
        elif cmd == "status":
            await m.reply(svc.status_text(cid))

    async def suggest(m: Message, word: str):
        norm = normalize(word)
        if not is_persian_word(norm) or not 3 <= len(norm) <= 12 or m.from_user is None:
            return
        n = await svc.pool.fetchval(
            "SELECT count(*) FROM word_suggestions WHERE user_id=$1 AND created_at > now() - interval '1 day'", m.from_user.id
        )
        if n >= 5:
            await m.reply("سقف پیشنهاد روزانه (۵ کلمه) تمام شده است.")
            return
        if await svc.pool.fetchval("SELECT 1 FROM words WHERE norm=$1", norm):
            await m.reply("این کلمه از قبل در بانک واژگان هست.")
            return
        async with svc.pool.acquire() as conn:
            await repo.upsert_user(conn, m.from_user.id, display_name(m.from_user), m.from_user.username)
            await conn.execute(
                "INSERT INTO word_suggestions(norm,display,user_id,chat_id) VALUES($1,$2,$3,$4)",
                norm, normalize_display(word), m.from_user.id, m.chat.id,
            )
        await m.reply("✅ پیشنهاد شما ثبت شد و بعد از بررسی مالک ربات اضافه می‌شود.")

    # ---------- دکمه‌های بازی ----------
    @r.callback_query(F.data.startswith("g:"))
    async def game_cb(q: CallbackQuery):
        if q.message is None:
            await q.answer()
            return
        cid, uid, act = q.message.chat.id, q.from_user.id, q.data[2:]
        if act in ("stop", "next") and not await svc.is_admin(cid, uid):
            await q.answer("این گزینه مخصوص مدیران است.", show_alert=True)
            return
        if act == "start":
            if not await _can_start(cid, uid):
                await q.answer("فقط مدیران می‌توانند بازی را شروع کنند.", show_alert=True)
                return
            err = await svc.start_round(cid, q.message.chat.title or "")
            await q.answer(err or "مرحله شروع شد!", show_alert=bool(err))
        elif act == "next":
            await svc.stop(cid, "skipped")
            err = await svc.start_round(cid, q.message.chat.title or "")
            await q.answer(err or "مرحله جدید شروع شد!", show_alert=bool(err))
        elif act == "stop":
            ok = await svc.stop(cid)
            await q.answer("بازی متوقف شد." if ok else "مرحله‌ی فعالی نیست.")
        elif act == "hint":
            st = svc.active.get(cid)
            await q.answer(await svc.use_hint(st, q.from_user) if st else "مرحله‌ی فعالی نیست.", show_alert=True)
        elif act == "status":
            await q.answer(_plain(svc.status_text(cid)), show_alert=True)
        elif act == "top":
            await q.answer()
            if not svc.cooldown(cid, "top"):
                await q.message.answer(await svc.top_text(cid))
        elif act == "stats":
            await q.answer()
            if not svc.cooldown(cid, "stats"):
                await q.message.answer(await svc.stats_text(cid))
        elif act == "help":
            await q.answer()
            if not svc.cooldown(cid, "help"):
                await q.message.answer(svc.HELP, reply_markup=kb.help_kb())
        else:
            await q.answer()

    # ---------- دکمه‌های تنظیمات ----------
    @r.callback_query(F.data.startswith("s:"))
    async def settings_cb(q: CallbackQuery):
        if q.message is None:
            await q.answer()
            return
        cid, key = q.message.chat.id, q.data[2:]
        if not await svc.is_admin(cid, q.from_user.id):
            await q.answer("فقط مدیران می‌توانند تنظیمات را تغییر دهند.", show_alert=True)
            return
        s = await svc.settings_for(cid)
        if key == "close":
            await q.message.delete()
            await q.answer("ذخیره شد.")
            return
        s = dict(DEFAULTS) if key == "reset" else cycle(s, key) if key in CHOICES else s
        await repo.save_settings(svc.pool, cid, s)
        try:
            await q.message.edit_text(SETTINGS_TITLE, reply_markup=kb.settings_kb(s))
        except TelegramBadRequest:
            pass
        await q.answer("اعمال شد.")

    return r


def _plain(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", html)[:200]
