import time
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from bot.config import Config
from bot.database.db import Database

logger = logging.getLogger(__name__)

_SUBSCRIBED_STATUSES = {"member", "administrator", "creator", "restricted"}

# Callbacks/commands that bypass the subscription check
_BYPASS_CALLBACKS = {"check_subscription", "cancel_payment"}
_BYPASS_COMMANDS = {"/start"}


class SubscriptionMiddleware(BaseMiddleware):
    _cache: dict[int, tuple[float, bool]] = {}
    CACHE_TTL = 60

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = None
        if isinstance(event, Message):
            from_user = event.from_user
        elif isinstance(event, CallbackQuery):
            from_user = event.from_user

        if not from_user:
            return await handler(event, data)

        config: Config = data.get("config")
        db: Database = data.get("db")
        if not config or not db:
            return await handler(event, data)

        # Admins are never blocked
        if from_user.id in config.ADMIN_IDS:
            return await handler(event, data)

        # Bypass commands (/start)
        if isinstance(event, Message) and event.text:
            cmd = event.text.split()[0].split("@")[0].lower()
            if cmd in _BYPASS_COMMANDS:
                return await handler(event, data)

        # Bypass specific callbacks
        if isinstance(event, CallbackQuery) and event.data:
            if event.data in _BYPASS_CALLBACKS or event.data.startswith("check_subscription"):
                return await handler(event, data)

        # Check if subscription enforcement is enabled
        req = await db.get_setting("require_subscription", "0")
        if req != "1":
            return await handler(event, data)

        channel_id = config.CHANNEL_ID
        if not channel_id:
            return await handler(event, data)

        # Check cache
        now = time.time()
        cached = self._cache.get(from_user.id)
        if cached and now - cached[0] < self.CACHE_TTL:
            is_sub = cached[1]
        else:
            try:
                bot = data.get("bot") or (event.bot if hasattr(event, "bot") else None)
                if bot is None and isinstance(event, CallbackQuery):
                    bot = event.message.bot if event.message else None
                if bot is None and isinstance(event, Message):
                    bot = event.bot

                member = await bot.get_chat_member(int(channel_id), from_user.id)
                is_sub = member.status in _SUBSCRIBED_STATUSES
            except Exception as exc:
                logger.warning("Subscription check failed for %s: %s", from_user.id, exc)
                is_sub = True  # fail open — don't block on error

            self._cache[from_user.id] = (now, is_sub)

        if is_sub:
            return await handler(event, data)

        # Not subscribed — show wall
        from bot.keyboards.inline import subscription_wall_kb
        from bot.constants import E_LOCK
        text = (
            f"{E_LOCK} <b>Требуется подписка</b>\n\n"
            "Чтобы пользоваться ботом, подпишись на наш канал.\n\n"
            "После подписки нажми кнопку ниже 👇"
        )
        try:
            if isinstance(event, CallbackQuery):
                await event.answer()
                if event.message:
                    await event.message.edit_text(text, parse_mode="HTML", reply_markup=subscription_wall_kb(channel_id))
            elif isinstance(event, Message):
                await event.answer(text, parse_mode="HTML", reply_markup=subscription_wall_kb(channel_id))
        except Exception:
            pass
        return None
