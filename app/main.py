from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from app.bot import keyboards
from app.bot.handlers import build_router
from app.bot.owner import build_owner_router
from app.config import load_config
from app.db.pool import create_pool, migrate
from app.engine.service import GameService
from app.logbuf import RingHandler
from app.words.importer import import_seed_if_empty

ALLOWED = ["message", "callback_query", "my_chat_member"]


async def amain() -> None:
    cfg = load_config()
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger().addHandler(RingHandler())
    log = logging.getLogger("kalamebaz")
    keyboards.STYLES_ENABLED = cfg.button_styles

    pool = await create_pool(cfg.database_url)
    await migrate(pool)
    await import_seed_if_empty(pool)

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    svc = GameService(bot, pool, cfg)
    await svc.recover()

    dp = Dispatcher()
    if cfg.owner_id:
        dp.include_router(build_owner_router(svc, cfg))   # قبل از روتر عمومی
    dp.include_router(build_router(svc, cfg))
    await bot.set_my_commands([BotCommand(command="start", description="راهنما و افزودن به گروه")])

    ticker = asyncio.create_task(svc.run())
    try:
        if cfg.mode == "polling":
            await bot.delete_webhook()
            log.info("polling شروع شد")
            await dp.start_polling(bot, allowed_updates=ALLOWED)
        else:
            app = web.Application()

            async def health(_):
                return web.Response(text="ok")

            app.router.add_get("/healthz", health)
            app.router.add_get("/", health)
            SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=cfg.webhook_secret).register(app, path="/webhook")
            setup_application(app, dp, bot=bot)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", cfg.port).start()
            await bot.set_webhook(
                f"{cfg.base_url}/webhook", secret_token=cfg.webhook_secret, allowed_updates=ALLOWED
            )
            log.info("webhook روی %s فعال شد", cfg.base_url)
            await asyncio.Event().wait()
    finally:
        ticker.cancel()
        await bot.session.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(amain())
