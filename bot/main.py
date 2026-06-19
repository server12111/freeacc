import sys
sys.stderr = sys.stdout
print("=== [1] sys ok ===", flush=True)

import asyncio, logging, os, signal
print("=== [2] stdlib ok ===", flush=True)

try:
    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import ErrorEvent
    print("=== [3] aiogram ok ===", flush=True)
except Exception as e:
    print(f"=== [3] aiogram FAIL: {e} ===", flush=True)
    raise

try:
    from bot.config import Config
    print("=== [4] config ok ===", flush=True)
except Exception as e:
    print(f"=== [4] config FAIL: {e} ===", flush=True)
    raise

try:
    from bot.database.db import Database
    print("=== [5] db ok ===", flush=True)
except Exception as e:
    print(f"=== [5] db FAIL: {e} ===", flush=True)
    raise

try:
    from bot.handlers import setup_routers
    from bot.middlewares.user import UserMiddleware
    from bot.middlewares.subscription import SubscriptionMiddleware
    print("=== [6] handlers/middlewares ok ===", flush=True)
except Exception as e:
    print(f"=== [6] handlers/middlewares FAIL: {e} ===", flush=True)
    raise

try:
    from bot.userbot.manager import UserbotManager
    from bot.services.account_issuer import AccountIssuerService
    from bot.services.contest_monitor import ContestMonitorService
    from bot.services.contest_scheduler import ContestSchedulerService
    print("=== [7] services ok ===", flush=True)
except Exception as e:
    print(f"=== [7] services FAIL: {e} ===", flush=True)
    raise

print("=== [8] all imports done ===", flush=True)

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    config = Config()

    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set in .env")

    os.makedirs(os.path.dirname(config.DATABASE_PATH) or ".", exist_ok=True)
    os.makedirs(config.SESSIONS_PATH, exist_ok=True)

    db = Database(config.DATABASE_PATH)
    await db.init()
    logger.info("Database initialised at %s", config.DATABASE_PATH)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()

    issuer = AccountIssuerService(bot, db, config)
    monitor = ContestMonitorService(db, issuer, config)
    userbot = UserbotManager(config)
    scheduler = ContestSchedulerService(bot, db, config, userbot)

    dp["db"] = db
    dp["config"] = config
    dp["manager"] = userbot
    dp["issuer"] = issuer
    dp["monitor"] = monitor

    dp.update.middleware(UserMiddleware())
    dp.update.middleware(SubscriptionMiddleware())
    setup_routers(dp)

    # Global error handler — logs every unhandled exception and answers pending callbacks
    @dp.error()
    async def _error_handler(event: ErrorEvent) -> bool:
        logger.error("Unhandled error in update %s: %s", event.update, event.exception, exc_info=True)
        cbq = getattr(event.update, "callback_query", None)
        if cbq:
            try:
                await cbq.answer("⚠️ Произошла ошибка")
            except Exception:
                pass
        return True

    try:
        await asyncio.wait_for(userbot.start(monitor), timeout=30)
    except asyncio.TimeoutError:
        logger.warning("Userbot connection timed out — bot starts without userbot")
    except Exception as exc:
        logger.warning("Userbot failed to start: %s — bot starts without userbot", exc)
    scheduler.start()
    logger.info("Bot starting — admins: %s", config.ADMIN_IDS)

    # SIGTERM / SIGINT → cancel current task → finally block runs → clean shutdown
    loop = asyncio.get_running_loop()
    current_task = asyncio.current_task()

    def _on_signal() -> None:
        logger.info("Shutdown signal received, stopping...")
        if current_task and not current_task.done():
            current_task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except (NotImplementedError, ValueError, OSError):
            pass  # Windows doesn't support add_signal_handler

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except asyncio.CancelledError:
        logger.info("Polling cancelled, shutting down...")
    finally:
        scheduler.stop()
        await userbot.stop()
        await db.close()
        await bot.session.close()
        logger.info("Shutdown complete")
