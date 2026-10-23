# Troubleshooting

| Symptom | What to check |
| --- | --- |
| Startup says a secret is missing | Fill `.env` from `.env.example`. Production rejects empty and placeholder values. |
| Login returns 401 | The administrator is created only when `ADMIN_EMAIL` and `ADMIN_PASSWORD` are present at startup. The password must be 12 to 64 characters. |
| Login returns 429 | The login limiter allows 10 attempts per minute per address. |
| Changes return CSRF errors | The browser must call the Next.js origin so the `tagp_csrf` cookie is present. Direct calls need the `X-CSRF-Token` header. |
| Import stays queued | With `TASK_MODE=celery`, the worker must be running and `REDIS_URL` must connect. Without Redis, use `TASK_MODE=thread`. |
| Test connection shows no bot | `BOT_TOKEN` is empty or Telegram rejected it. The token is not displayed. |
| Bot is not an administrator | Add the bot in channel settings and grant invite permission, then test again. |
| Launch says Telegram is not configured | Set both `BOT_TOKEN` and `TELEGRAM_CHANNEL_ID`. |
| Invite link never appears | Launch failed before Telegram returned a URL. The app does not invent `t.me` links. |
| Join did not attribute | The membership update must include the invite link. Joins without it are unattributed. A phone number is never matched by itself. |
| Webhook returns 401 | The secret header does not match `TELEGRAM_WEBHOOK_SECRET`. |
| Dashboard membership says No data | The bot is not configured and no events are stored. That is missing data, not zero joins. |
| Provider launch returns 422 | Email, SMS, or WhatsApp credentials are empty. Use a Telegram invite campaign or configure the provider. |
| Phone numbers unreadable after a restart | `PHONE_ENCRYPTION_KEY` changed. Restore the original key. |

Logs are JSON on stdout. They should never contain the bot token, passwords, or session cookies. If a provider error includes one of those values, the redaction filter replaces the configured secrets.
