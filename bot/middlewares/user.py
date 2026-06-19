from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from bot.database.db import Database


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, (Message, CallbackQuery)):
            from_user = event.from_user
            if from_user:
                db: Database = data.get("db")
                if db:
                    bot_user, _ = await db.get_or_create_user(
                        tg_id=from_user.id,
                        username=from_user.username,
                        first_name=from_user.first_name,
                    )
                    data["bot_user"] = bot_user
        return await handler(event, data)
