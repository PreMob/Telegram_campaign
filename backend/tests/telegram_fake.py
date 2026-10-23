from app.services.telegram_api import TelegramError, set_telegram_client


class FakeTelegram:
    def __init__(self, fail: str | None = None, member_status: str = "administrator"):
        self.fail = fail
        self.member_status = member_status
        self.links = []
        self.messages = []

    def get_me(self):
        if self.fail == "token":
            raise TelegramError("Telegram rejected the bot token", permanent=True)
        return {"id": 4242, "username": "audience_bot", "is_bot": True}

    def get_chat(self, chat_id):
        return {"id": chat_id, "type": "channel", "title": "Test"}

    def get_chat_member(self, chat_id, user_id):
        if self.fail == "channel":
            raise TelegramError("chat not found", permanent=True)
        return {
            "status": self.member_status,
            "can_invite_users": self.member_status in {"administrator", "creator"},
            "user_id": str(user_id),
        }

    def create_chat_invite_link(self, chat_id, name):
        if self.fail == "rights":
            raise TelegramError("not enough rights to manage invite links", permanent=True)
        url = f"https://t.me/+{name}"
        self.links.append(url)
        return {"invite_link": url, "name": name}

    def send_message(self, chat_id, text):
        self.messages.append((str(chat_id), text))
        return {"message_id": len(self.messages)}


def use_telegram(monkeypatch, fake: FakeTelegram | None = None):
    fake = fake or FakeTelegram()
    set_telegram_client(fake)
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "bot_token", "123456:TEST_TOKEN_SHOULD_NOT_LEAK")
    monkeypatch.setattr(settings, "telegram_channel_id", "-100555")
    return fake
