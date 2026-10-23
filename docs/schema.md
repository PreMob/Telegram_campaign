# Schema

Internal ids are UUID strings. Timestamps are UTC. Phone numbers are stored as ciphertext plus a keyed HMAC, with the last four digits kept for masked display.

| Table | Role |
| --- | --- |
| users, roles | Operators and the four roles |
| contacts | Unique people, keyed by phone HMAC |
| import_batches, import_errors | File preview, progress, and row errors |
| consents | Channel and purpose specific consent, including withdrawal |
| suppression_records | Active blocks checked before outreach |
| campaigns, campaign_audiences, campaign_events | Configuration, preview snapshots, and the activity log |
| campaign_links | Invite URLs returned by Telegram |
| invitations, provider_messages | One delivery attempt and the provider response |
| telegram_identities, contact_identity_links | Voluntary link between a contact and a Telegram user |
| membership_events | Joins, leaves, and verified non-member results |
| webhook_inbox | Deduplicated Telegram updates |
| job_runs | Background job status |
| audit_logs | Sensitive operator actions |
| system_settings | Policy, retention, and integration error notes |

Unique constraints stop duplicate phone hashes, duplicate Telegram update ids, duplicate invitation keys, and duplicate membership idempotency keys. A second delivery of the same update does not add another join.

SQLite is used for tests. PostgreSQL is the deployment database. The initial Alembic revision creates the model metadata.
