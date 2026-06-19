import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

_BASE = Path(__file__).resolve().parent.parent


def _admin_ids() -> list[int]:
    raw = os.getenv("ADMIN_IDS", "")
    result = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            result.append(int(part))
    return result


class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: list[int] = _admin_ids()

    DATABASE_PATH: str = os.getenv("DATABASE_PATH", str(_BASE / "data" / "bot.db"))
    SESSIONS_PATH: str = os.getenv("SESSIONS_PATH", str(_BASE / "data" / "sessions"))

    USERBOT_API_ID: int = int(os.getenv("USERBOT_API_ID", "0") or "0")
    USERBOT_API_HASH: str = os.getenv("USERBOT_API_HASH", "")
    USERBOT_SESSION: str = os.getenv("USERBOT_SESSION", "")

    INVITE_THRESHOLD: int = int(os.getenv("INVITE_THRESHOLD", "10") or "10")
    CHANNEL_ID: str = os.getenv("CHANNEL_ID", "")
    CHANNEL_USERNAME: str = os.getenv("CHANNEL_USERNAME", "").strip().lstrip("@")

    CRYPTO_BOT_TOKEN: str = os.getenv("CRYPTO_BOT_TOKEN", "")
    ACCOUNT_PRICE_USDT: str = os.getenv("ACCOUNT_PRICE_USDT", "0.5")
