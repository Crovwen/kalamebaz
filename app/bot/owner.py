"""پنل خصوصی مالک ربات (فقط شناسه عددی OWNER_ID)."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from html import escape

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot import keyboards as kb
from app.config import Config
from app.db import repo
from app.engine.service import GameService
from app.keywords import compact_key
from app.logbuf import recent_errors
from app.text.normalize import is_persian_word, letters_signature, normalize, normalize_display
from app.words import importer

log = logging.getLogger(__name__)
PANEL_KEYS = {compact_key("پنل مدیریت"), compact_key("پنل")}


def build_owner_router(svc: GameService, cfg: Config) -> Router:
    r = Router()
    is_owner = F.from_user.id == cfg.owner_id
    private = F.chat.type == "private"
    state: dict[str, str] = {}   # حالت گفتگوی مالک: add | dis | bc

    @r.message(private, is_owner, F.text.func(lambda t: compact_key(t) in PANEL_KEYS))
    async def panel(m: Message):
        state.clear()
        await m.answer("🛠 <b>پنل مدیریت</b>", reply_markup=kb.owner_kb())

    @r.message(private, is_owner, F.document)
    async def doc(m: Message):
        """فایل واژگان؛ کپشن اختیاری: source=نام category=common puzzle=1 mode=freq"""
        opts = dict(p.split("=", 1) for p in (m.caption or "").split() if "=" in p)
        buf = io.BytesIO()
        await m.bot.download(m.document, destination=buf)
        tuples, rep = importer.prepare(
            importer.iter_rows(buf.getvalue(), m.document.file_name or "words.txt"),
            source=opts.get("source", "upload"), category=opts.get("category", "common"),
            trust_puzzle=opts.get("puzzle") in ("1", "true"),
        )
        if opts.get("mode") == "freq":
            await importer.update_freq(svc.pool, tuples, rep)
        else:
            await importer.upsert_words(svc.pool, tuples, rep, filename=m.document.file_name or "", source=opts.get("source", "upload"))
        await m.answer("📥 " + rep.text())

    @r.message(private, is_owner, F.text, ~F.text.startswith("/"))
    async def text(m: Message):
        mode = state.pop("mode", None)
        if mode in ("add", "dis"):
            words = [normalize(w) for w in m.text.replace("،", " ").split()]
            ok = [w for w in words if is_persian_word(w) and 2 <= len(w) <= 14]
            if mode == "add":
                tuples = [
                    (w, normalize_display(w), len(w), letters_signature(w), 0, 3, "common", ["manual"], 3 <= len(w) <= 8, True)
                    for w in ok
                ]
                rep = importer.Report(total=len(words), accepted=len(ok))
                await importer.upsert_words(svc.pool, tuples, rep, filename="manual", source="manual")
                await m.answer(f"➕ {importer.Report.text(rep)}")
            else:
                res = await svc.pool.execute(
                    "UPDATE words SET status='disabled', puzzle_ok=FALSE, bonus_ok=FALSE WHERE norm = ANY($1::text[])", ok
                )
                await m.answer(f"🚫 {res}")
        elif mode == "bc":
            await broadcast(m, m.html_text)

    async def broadcast(m: Message, html: str):
        ids = [x["id"] for x in await svc.pool.fetch("SELECT id FROM chats")]
        sent = failed = 0
        for cid in ids:
            try:
                await m.bot.send_message(cid, "📣 " + html)
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)
        await m.answer(f"ارسال‌شده: {sent} | ناموفق: {failed}")

    @r.callback_query(F.data.startswith("o:"), F.from_user.id == cfg.owner_id)
    async def cb(q: CallbackQuery):
        act = q.data[2:]
        msg = q.message
        await q.answer()
        if act == "stats":
            g = await repo.global_stats(svc.pool)
            await msg.answer(
                f"📊 کاربران: {g['users']} | گروه‌ها: {g['chats']} | مراحل: {g['rounds']}\n"
                f"📚 مدخل‌ها: {g['words']} | مناسب معما: {g['puzzle_words']} | پیشنهاد در انتظار: {g['pending']}\n"
                f"🎮 مراحل فعال اکنون: {len(svc.active)}"
            )
        elif act == "words":
            await msg.answer(
                "📚 " + await importer.stats(svc.pool) +
                "\n\nبرای ورود فایل، آن را (TXT/CSV/JSON) برای من بفرستید. کپشن اختیاری:\n"
                "<code>source=نام category=common puzzle=1 mode=freq</code>"
            )
        elif act in ("add", "dis", "bc"):
            state["mode"] = act
            await msg.answer({"add": "کلمات را (با فاصله یا خط جدید) بفرستید.",
                              "dis": "کلماتی را که باید غیرفعال شوند بفرستید.",
                              "bc": "متن اطلاعیه را بفرستید؛ به همه گروه‌ها ارسال می‌شود."}[act])
        elif act == "names":
            svc.allow_names = not svc.allow_names
            await msg.answer(f"🏷 نام‌های خاص: {'روشن' if svc.allow_names else 'خاموش'} (تا ری‌استارت بعدی؛ برای دائمی‌شدن ALLOW_NAMES را تنظیم کنید)")
        elif act == "err":
            errs = recent_errors()
            await msg.answer("🐞 " + ("\n".join(escape(e)[:300] for e in errs) if errs else "خطایی ثبت نشده است."))
        elif act == "sugg":
            rows = await svc.pool.fetch("SELECT id, display FROM word_suggestions WHERE status='pending' ORDER BY id LIMIT 5")
            if not rows:
                await msg.answer("پیشنهادی در انتظار نیست.")
            for x in rows:
                await msg.answer(f"«{escape(x['display'])}»", reply_markup=kb.suggestion_kb(x["id"]))
        elif act.startswith(("ap:", "rj:")):
            kind, sid = act.split(":")
            row = await svc.pool.fetchrow(
                "UPDATE word_suggestions SET status=$2 WHERE id=$1 AND status='pending' RETURNING norm, display",
                int(sid), "approved" if kind == "ap" else "rejected",
            )
            if row and kind == "ap":
                n = row["norm"]
                await svc.pool.execute(
                    "INSERT INTO words(norm,display,length,letters_sig,sources,puzzle_ok) VALUES($1,$2,$3,$4,'{suggested}',$5) "
                    "ON CONFLICT (norm) DO NOTHING", n, row["display"], len(n), letters_signature(n), 3 <= len(n) <= 8,
                )
            await msg.edit_text(("✅ تأیید شد" if kind == "ap" else "❌ رد شد") + (f": {escape(row['display'])}" if row else ""))
        elif act == "backup":
            sc = await svc.pool.fetch(
                "SELECT cm.chat_id, cm.user_id, u.name, cm.points, cm.words, cm.rounds, cm.wins "
                "FROM chat_members cm JOIN users u ON u.id=cm.user_id"
            )
            data = json.dumps([dict(x) for x in sc], ensure_ascii=False).encode()
            await msg.answer_document(BufferedInputFile(data, "scores.json"))
            ws = await svc.pool.fetch(
                "SELECT norm, display, freq, difficulty, category, puzzle_ok, bonus_ok, status FROM words ORDER BY id"
            )
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(["word", "display", "freq", "difficulty", "category", "puzzle_ok", "bonus_ok", "status"])
            for x in ws:
                w.writerow(list(x.values()))
            await msg.answer_document(BufferedInputFile(out.getvalue().encode("utf-8-sig"), "words.csv"))

    return r
