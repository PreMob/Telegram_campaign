# Deployment

1. Provision PostgreSQL 16 and Redis 7. Put both on a private network.
2. Set the production variables from `.env.example`. `ENVIRONMENT=production` requires PostgreSQL, distinct secrets, and `TELEGRAM_WEBHOOK_SECRET`.
3. Build the images from `docker compose` or run the same commands in your platform:

```bash
docker compose up --build -d
```

4. Confirm `https://your-api-host/health` reports database and redis as ok.
5. Create the first administrator through `ADMIN_EMAIL` and `ADMIN_PASSWORD`, then change the password by creating a new super admin and deactivating the bootstrap account if you want a rotation.
6. Put TLS in front of both the web app and the API. Set `CORS_ORIGINS` to the public site origin.
7. Register the Telegram webhook against the API host, not the Next.js origin. See `docs/telegram-setup.md`.
8. Run the Celery worker and beat processes. Beat reconciles voluntarily linked members, starts scheduled campaigns, applies retention, and stores an analytics snapshot.
9. Configure an outreach provider only for a channel you are allowed to use. Leave SMS, email, and WhatsApp blank until credentials exist.
10. Take a PostgreSQL backup and keep the phone keys with the backup procedure in `docs/security.md`.

The web container proxies API calls to `http://api:8000`. Do not expose Redis or PostgreSQL publicly.
