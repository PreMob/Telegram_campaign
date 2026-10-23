# Telegram setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token into `BOT_TOKEN`. Do not commit it.
2. Add the bot to your channel as an administrator with permission to invite users via link.
3. Put the channel id in `TELEGRAM_CHANNEL_ID`. For a public channel this can be `@name`. For a private channel, use the numeric id, usually starting with `-100`. Forward a channel post to [@userinfobot](https://t.me/userinfobot) or read `my_chat_member` when the bot is added.
4. Set `TELEGRAM_WEBHOOK_SECRET` to a long random string.
5. Set `ADMIN_USER_ID` to your own numeric Telegram id. Only that account can use `/myid` and `/invite`.
6. Expose the API with HTTPS. Telegram will not deliver webhooks to a bare local port.
7. Register the webhook. Replace the host and secret. The secret is sent as a header, not as a query parameter.

```bash
curl "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -d "url=https://your-api-host/api/v1/webhooks/telegram" \
  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}" \
  -d "allowed_updates=[\"message\",\"chat_member\",\"my_chat_member\",\"chat_join_request\"]"
```

8. Open Integrations → Telegram and run Test connection. The bot username should appear, and the permission checklist should show an administrator who can invite users.
9. Create a campaign with the Telegram invite channel, submit it, approve it, and launch it. The invite URL on the campaign page is the URL Telegram returned.
10. Join that link from a Telegram account. The next membership update should appear as an attributed join when the update includes the invite link.
11. Optional identity link: on a contact, create a link code and ask the person to send `/start <code>` to the bot. The code contains no phone number, expires in seven days, and works once. Only then can a membership event be attached to that contact, and only then can a bot direct message be considered.

If the token, channel, or administrator permission is missing, launch fails with a configuration error and does not pretend a link was created.
