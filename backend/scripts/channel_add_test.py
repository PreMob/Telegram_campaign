"""Add linked Telegram users to the channel (no invite link). Run from backend/."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

BASE = "http://127.0.0.1:8000"
EMAIL = "admin@example.com"
PASSWORD = "Harbor-admin-2026"
PHONE_QUERY = "39164"
ADMIN_TELEGRAM_ID = "1684967476"


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=90.0)
    login = c.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if login.status_code != 200:
        print("LOGIN FAILED", login.text)
        return 1
    csrf = c.cookies.get("tagp_csrf")
    headers = {"X-CSRF-Token": csrf} if csrf else {}

    contacts = c.get(f"/api/v1/contacts?q={PHONE_QUERY}", headers=headers).json().get("items") or []
    if not contacts:
        print("No contact found for", PHONE_QUERY)
        return 1
    contact = contacts[0]
    cid = contact["id"]
    print("CONTACT", cid, contact.get("phone_masked"))

    # Link admin Telegram account to this contact for addChatMember.
    detail = c.get(f"/api/v1/contacts/{cid}", headers=headers).json()
    prefs = dict(detail.get("communication_preferences") or {})
    prefs["telegram_chat_id"] = ADMIN_TELEGRAM_ID
    prefs["telegram_user_id"] = ADMIN_TELEGRAM_ID
    # No public PATCH for prefs — use direct DB for operator test.
    from app.database import SessionLocal, init_engine
    from app.models import Contact
    from app.services.state import refresh_contact_state

    init_engine()
    db = SessionLocal()
    row = db.get(Contact, cid)
    row.communication_preferences = prefs
    refresh_contact_state(db, row)
    db.commit()
    db.close()
    print("LINKED telegram_user_id", ADMIN_TELEGRAM_ID)

    c.post(
        f"/api/v1/contacts/{cid}/consents",
        headers=headers,
        json={
            "channel": "telegram_channel_add",
            "purpose": "channel_invitation",
            "source": "operator_channel_add_test",
            "policy_version": "test-1",
        },
    )

    camp = c.post(
        "/api/v1/campaigns",
        headers=headers,
        json={
            "name": f"Channel add test {int(time.time())}",
            "objective": "Add linked members without invite URL",
            "outreach_channel": "telegram_channel_add",
            "message_template": "Channel membership",
            "target_audience": {"membership": "any"},
            "frequency_cap_days": 0,
        },
    )
    if camp.status_code != 201:
        print("CAMPAIGN_CREATE FAILED", camp.status_code, camp.text)
        return 2
    campaign_id = camp.json()["id"]
    preview = c.post(f"/api/v1/campaigns/{campaign_id}/preview", headers=headers).json()
    print("PREVIEW eligible", preview.get("eligible"), preview.get("reasons"))

    c.patch(f"/api/v1/campaigns/{campaign_id}", headers=headers, json={"status": "pending_approval"})
    c.post(f"/api/v1/campaigns/{campaign_id}/approve", headers=headers)
    launch = c.post(
        f"/api/v1/campaigns/{campaign_id}/launch",
        headers=headers,
        json={"confirm": True, "dry_run": False},
    )
    print("LAUNCH", launch.status_code, launch.text[:500])
    if launch.status_code != 200:
        return 2

    for _ in range(20):
        row = c.get(f"/api/v1/campaigns/{campaign_id}", headers=headers).json()
        if row.get("status") in {"completed", "failed"}:
            print("CAMPAIGN_STATUS", row.get("status"))
            break
        time.sleep(0.5)
    else:
        from app.services.campaigns import dispatch_campaign
        from app.database import SessionLocal, init_engine

        init_engine()
        db = SessionLocal()
        print("DISPATCH", dispatch_campaign(db, campaign_id))
        db.close()

    timeline = c.get(f"/api/v1/contacts/{cid}/timeline", headers=headers).json()
    invites = [e for e in timeline.get("events", []) if e.get("type") == "invitation"]
    print("INVITATIONS", json.dumps(invites[:3], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
