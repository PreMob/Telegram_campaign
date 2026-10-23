# Telegram Audience Growth Platform

Harbor is a consent-aware desk for a public Telegram channel. It imports contacts, keeps suppression and consent, creates official Bot API invite links, records membership updates Telegram actually sends, and shows those numbers on a dashboard.

Telegram does not offer an API that turns a list of phone numbers into Telegram accounts, and it does not let a bot add 40,000 people to a channel. This application does not scrape, guess accounts, or send bulk messages from a personal Telegram login.

## What the Bot API can and cannot do

It can:

- Confirm the bot identity with `getMe`.
- Check whether the bot is an administrator.
- Create a named chat invite link with `createChatInviteLink`.
- Receive `chat_member` updates when the bot is an administrator and those updates are enabled.
- Record a join, leave, or join request that Telegram includes in an update.
- Message a person in private only after that person has started the bot.

It cannot:

- Look up which phone numbers have Telegram accounts.
- Add a phone list to a channel.
- Report a complete historical member list.
- Tell you that someone did not join merely because no event arrived.
- Prove delivery of an email, SMS, or WhatsApp message just because a provider accepted the request.

Unknown membership stays unknown until Telegram, or a reconciliation call for a voluntarily linked account, says otherwise.

## Stack

- Next.js, React, and Tailwind for the interface.
- FastAPI, SQLAlchemy, Alembic, and Pydantic for the API.
- PostgreSQL in Docker. Tests and a lightweight local mode use SQLite.
- Redis and Celery when `REDIS_URL` is set. Without Redis, imports and campaign sends run in a background thread.
- `python-telegram-bot` for official Bot API calls.

## Run with Docker

1. Copy the environment template and fill in the secrets.

```powershell
Copy-Item .env.example .env
```

Generate three different secrets and an administrator password of at least 12 characters. Put them in `APP_SECRET_KEY`, `PHONE_ENCRYPTION_KEY`, `PHONE_HMAC_KEY`, and `ADMIN_PASSWORD`.

2. Start the stack.

```powershell
docker compose up --build
```

3. Open http://localhost:3000 and sign in with `ADMIN_EMAIL` and `ADMIN_PASSWORD`.

The API documentation is at http://localhost:8000/docs. Health is at http://localhost:8000/health.

## Run the API and web app on your machine

PostgreSQL and Redis can still come from Docker:

```powershell
docker compose up postgres redis
```

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
$env:DATABASE_URL = "postgresql+psycopg://tagp:tagp@localhost:5432/tagp"
$env:REDIS_URL = "redis://localhost:6379/0"
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

The API reads `.env` from the working directory. Start uvicorn from the repository root, or set the variables in the shell. From `backend`, point the env file at the repository root or export the variables above together with the secrets.

A SQLite file is the lightweight alternative when Docker is not running:

```powershell
$env:DATABASE_URL = "sqlite+pysqlite:///./data/dev.db"
$env:REDIS_URL = ""
$env:TASK_MODE = "thread"
```

Frontend, in another terminal:

```powershell
cd frontend
npm install
npm run dev
```

## Tests

```powershell
cd backend
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
cd ..\frontend
npm test
npm run typecheck
npm run lint
```

Tests mock Telegram. They do not send messages and they do not call the live Bot API.

## Environment variables

Mandatory:

| Name | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL in Docker and production. SQLite is only for tests and local lightweight mode. |
| `APP_SECRET_KEY` | Session signing. |
| `PHONE_ENCRYPTION_KEY` | Encrypts stored phone numbers. A long passphrase is accepted and derived into a Fernet key. |
| `PHONE_HMAC_KEY` | Separate keyed hash used to find duplicates. This is not a plain SHA of the phone number. |
| `ADMIN_EMAIL` | First administrator, created on startup if missing. |
| `ADMIN_PASSWORD` | 12 to 64 characters. |

Mandatory in production, optional until you connect Telegram:

| Name | Purpose |
| --- | --- |
| `BOT_TOKEN` | BotFather token. Never put this in the browser or in logs. |
| `TELEGRAM_CHANNEL_ID` | Channel id such as `-100...` or `@channel`. |
| `TELEGRAM_WEBHOOK_SECRET` | Value Telegram sends in `X-Telegram-Bot-Api-Secret-Token`. |
| `REDIS_URL` | Required for Celery. Without it, work runs in a thread. |
| `ADMIN_USER_ID` | Numeric Telegram user id allowed to use `/myid` and `/invite`. |

Optional: `SEED_DEMO`, `SMTP_*`, `SMS_API_URL`, `SMS_API_TOKEN`, `WHATSAPP_API_URL`, `WHATSAPP_API_TOKEN`, `TASK_MODE`, `DEFAULT_REGION`.

`SEED_DEMO=true` inserts clearly named demo contacts and events. It does not invent a Telegram invite URL.

## Manual Telegram setup

See [docs/telegram-setup.md](docs/telegram-setup.md).

## Further reading

- [Product requirements](docs/prd.md)
- [Architecture](docs/architecture.md)
- [Database schema](docs/schema.md)
- [Metrics](docs/metrics.md)
- [Security](docs/security.md)
- [Deployment](docs/deployment.md)
- [Troubleshooting](docs/troubleshooting.md)

## Sample file

`samples/contacts_sample.csv` contains fictional numbers for the import screen. Review the error report after import; numbers that fail validation are reported rather than stored.
