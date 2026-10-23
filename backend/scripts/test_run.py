"""One-shot API test run for a single contact. Run from backend with venv active."""

import io
import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
EMAIL = "admin@example.com"
PASSWORD = "Harbor-admin-2026"
PHONE = "+918299139164"
NAME = "Vikku test contact"


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=60.0)
    login = c.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if login.status_code != 200:
        print("LOGIN FAILED", login.status_code, login.text)
        return 1
    csrf = c.cookies.get("tagp_csrf")
    headers = {"X-CSRF-Token": csrf} if csrf else {}

    health = c.get("/health").json()
    print("HEALTH", json.dumps(health, indent=2))

    tg = c.post("/api/v1/integrations/telegram/test", headers=headers)
    print("TELEGRAM_TEST", tg.status_code)
    if tg.status_code == 200:
        body = tg.json()
        print(
            "  bot:",
            body.get("bot_username"),
            "| admin:",
            body.get("administrator"),
            "| invite:",
            body.get("permissions", {}).get("can_invite_users"),
        )
        if body.get("recent_errors"):
            print("  errors:", body["recent_errors"][:2])
    else:
        print(" ", tg.text[:400])

    csv = f"phone,name,source\n{PHONE},{NAME},test_run\n"
    imp = c.post(
        "/api/v1/imports",
        headers=headers,
        files={"file": ("test_run.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    print("IMPORT_PREVIEW", imp.status_code)
    if imp.status_code != 201:
        print(imp.text)
        return 1
    batch_id = imp.json()["id"]
    commit = c.post(
        f"/api/v1/imports/{batch_id}/commit",
        headers=headers,
        json={
            "mapping": {"phone": "phone", "name": "name", "source": "source"},
            "default_region": "IN",
            "default_source": "test_run",
        },
    )
    print("IMPORT_COMMIT", commit.status_code, commit.json().get("status"))
    for _ in range(30):
        row = c.get(f"/api/v1/imports/{batch_id}", headers=headers).json()
        if row["status"] in {"completed", "failed", "cancelled"}:
            print(
                "IMPORT_RESULT",
                row["status"],
                "inserted",
                row.get("inserted_rows"),
                "dup",
                row.get("duplicate_rows"),
                "invalid",
                row.get("invalid_rows"),
            )
            break
        time.sleep(0.5)

    contacts = c.get("/api/v1/contacts?q=39164", headers=headers).json()
    items = contacts.get("items") or []
    if not items:
        print("CONTACT not found after import")
        return 1
    contact = items[0]
    cid = contact["id"]
    print("CONTACT", cid, contact.get("phone_masked"), contact.get("lifecycle_status"))

    consent = c.post(
        f"/api/v1/contacts/{cid}/consents",
        headers=headers,
        json={
            "channel": "telegram_invite",
            "purpose": "channel_invitation",
            "source": "operator_test_run",
            "policy_version": "test-1",
        },
    )
    print("CONSENT", consent.status_code, consent.json().get("status") if consent.status_code == 201 else consent.text[:200])

    contact = c.get(f"/api/v1/contacts/{cid}", headers=headers).json()
    print("CONTACT_AFTER", contact.get("lifecycle_status"), contact.get("consent_status"))

    camp = c.post(
        "/api/v1/campaigns",
        headers=headers,
        json={
            "name": "Test run Mahadev invite",
            "objective": "Single-contact test",
            "outreach_channel": "telegram_invite",
            "message_template": "Hello {{name}} join here {{invite_link}}",
            "target_audience": {"membership": "any"},
            "frequency_cap_days": 0,
        },
    )
    print("CAMPAIGN_CREATE", camp.status_code)
    if camp.status_code != 201:
        print(camp.text)
        return 1
    campaign_id = camp.json()["id"]

    preview = c.post(f"/api/v1/campaigns/{campaign_id}/preview", headers=headers).json()
    print("AUDIENCE_PREVIEW eligible", preview.get("eligible"), "reasons", preview.get("reasons"))

    c.patch(f"/api/v1/campaigns/{campaign_id}", headers=headers, json={"status": "pending_approval"})
    appr = c.post(f"/api/v1/campaigns/{campaign_id}/approve", headers=headers)
    print("APPROVE", appr.status_code)

    launch = c.post(
        f"/api/v1/campaigns/{campaign_id}/launch",
        headers=headers,
        json={"confirm": True, "dry_run": False},
    )
    print("LAUNCH", launch.status_code)
    if launch.status_code == 200:
        data = launch.json()
        print("  invite_link:", data.get("invite_link"))
        print("  campaign_status:", data.get("campaign", {}).get("status"))
    else:
        print(" ", launch.text[:500])

    print("DONE open http://localhost:3000/contacts and campaign", campaign_id)
    return 0 if launch.status_code == 200 else 2


if __name__ == "__main__":
    sys.exit(main())
