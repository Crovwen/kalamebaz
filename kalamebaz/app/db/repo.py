"""دسترسی به دیتابیس (SQL ساده و صریح)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine.levelgen import Level, WordRow
from app.engine.scoring import word_points
from app.engine.state import RoundState, RWord
from app.settings_schema import merge

TEHRAN = ZoneInfo("Asia/Tehran")
_ROW = "id, norm, display, length, difficulty, puzzle_ok, category"


def _word(r) -> WordRow:
    return WordRow(r["id"], r["norm"], r["display"], r["length"], r["difficulty"], r["puzzle_ok"], r["category"])


def period_starts(now: datetime) -> tuple[datetime, datetime, datetime]:
    """شروع امروز، هفته (از شنبه) و ماه میلادی به وقت تهران."""
    t = now.astimezone(TEHRAN)
    day = t.replace(hour=0, minute=0, second=0, microsecond=0)
    week = day - timedelta(days=(t.weekday() + 2) % 7)
    month = day.replace(day=1)
    return day, week, month


# ---------- کاربر و گروه ----------
async def upsert_user(conn, uid: int, name: str, username: str | None) -> None:
    await conn.execute(
        "INSERT INTO users(id,name,username) VALUES($1,$2,$3) "
        "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, username=EXCLUDED.username",
        uid, name[:64], username,
    )


async def ensure_chat(pool, chat_id: int, title: str = "") -> dict:
    raw = await pool.fetchval(
        "INSERT INTO chats(id,title) VALUES($1,$2) "
        "ON CONFLICT (id) DO UPDATE SET title=CASE WHEN EXCLUDED.title<>'' THEN EXCLUDED.title ELSE chats.title END "
        "RETURNING settings",
        chat_id, title[:128],
    )
    return merge(json.loads(raw) if isinstance(raw, str) else raw)


async def save_settings(pool, chat_id: int, settings: dict) -> None:
    await pool.execute("UPDATE chats SET settings=$2::jsonb WHERE id=$1", chat_id, json.dumps(settings))


# ---------- تولید مرحله ----------
async def fetch_seeds(pool, n: int, lo: int, hi: int, exclude: list[int], allow_names: bool, limit: int) -> list[WordRow]:
    rows = await pool.fetch(
        f"SELECT {_ROW} FROM words WHERE status='approved' AND puzzle_ok AND length=$1 "
        "AND difficulty BETWEEN $2 AND $3 AND id <> ALL($4::int[]) AND ($5 OR category<>'name') "
        "AND position(chr(8204) in display)=0 ORDER BY random() LIMIT $6",
        n, lo, hi, exclude, allow_names, limit,
    )
    return [_word(r) for r in rows]


async def fetch_candidates(pool, sigs: list[str], allow_names: bool) -> list[WordRow]:
    rows = await pool.fetch(
        f"SELECT {_ROW} FROM words WHERE status='approved' AND letters_sig = ANY($1::text[]) "
        "AND (puzzle_ok OR bonus_ok) AND ($2 OR category<>'name')",
        sigs, allow_names,
    )
    return [_word(r) for r in rows]


async def recent_ids(pool, chat_id: int) -> tuple[set[int], set[int]]:
    seeds = await pool.fetch(
        "SELECT seed_word_id FROM rounds WHERE chat_id=$1 AND seed_word_id IS NOT NULL ORDER BY id DESC LIMIT 300", chat_id
    )
    words = await pool.fetch(
        "SELECT DISTINCT word_id FROM round_words WHERE chat_id=$1 AND is_main AND round_id IN "
        "(SELECT id FROM rounds WHERE chat_id=$1 ORDER BY id DESC LIMIT 150)", chat_id,
    )
    return {r[0] for r in seeds}, {r[0] for r in words}


async def create_round(pool, chat_id: int, level: Level, duration: int, hints_max: int) -> RoundState:
    async with pool.acquire() as conn:
        async with conn.transaction():
            number = await conn.fetchval(
                "UPDATE chats SET round_counter=round_counter+1 WHERE id=$1 RETURNING round_counter", chat_id
            )
            r = await conn.fetchrow(
                "INSERT INTO rounds(chat_id,number,letters,seed_word_id,ends_at,hints_max) "
                "VALUES($1,$2,$3,$4, now() + make_interval(secs => $5::int), $6) RETURNING id, ends_at",
                chat_id, number, "".join(level.letters), level.seed.id, duration, hints_max,
            )
            items = [(w, True) for w in level.main] + [(w, False) for w in level.bonus]
            await conn.executemany(
                "INSERT INTO round_words(round_id,chat_id,word_id,norm,display,is_main,base_points) "
                "VALUES($1,$2,$3,$4,$5,$6,$7)",
                [
                    (r["id"], chat_id, w.id, w.norm, w.display, main, word_points(w.length, w.difficulty, main))
                    for w, main in items
                ],
            )
            rows = await conn.fetch(
                "SELECT id, word_id, norm, display, is_main, base_points FROM round_words WHERE round_id=$1", r["id"]
            )
    words = {
        x["norm"]: RWord(x["id"], x["word_id"], x["norm"], x["display"], x["is_main"], x["base_points"])
        for x in rows
    }
    return RoundState(r["id"], chat_id, number, list(level.letters), r["ends_at"], hints_max, words)


async def set_message(pool, round_id: int, message_id: int) -> None:
    await pool.execute("UPDATE rounds SET message_id=$2 WHERE id=$1", round_id, message_id)


async def load_active(pool) -> list[RoundState]:
    out: list[RoundState] = []
    for r in await pool.fetch("SELECT * FROM rounds WHERE status='active'"):
        rows = await pool.fetch(
            "SELECT rw.id, rw.word_id, rw.norm, rw.display, rw.is_main, rw.base_points, rw.revealed, rw.points, "
            "rw.found_by, u.name FROM round_words rw LEFT JOIN users u ON u.id=rw.found_by WHERE rw.round_id=$1",
            r["id"],
        )
        words = {}
        players: dict[int, list] = {}
        for x in rows:
            w = RWord(x["id"], x["word_id"], x["norm"], x["display"], x["is_main"], x["base_points"],
                      x["revealed"], x["found_by"], x["name"], x["points"])
            words[w.norm] = w
            if w.found_by is not None:
                p = players.setdefault(w.found_by, [w.found_name or "", 0, 0])
                p[1] += w.points
                p[2] += 1
        out.append(RoundState(
            r["id"], r["chat_id"], r["number"], list(r["letters"]), r["ends_at"], r["hints_max"], words,
            message_id=r["message_id"], hints_used=r["hints_used"], players=players, dirty=True,
        ))
    return out


# ---------- حدس و امتیاز (اتمیک) ----------
async def claim_word(pool, rw_id: int, chat_id: int, uid: int, name: str, username: str | None, points: int) -> bool:
    """فقط اولین ثبت‌کننده برنده است؛ UPDATE شرطی در یک تراکنش."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await upsert_user(conn, uid, name, username)
            row = await conn.fetchrow(
                "UPDATE round_words SET found_by=$1, found_at=now(), points=$2 "
                "WHERE id=$3 AND found_by IS NULL RETURNING id", uid, points, rw_id,
            )
            if row is None:
                return False
            await conn.execute(
                "UPDATE users SET total_points=total_points+$2, words_found=words_found+1 WHERE id=$1", uid, points
            )
            await conn.execute(
                "INSERT INTO chat_members(chat_id,user_id,points,words) VALUES($1,$2,$3,1) "
                "ON CONFLICT (chat_id,user_id) DO UPDATE SET points=chat_members.points+$3, words=chat_members.words+1",
                chat_id, uid, points,
            )
    return True


async def record_hint(pool, state: RoundState, rw: RWord, uid: int, name: str, username: str | None) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await upsert_user(conn, uid, name, username)
            await conn.execute("UPDATE round_words SET revealed=$2 WHERE id=$1", rw.id, rw.revealed)
            await conn.execute("UPDATE rounds SET hints_used=$2 WHERE id=$1", state.id, state.hints_used)
            await conn.execute(
                "INSERT INTO round_hints(round_id,round_word_id,user_id) VALUES($1,$2,$3)", state.id, rw.id, uid
            )


async def finish_round(pool, state: RoundState, status: str) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "UPDATE rounds SET status=$2, finished_at=now(), hints_used=$3 WHERE id=$1 AND status='active' RETURNING id",
                state.id, status, state.hints_used,
            )
            if row is None or not state.players:
                return
            top = max(state.players.items(), key=lambda kv: kv[1][1])[0]
            for uid in state.players:
                win = 1 if uid == top else 0
                await conn.execute("UPDATE users SET rounds_played=rounds_played+1, wins=wins+$2 WHERE id=$1", uid, win)
                await conn.execute(
                    "UPDATE chat_members SET rounds=rounds+1, wins=wins+$3 WHERE chat_id=$1 AND user_id=$2",
                    state.chat_id, uid, win,
                )


# ---------- آمار و جدول‌ها ----------
async def user_stats(pool, chat_id: int, uid: int, now: datetime) -> dict:
    m = await pool.fetchrow("SELECT points, words, rounds, wins FROM chat_members WHERE chat_id=$1 AND user_id=$2", chat_id, uid)
    u = await pool.fetchrow("SELECT total_points, words_found, rounds_played, wins FROM users WHERE id=$1", uid)
    if m is None or u is None:
        return {}
    crank = await pool.fetchval("SELECT count(*)+1 FROM chat_members WHERE chat_id=$1 AND points>$2", chat_id, m["points"])
    grank = await pool.fetchval("SELECT count(*)+1 FROM users WHERE total_points>$1", u["total_points"])
    day, week, month = period_starts(now)
    per = await pool.fetchrow(
        "SELECT coalesce(sum(points) FILTER (WHERE found_at>=$2),0) AS day, "
        "coalesce(sum(points) FILTER (WHERE found_at>=$3),0) AS week, coalesce(sum(points),0) AS month "
        "FROM round_words WHERE found_by=$1 AND found_at>=$4", uid, day, week, month,
    )
    return {"chat": dict(m), "global": dict(u), "crank": crank, "grank": grank, "per": dict(per)}


async def top_chat(pool, chat_id: int, limit: int = 10) -> list:
    return await pool.fetch(
        "SELECT u.name, cm.points, cm.words FROM chat_members cm JOIN users u ON u.id=cm.user_id "
        "WHERE cm.chat_id=$1 ORDER BY cm.points DESC LIMIT $2", chat_id, limit,
    )


async def top_global(pool, limit: int = 10) -> list:
    return await pool.fetch(
        "SELECT name, total_points AS points, words_found AS words FROM users WHERE total_points>0 "
        "ORDER BY total_points DESC LIMIT $1", limit,
    )


async def chat_stats(pool, chat_id: int) -> dict:
    r = await pool.fetchrow(
        "SELECT (SELECT count(*) FROM rounds WHERE chat_id=$1 AND status<>'active') AS rounds, "
        "(SELECT count(*) FROM round_words WHERE chat_id=$1 AND found_by IS NOT NULL) AS words, "
        "(SELECT count(*) FROM chat_members WHERE chat_id=$1) AS players", chat_id,
    )
    return dict(r)


async def global_stats(pool) -> dict:
    r = await pool.fetchrow(
        "SELECT (SELECT count(*) FROM users) AS users, (SELECT count(*) FROM chats) AS chats, "
        "(SELECT count(*) FROM rounds) AS rounds, (SELECT count(*) FROM words) AS words, "
        "(SELECT count(*) FROM words WHERE puzzle_ok AND status='approved') AS puzzle_words, "
        "(SELECT count(*) FROM word_suggestions WHERE status='pending') AS pending"
    )
    return dict(r)
