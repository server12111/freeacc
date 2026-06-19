import asyncio
import logging
import re
from typing import TYPE_CHECKING, Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession

if TYPE_CHECKING:
    from bot.services.contest_monitor import ContestMonitorService
    from bot.database.db import Database

logger = logging.getLogger(__name__)

PIARFLOW_BOT = "PiarFlowBot"


class UserbotManager:
    def __init__(self, config) -> None:
        self._config = config
        self._client: Optional[TelegramClient] = None
        self._monitor: Optional["ContestMonitorService"] = None
        self._polling_task: Optional[asyncio.Task] = None
        self._creation_lock = asyncio.Lock()

    @property
    def client(self) -> Optional[TelegramClient]:
        return self._client

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self, monitor: "ContestMonitorService") -> None:
        self._monitor = monitor
        if not self._config.USERBOT_API_ID or not self._config.USERBOT_API_HASH:
            logger.warning("Userbot API credentials not set — userbot disabled")
            return
        if not self._config.USERBOT_SESSION:
            logger.warning(
                "USERBOT_SESSION is empty — userbot not connected. "
                "Use /auth in the bot to authorize."
            )
            return
        await self._connect()

    async def _connect(self) -> None:
        session = StringSession(self._config.USERBOT_SESSION)
        self._client = TelegramClient(
            session,
            self._config.USERBOT_API_ID,
            self._config.USERBOT_API_HASH,
            device_model="Samsung Galaxy S23",
            system_version="Android 13",
            app_version="10.14.1",
        )
        await self._client.connect()
        if not await self._client.is_user_authorized():
            logger.warning("Userbot session is invalid — run /auth again")
            await self._client.disconnect()
            self._client = None
            return
        me = await self._client.get_me()
        logger.info("Userbot connected: %s", me)
        # Populate entity cache so get_messages() works for any subscribed channel
        try:
            await self._client.get_dialogs()
            logger.info("Dialogs loaded — entity cache populated")
        except Exception as exc:
            logger.warning("get_dialogs failed: %s", exc)
        self._attach_events()
        self._polling_task = asyncio.create_task(self._fallback_poll_loop())

    async def stop(self) -> None:
        if self._polling_task:
            self._polling_task.cancel()
        if self._client and self._client.is_connected():
            await self._client.disconnect()
        logger.info("Userbot disconnected")

    def _attach_events(self) -> None:
        channel_str = self._config.CHANNEL_ID
        if not channel_str:
            logger.warning("CHANNEL_ID not set — channel monitoring disabled")
            return

        channel_id = int(channel_str)
        logger.info("Attaching channel event handlers for %s", channel_id)

        @self._client.on(events.MessageEdited())
        async def on_edited(event):
            if event.chat_id != channel_id:
                return
            try:
                await self._monitor.process_update(event.message)
            except Exception as exc:
                logger.exception("Error processing channel update: %s", exc)

        @self._client.on(events.NewMessage())
        async def on_new(event):
            if event.chat_id != channel_id:
                return
            try:
                await self._monitor.process_update(event.message)
            except Exception as exc:
                logger.exception("Error processing new channel message: %s", exc)

        logger.info("Channel monitoring active for %s", channel_id)

    async def _fallback_poll_loop(self) -> None:
        await asyncio.sleep(60)
        while True:
            try:
                await self._monitor.poll_active_contests(self._client)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Fallback poll error: %s", exc)
            await asyncio.sleep(60)

    # ── PiarFlowBot helpers ────────────────────────────────────────────────

    async def _resolve_piarflow(self):
        """Resolve @PiarFlowBot entity once and cache it."""
        if not hasattr(self, "_pf_entity"):
            self._pf_entity = await self._client.get_entity(PIARFLOW_BOT)
            logger.info("PiarFlowBot entity resolved: id=%s", self._pf_entity.id)
        return self._pf_entity

    def _pf_listen(self, pf_entity):
        """
        Register one-shot listeners (new + edited) scoped to PiarFlowBot chat.
        Always call BEFORE the action that triggers the response.
        Returns (future, (h_new, h_edit)).
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        async def _h_new(event):
            if not future.done():
                logger.info("_pf_listen: NewMessage from PiarFlowBot")
                future.set_result(event.message)

        async def _h_edit(event):
            if not future.done():
                logger.info("_pf_listen: MessageEdited from PiarFlowBot")
                future.set_result(event.message)

        self._client.add_event_handler(_h_new, events.NewMessage(chats=pf_entity))
        self._client.add_event_handler(_h_edit, events.MessageEdited(chats=pf_entity))
        return future, (_h_new, _h_edit)

    async def _pf_wait(self, future, handlers, timeout: float = 8):
        """Await the future prepared by _pf_listen() and remove handlers."""
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("_pf_wait timed out after %ss", timeout)
            return None
        finally:
            for h in handlers:
                self._client.remove_event_handler(h)

    async def _click_button(self, msg, text: str) -> bool:
        """Click inline button whose label contains `text` (case-insensitive)."""
        if not msg or not msg.reply_markup:
            logger.warning("_click_button: no markup, looking for '%s'", text)
            return False
        all_btns = []
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                btn_text = getattr(btn, "text", "") or ""
                all_btns.append(repr(btn_text))
                if text.lower() in btn_text.lower():
                    try:
                        await msg.click(data=btn.data)
                        logger.info("Clicked button '%s'", btn_text)
                        return True
                    except Exception as exc:
                        logger.warning("Click '%s' failed: %s", text, exc)
                        return False
        logger.warning("Button '%s' not found. Available: %s", text, all_btns)
        return False

    @staticmethod
    def _extract_channel_id_from_select(msg) -> Optional[int]:
        """
        Parse the channel_id embedded in PiarFlowBot's channel-selection button data.
        Data format examples: b'contests:do_publish:12190:-1004477541143'
        Returns the last integer segment if it looks like a Telegram channel ID.
        """
        if not msg or not msg.reply_markup:
            return None
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                data = getattr(btn, "data", None)
                if not data:
                    continue
                try:
                    parts = data.decode("utf-8", errors="ignore").split(":")
                    for part in reversed(parts):
                        part = part.strip()
                        if part.lstrip("-").isdigit() and len(part) >= 8:
                            return int(part)
                except Exception:
                    pass
        return None

    @staticmethod
    def _extract_link(msg) -> Optional[str]:
        """Extract first t.me link from message text or URL buttons."""
        if not msg:
            return None
        text = msg.text or msg.message or ""
        urls = re.findall(r"https?://t\.me/\S+", text)
        if urls:
            return urls[0].rstrip(")")
        if msg.reply_markup:
            try:
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        url = getattr(btn, "url", None)
                        if url and "t.me" in url:
                            return url
            except Exception:
                pass
        return None

    @staticmethod
    def _extract_msg_id(link: str) -> Optional[int]:
        """
        Extract message_id from a Telegram post link.
        Handles:
          https://t.me/c/1234567890/42   → 42
          https://t.me/channelname/42    → 42
        """
        m = re.search(r"/(\d+)\s*$", link.rstrip("/"))
        if m:
            return int(m.group(1))
        return None

    # ── PiarFlowBot contest creation ───────────────────────────────────────

    async def create_piarflow_contest(
        self,
        contest_id: int,
        participant_number: int,
        username_text: str,
        db: "Database",
        status_message=None,
    ) -> Optional[str]:
        """
        Runs through @PiarFlowBot to create a personal contest.
        Retries up to 3 times with 60-second delays if PiarFlowBot is unresponsive.
        Returns the contest link on success, None on failure.
        Serialised via lock — only one creation at a time.
        """
        if not self._client:
            logger.error("create_piarflow_contest: client not connected")
            return None

        MAX_RETRIES = 3
        RETRY_DELAY = 60

        for attempt in range(1, MAX_RETRIES + 1):
            async with self._creation_lock:
                try:
                    link = await self._run_piarflow_flow(
                        contest_id, participant_number, username_text
                    )
                    if link:
                        msg_id = self._extract_msg_id(link)
                        await db.set_contest_piarflow(contest_id, msg_id, link)
                        await db.add_log(
                            "piarflow_contest_created",
                            f"contest={contest_id} participant={participant_number} link={link}",
                        )
                        logger.info(
                            "Contest #%d created: participant=%d link=%s",
                            contest_id, participant_number, link,
                        )
                        return link
                    await db.add_log(
                        "piarflow_contest_failed",
                        f"contest={contest_id} participant={participant_number} attempt={attempt}",
                    )
                except Exception as exc:
                    logger.exception(
                        "PF attempt %d/%d error for contest %d: %s",
                        attempt, MAX_RETRIES, contest_id, exc,
                    )
                    await db.add_log(
                        "piarflow_error",
                        f"contest={contest_id} attempt={attempt} error={exc}",
                    )

            if attempt < MAX_RETRIES:
                logger.warning(
                    "PF attempt %d/%d failed, retrying in %ds", attempt, MAX_RETRIES, RETRY_DELAY
                )
                if status_message:
                    try:
                        await status_message.edit_text(
                            f"⏳ PiarFlowBot не отвечает — попытка {attempt}/{MAX_RETRIES}.\n"
                            f"Повторяем через {RETRY_DELAY} сек...\n\n"
                            f"Пожалуйста, подожди — бот работает 🔄"
                        )
                    except Exception:
                        pass
                await asyncio.sleep(RETRY_DELAY)

        return None

    async def _run_piarflow_flow(
        self,
        contest_id: int,
        participant_number: int,
        username_text: str,
    ) -> Optional[str]:
        c = self._client
        pf = await self._resolve_piarflow()
        channel_id = int(self._config.CHANNEL_ID)
        invite_threshold = getattr(self._config, "INVITE_THRESHOLD", 10)

        # Register channel listener BEFORE the flow to catch the published post
        btn_needle = f"{participant_number} участник"
        chan_future: asyncio.Future = asyncio.get_running_loop().create_future()

        async def _chan_post_handler(event):
            if event.chat_id != channel_id or chan_future.done():
                return
            msg = event.message
            if not msg.reply_markup:
                return
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    t = getattr(btn, "text", "") or ""
                    if btn_needle in t:
                        logger.info(
                            "Channel post detected for participant #%d, msg_id=%d",
                            participant_number, msg.id,
                        )
                        chan_future.set_result(msg)
                        return

        self._client.add_event_handler(_chan_post_handler, events.NewMessage())
        try:
            return await self._pf_steps(
                c, pf, contest_id, participant_number, username_text,
                invite_threshold, chan_future, channel_id,
            )
        finally:
            self._client.remove_event_handler(_chan_post_handler)

    async def _pf_steps(
        self,
        c,
        pf,
        contest_id: int,
        participant_number: int,
        username_text: str,
        invite_threshold: int,
        chan_future: asyncio.Future,
        channel_id: int,
    ) -> Optional[str]:
        def listen():
            return self._pf_listen(pf)

        async def wait(f, h, t=8):
            return await self._pf_wait(f, h, t)

        # ── 1: /start ──────────────────────────────────────────────────────
        f, h = listen()
        await c.send_message(PIARFLOW_BOT, "/start")
        msg = await wait(f, h, 10)
        if not msg:
            logger.error("PF[1/start] no response")
            return None
        await asyncio.sleep(2)

        # ── 2: Продать трафик ──────────────────────────────────────────────
        f, h = listen()
        await self._click_button(msg, "Продать трафик")
        msg = await wait(f, h)
        if not msg:
            logger.error("PF[2/Продать трафик] no response")
            return None
        await asyncio.sleep(2)

        # ── 3: Конкурсы ────────────────────────────────────────────────────
        f, h = listen()
        await self._click_button(msg, "Конкурсы")
        msg = await wait(f, h)
        if not msg:
            logger.error("PF[3/Конкурсы] no response")
            return None
        await asyncio.sleep(2)

        # ── 4: Создать конкурс ─────────────────────────────────────────────
        f, h = listen()
        await self._click_button(msg, "Создать конкурс")
        msg = await wait(f, h, 15)
        if not msg:
            logger.error("PF[4/Создать конкурс] no response")
            return None
        await asyncio.sleep(2)

        # ── 5: 1/8 Пост — contest text ─────────────────────────────────────
        f, h = listen()
        await c.send_message(PIARFLOW_BOT, username_text)
        msg = await wait(f, h)
        if not msg:
            logger.error("PF[5/1/8 Пост] no response")
            return None
        await asyncio.sleep(2)

        # ── 6: 2/8 Обложка — Без медиа ────────────────────────────────────
        f, h = listen()
        await self._click_button(msg, "Без медиа")
        msg = await wait(f, h)
        if not msg:
            logger.error("PF[6/2/8 Без медиа] no response")
            return None
        await asyncio.sleep(2)

        # ── 7: 3/8 Кнопка — "N участник" as button text ───────────────────
        f, h = listen()
        await c.send_message(PIARFLOW_BOT, f"{participant_number} участник")
        msg = await wait(f, h)
        if not msg:
            logger.error("PF[7/3/8 Кнопка] no response")
            return None
        await asyncio.sleep(2)

        # ── 8: 4/8 Фильтр входа — 1 task (subscribe to our channel) ───────
        f, h = listen()
        await self._click_button(msg, "1")
        msg = await wait(f, h)
        if not msg:
            logger.error("PF[8/4/8 Фильтр] no response")
            return None
        await asyncio.sleep(2)

        # ── 9: 5/8 Нет заданий — Не пускать без заданий ───────────────────
        f, h = listen()
        await self._click_button(msg, "Не пускать без заданий")
        msg = await wait(f, h)
        if not msg:
            logger.error("PF[9/5/8 Не пускать без заданий] no response")
            return None
        await asyncio.sleep(2)

        # ── 10: 6/8 Отписка — Исключать после отписки ─────────────────────
        f, h = listen()
        await self._click_button(msg, "Исключать после отписки")
        msg = await wait(f, h)
        if not msg:
            logger.error("PF[10/6/8 Исключать после отписки] no response")
            return None
        await asyncio.sleep(2)

        # ── 11: 7/8 Победители — 1 winner ─────────────────────────────────
        f, h = listen()
        await c.send_message(PIARFLOW_BOT, "1")
        msg = await wait(f, h)
        if not msg:
            logger.error("PF[11/7/8 Победители] no response")
            return None
        await asyncio.sleep(2)

        # ── 12: 8/8 Завершение — По участникам ────────────────────────────
        f, h = listen()
        await self._click_button(msg, "По участникам")
        msg = await wait(f, h)
        if not msg:
            logger.error("PF[12/8/8 Завершение] no response")
            return None
        await asyncio.sleep(2)

        # ── 13: 8/8 Значение — send 1000 so PiarFlowBot contest never auto-ends;
        # the bot issues the account via its own channel-monitoring threshold.
        pf_queue: asyncio.Queue = asyncio.Queue()

        async def _q_h(event):
            await pf_queue.put(event.message)

        self._client.add_event_handler(_q_h, events.NewMessage(chats=pf))
        try:
            await c.send_message(PIARFLOW_BOT, "1000")
            last_msg = None
            for _ in range(3):
                try:
                    m = await asyncio.wait_for(pf_queue.get(), timeout=12)
                    last_msg = m
                    logger.debug("PF[13] received batch message, text=%r", (m.text or "")[:60])
                except asyncio.TimeoutError:
                    break
        finally:
            self._client.remove_event_handler(_q_h)

        if not last_msg:
            logger.error("PF[13/8/8 Значение] no messages received after threshold")
            return None
        await asyncio.sleep(2)

        # ── 14: Опубликовать (from "Preview готов к публикации") ───────────
        f, h = listen()
        await self._click_button(last_msg, "Опубликовать")
        msg = await wait(f, h, 10)
        if not msg:
            logger.error("PF[14/Опубликовать preview] no response")
            return None
        await asyncio.sleep(2)

        # Extract the real channel_id from PiarFlowBot's channel selection
        # button data (format: b"contests:...:CHANNEL_ID"), which is more
        # reliable than the config value.
        effective_channel_id = self._extract_channel_id_from_select(msg) or channel_id
        logger.info("PF publish channel_id: %d (config: %d)", effective_channel_id, channel_id)
        peer_id = str(abs(effective_channel_id))[3:]  # -100XXXXXXXXXX → XXXXXXXXXX
        chan_username = getattr(self._config, "CHANNEL_USERNAME", "").strip().lstrip("@")

        def _build_link(msg_id: int) -> str:
            if chan_username:
                return f"https://t.me/{chan_username}/{msg_id}"
            return f"https://t.me/c/{peer_id}/{msg_id}"

        # ── 15: Select channel — publishes contest to channel ─────────────
        f, h = listen()
        await self._click_button(msg, "Бесплатные")
        await wait(f, h, 12)  # management page — ignore content, already published

        # ── Obtain channel post link ─────────────────────────────────────

        # Primary: event-based (registered before flow started)
        try:
            chan_msg = await asyncio.wait_for(asyncio.shield(chan_future), timeout=20)
            link = _build_link(chan_msg.id)
            logger.info("Contest #%d link (event): %s", contest_id, link)
            return link
        except asyncio.TimeoutError:
            logger.warning("Chan event timeout for participant #%d, trying get_messages", participant_number)

        # Fallback: scan recent channel messages directly
        try:
            await asyncio.sleep(1)
            msgs = await c.get_messages(effective_channel_id, limit=15)
            for m in msgs:
                if not m.reply_markup:
                    continue
                for row in m.reply_markup.rows:
                    for btn in row.buttons:
                        t = getattr(btn, "text", "") or ""
                        if btn_needle in t:
                            link = _build_link(m.id)
                            logger.info("Contest #%d link (scan): %s", contest_id, link)
                            return link
        except Exception as exc:
            logger.warning("Channel scan failed for participant #%d: %s", participant_number, exc)

        logger.error("PF: could not obtain link for contest #%d participant #%d", contest_id, participant_number)
        return None

    # ── Account code retrieval ─────────────────────────────────────────────

    async def get_telegram_auth_code(self, phone: str, session_string: str) -> Optional[str]:
        """
        Read the most recent auth code already delivered to the account session
        (message from 777000). Does NOT call send_code_request — the code must
        have been triggered by the user logging in on a device.
        """
        account_client = TelegramClient(
            StringSession(session_string),
            self._config.USERBOT_API_ID,
            self._config.USERBOT_API_HASH,
            device_model="Windows PC",
            system_version="Windows 10",
        )
        try:
            await account_client.connect()
            if not await account_client.is_user_authorized():
                logger.warning("Account session expired for %s", phone)
                return None

            msgs = await account_client.get_messages(777000, limit=5)
            for msg in msgs:
                text = getattr(msg, "message", "") or ""
                m = re.search(r"\b(\d{5,6})\b", text)
                if m:
                    logger.info("Auth code found in history for %s", phone)
                    return m.group(1)

            logger.warning("No auth code found in 777000 history for %s", phone)
            return None

        finally:
            try:
                if account_client.is_connected():
                    await account_client.disconnect()
            except Exception:
                pass

    # ── Auth helpers ───────────────────────────────────────────────────────

    async def send_code(self, phone: str) -> None:
        if self._client is None:
            session = StringSession("")
            self._client = TelegramClient(
                session,
                self._config.USERBOT_API_ID,
                self._config.USERBOT_API_HASH,
            )
        await self._client.connect()
        await self._client.send_code_request(phone)
        self._phone = phone

    async def sign_in(self, code: str) -> str:
        await self._client.sign_in(self._phone, code)
        return self._client.session.save()

    async def sign_in_2fa(self, password: str) -> str:
        await self._client.sign_in(password=password)
        return self._client.session.save()

    def get_session_string(self) -> str:
        if self._client:
            return self._client.session.save()
        return ""
