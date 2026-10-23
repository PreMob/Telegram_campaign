# Security notes

- Passwords are hashed with bcrypt. Sessions are signed JWTs in an HttpOnly cookie, with a separate CSRF cookie checked on every change except login and the Telegram webhook.
- The webhook requires `X-Telegram-Bot-Api-Secret-Token` to match `TELEGRAM_WEBHOOK_SECRET`.
- Authorization is enforced on the server for every contact, campaign, export, and settings route.
- Phone numbers are encrypted with a key derived from `PHONE_ENCRYPTION_KEY`. Lookup uses HMAC-SHA256 with a different secret. A plain hash of a phone number is not treated as anonymization.
- Analysts and read-only users receive a masked phone. Export is limited to super admins and campaign managers and writes an audit event.
- CSV export prefixes values that start with `=`, `+`, `-`, `@`, or a tab so a spreadsheet does not treat them as formulas.
- Logs pass through a redaction filter for the bot token and application secrets.
- Bot tokens are not returned by the status endpoint and are not stored in ordinary tables.
- Imports cannot clear suppression or replace a withdrawn consent on an existing contact.
- Erasure removes the phone number and name and keeps the anonymous id for historical counts.
- Production startup refuses placeholder secrets and refuses SQLite.
- Review consent, messaging, and privacy rules for your jurisdiction before using a live contact list. This repository does not provide legal advice.

Backups: dump PostgreSQL on a schedule (`pg_dump`) and store the dump, plus the encryption and HMAC secrets, in a separate secret manager. A database backup cannot be read back into phone numbers without `PHONE_ENCRYPTION_KEY`. Restoring a backup with a different HMAC key makes existing numbers look new.
