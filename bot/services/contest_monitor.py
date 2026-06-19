import re
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.services.account_issuer import AccountIssuerService

logger = logging.getLogger(__name__)


def _parse_button_stats(button_text: str) -> Optional[tuple[int, int]]:
    """
    Parse "N участник · M" (or N участник•M) from a PiarFlowBot channel button.
    Returns (participant_number, invite_count) or None.
    """
    m = re.search(r"(\d+)\s*участни[к]?[^•·\d]*[•·]\s*(\d+)", button_text, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)\s*[•·]\s*(\d+)", button_text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


class ContestMonitorService:
    def __init__(self, db, issuer: "AccountIssuerService", config) -> None:
        self._db = db
        self._issuer = issuer
        self._config = config

    async def _custom_invite_count(self, text: str) -> Optional[int]:
        pattern = await self._db.get_setting("parse_pattern", "")
        if not pattern:
            return None
        try:
            m = re.search(pattern, text)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return None

    async def process_update(self, message) -> None:
        if message is None:
            return
        try:
            await self._process_update_inner(message)
        except Exception as exc:
            logger.error("process_update failed for msg %s: %s", getattr(message, 'id', '?'), exc, exc_info=True)

    async def _process_update_inner(self, message) -> None:

        button_texts: list[str] = []
        if message.reply_markup:
            try:
                for row in message.reply_markup.rows:
                    for btn in row.buttons:
                        t = getattr(btn, "text", "") or ""
                        if t:
                            button_texts.append(t)
            except Exception:
                pass

        full_text = (message.text or message.message or "") + "\n" + "\n".join(button_texts)
        await self._db.add_log(
            "channel_update",
            f"msg_id={message.id} buttons={button_texts} preview={full_text[:150]!r}",
        )

        contest = await self._db.get_contest_by_piarflow_msg(message.id)

        for btn_text in button_texts:
            parsed = _parse_button_stats(btn_text)
            if parsed is None:
                continue
            participant_number, default_invite_count = parsed
            custom = await self._custom_invite_count(btn_text)
            invite_count = custom if custom is not None else default_invite_count

            if contest and contest.participant_number != participant_number:
                contest = await self._db.get_contest_by_participant_number(participant_number)
            elif contest is None:
                contest = await self._db.get_contest_by_participant_number(participant_number)

            if contest is None:
                logger.debug(
                    "No active contest for participant_number=%d (msg_id=%d)",
                    participant_number, message.id,
                )
                continue

            if contest.piarflow_msg_id is None:
                await self._db.set_contest_piarflow(contest.id, message.id, contest.piarflow_link)
                contest = await self._db.get_contest(contest.id)

            updated = await self._db.update_contest_invite_count(contest.id, invite_count)
            logger.info(
                "Contest #%d (participant %d, user %d): invites %d",
                contest.id, participant_number, contest.owner_tg_id, invite_count,
            )

    async def poll_active_contests(self, client) -> None:
        if client is None:
            return
        try:
            contests = await self._db.get_active_contests()
        except Exception as exc:
            logger.error("poll_active_contests: failed to load contests: %s", exc)
            return
        for contest in contests:
            if not contest.piarflow_msg_id or not contest.channel_id:
                continue
            try:
                msgs = await client.get_messages(
                    contest.channel_id, ids=[contest.piarflow_msg_id]
                )
                if msgs and msgs[0]:
                    await self.process_update(msgs[0])
            except Exception as exc:
                logger.warning(
                    "Fallback poll failed for contest #%d: %s", contest.id, exc
                )
