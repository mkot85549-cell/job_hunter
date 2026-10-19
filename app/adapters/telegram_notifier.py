import html

from aiogram import Bot
from aiogram.enums import ParseMode

from app.core.job_hunter import Invitation


class AiogramNotificationSender:
    def __init__(self, bot: Bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def send_invitation_alert(self, invitation: Invitation) -> None:
        safe_title = html.escape(invitation.vacancy_title)
        safe_url = html.escape(invitation.vacancy_url, quote=True)
        safe_text = html.escape(invitation.message_text[:1500])

        if invitation.telegram_tags:
            tags_block = ", ".join(
                f"<code>{html.escape(t)}</code>" for t in invitation.telegram_tags
            )
        else:
            tags_block = "<i>Не найден автоматически (проверь текст ниже)</i>"

        message = (
            f"🎯 <b>Новый положительный отклик!</b>\n\n"
            f"📌 <b>Вакансия:</b> <a href='{safe_url}'>{safe_title}</a>\n"
            f"📲 <b>Теги ТГ:</b> {tags_block}\n\n"
            f"💬 <b>Текст приглашения:</b>\n"
            f"<blockquote expandable>{safe_text}</blockquote>"
        )

        await self._bot.send_message(
            chat_id=self._chat_id,
            text=message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
