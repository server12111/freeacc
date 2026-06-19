import logging
from typing import Optional
import aiohttp

logger = logging.getLogger(__name__)

CRYPTOBOT_API = "https://pay.crypt.bot/api"


class CryptoBotService:
    def __init__(self, token: str) -> None:
        self._token = token
        self._headers = {"Crypto-Pay-API-Token": token}

    async def create_invoice(
        self,
        amount: str,
        description: str,
        payload: str = "",
    ) -> Optional[dict]:
        """Create USDT invoice. Returns invoice dict or None on error."""
        data = {
            "asset": "USDT",
            "amount": amount,
            "description": description,
            "payload": payload,
            "allow_comments": False,
            "allow_anonymous": True,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CRYPTOBOT_API}/createInvoice",
                json=data,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                body = await resp.json()
                if body.get("ok"):
                    return body["result"]
                logger.error("CryptoBot createInvoice error: %s", body)
                return None

    async def get_invoice(self, invoice_id: str) -> Optional[dict]:
        """Fetch invoice by ID. Returns invoice dict or None."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{CRYPTOBOT_API}/getInvoices",
                params={"invoice_ids": invoice_id},
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                body = await resp.json()
                if body.get("ok"):
                    items = body["result"].get("items", [])
                    return items[0] if items else None
                logger.error("CryptoBot getInvoices error: %s", body)
                return None

    def is_configured(self) -> bool:
        return bool(self._token)
