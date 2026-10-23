import csv
import io

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Contact, Invitation, MembershipEvent
from app.phone import normalize_phone
from app.services.providers import FakeProvider, ProviderResult
from app.services.telegram_api import set_telegram_client
from tests.conftest import create_user
from tests.telegram_fake import FakeTelegram, use_telegram

_NUMBERS: list[str] = []


def numbers(count: int) -> list[str]:
    if len(_NUMBERS) < count:
        for line in range(0, 20000):
            value, _error = normalize_phone(f"+44207946{line:04d}", "GB")
            if value and value not in _NUMBERS:
                _NUMBERS.append(value)
            if len(_NUMBERS) >= count:
                break
    if len(_NUMBERS) < count:
        raise AssertionError("Could not find enough valid phone numbers")
    return _NUMBERS[:count]


def login(client, role="super_admin", email="admin@example.com"):
    email, password, _headers = create_user(role=role, email=email)
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": client.cookies.get("tagp_csrf")}


def remember(client):
    return {cookie.name: cookie.value for cookie in client.cookies.jar}


def recall(client, saved: dict[str, str]) -> None:
    client.cookies.clear()
    for name, value in saved.items():
        client.cookies.set(name, value)


def csv_bytes(rows: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


def test_login_logout_and_role_block(client):
    assert client.get("/api/v1/contacts").status_code == 401
    headers = login(client)
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "super_admin"
    logged_out = client.post("/api/v1/auth/logout", headers=headers)
    assert logged_out.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    outsider = login(client, role="read_only", email="reader@example.com")
    denied = client.post("/api/v1/campaigns", json={"name": "Nope", "outreach_channel": "telegram_invite"}, headers=outsider)
    assert denied.status_code == 403
    missing = client.post("/api/v1/auth/logout")
    assert missing.status_code == 403


def test_import_validation_duplicates_and_consent_defaults(client):
    headers = login(client)
    good, duplicate_source, invalid = numbers(2) + ["not-a-phone"]
    payload = csv_bytes(
        [
            {"Phone": good, "Name": "Ada", "Source": "sheet"},
            {"Phone": good, "Name": "Ada again", "Source": "sheet"},
            {"Phone": duplicate_source, "Name": "=HYPERLINK(\"http://example.test\")", "Source": "sheet"},
            {"Phone": invalid, "Name": "Bad", "Source": "sheet"},
        ]
    )
    preview = client.post("/api/v1/imports", files={"file": ("people.csv", payload, "text/csv")}, headers=headers)
    assert preview.status_code == 201, preview.text
    body = preview.json()
    assert body["headers"] == ["Phone", "Name", "Source"]
    committed = client.post(
        f"/api/v1/imports/{body['id']}/commit",
        json={"mapping": {"phone": "Phone", "name": "Name", "source": "Source"}, "default_region": "GB"},
        headers=headers,
    )
    assert committed.status_code == 202, committed.text
    report = committed.json()
    assert report["status"] == "completed"
    assert report["inserted_rows"] == 2
    assert report["duplicate_rows"] == 1
    assert report["invalid_rows"] == 1
    contacts = client.get("/api/v1/contacts", headers=headers).json()
    assert contacts["total"] == 2
    assert all(item["consent_status"] == "pending" for item in contacts["items"])
    assert all(item["membership_status"] == "unknown" for item in contacts["items"])
    again = client.post("/api/v1/imports", files={"file": ("people.csv", payload, "text/csv")}, headers=headers)
    second = client.post(
        f"/api/v1/imports/{again.json()['id']}/commit",
        json={"mapping": {"phone": "Phone", "name": "Name", "source": "Source"}, "default_region": "GB"},
        headers=headers,
    )
    assert second.json()["inserted_rows"] == 0
    assert second.json()["duplicate_rows"] == 3
    errors = client.get(f"/api/v1/imports/{body['id']}/errors", headers=headers)
    assert errors.status_code == 200
    assert "not valid" in errors.text or "could not be parsed" in errors.text or "Duplicate" in errors.text


def test_suppression_survives_reimport_and_withdrawal(client):
    headers = login(client)
    phone = numbers(1)[0]
    payload = csv_bytes([{"Phone": phone, "Name": "Sam"}])
    preview = client.post("/api/v1/imports", files={"file": ("one.csv", payload, "text/csv")}, headers=headers).json()
    client.post(f"/api/v1/imports/{preview['id']}/commit", json={"mapping": {"phone": "Phone", "name": "Name"}, "default_region": "GB"}, headers=headers)
    contact = client.get("/api/v1/contacts", headers=headers).json()["items"][0]
    granted = client.post(
        f"/api/v1/contacts/{contact['id']}/consents",
        json={"channel": "telegram_invite", "purpose": "channel_invitation", "source": "operator", "policy_version": "v1"},
        headers=headers,
    )
    assert granted.status_code == 201
    withdrawn = client.post(f"/api/v1/contacts/{contact['id']}/consents/{granted.json()['id']}/withdraw", headers=headers)
    assert withdrawn.json()["status"] == "withdrawn"
    suppressed = client.get(f"/api/v1/contacts/{contact['id']}", headers=headers).json()
    assert suppressed["suppression_status"] is True
    preview = client.post("/api/v1/imports", files={"file": ("one.csv", payload, "text/csv")}, headers=headers).json()
    client.post(
        f"/api/v1/imports/{preview['id']}/commit",
        json={"mapping": {"phone": "Phone", "name": "Name"}, "default_region": "GB", "apply_consent_column": True, "policy_version": "v9"},
        headers=headers,
    )
    again = client.get(f"/api/v1/contacts/{contact['id']}", headers=headers).json()
    assert again["suppression_status"] is True
    assert again["lifecycle_status"] == "SUPPRESSED"


def test_large_import_streams_in_chunks(client):
    headers = login(client)
    rows = [{"Phone": phone, "Name": f"Person {index}"} for index, phone in enumerate(numbers(800))]
    payload = csv_bytes(rows)
    preview = client.post("/api/v1/imports", files={"file": ("bulk.csv", payload, "text/csv")}, headers=headers)
    assert preview.status_code == 201
    committed = client.post(
        f"/api/v1/imports/{preview.json()['id']}/commit",
        json={"mapping": {"phone": "Phone", "name": "Name"}, "default_region": "GB"},
        headers=headers,
    )
    assert committed.status_code == 202, committed.text
    assert committed.json()["inserted_rows"] == 800
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(Contact)) == 800
    db.close()


def test_campaign_approval_launch_pause_cancel_and_frequency(client, monkeypatch):
    headers = login(client)
    phone = numbers(1)[0]
    payload = csv_bytes([{"Phone": phone, "Name": "Jo"}])
    preview = client.post("/api/v1/imports", files={"file": ("one.csv", payload, "text/csv")}, headers=headers).json()
    client.post(f"/api/v1/imports/{preview['id']}/commit", json={"mapping": {"phone": "Phone", "name": "Name"}, "default_region": "GB"}, headers=headers)
    contact = client.get("/api/v1/contacts", headers=headers).json()["items"][0]
    client.post(
        f"/api/v1/contacts/{contact['id']}/consents",
        json={"channel": "email", "purpose": "channel_invitation", "source": "form", "policy_version": "v1"},
        headers=headers,
    )
    created = client.post(
        "/api/v1/campaigns",
        json={
            "name": "April email",
            "description": "Follow up",
            "objective": "Invite consented contacts",
            "outreach_channel": "email",
            "message_template": "Hello {{name}} {{invite_link}}",
            "frequency_cap_days": 7,
            "target_audience": {"membership": "confirmed_non_member"},
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]
    preview_audience = client.post(f"/api/v1/campaigns/{campaign_id}/preview", headers=headers).json()
    assert preview_audience["eligible"] == 0
    assert preview_audience["reasons"].get("unknown_membership", 0) == 1
    client.patch(f"/api/v1/campaigns/{campaign_id}", json={"target_audience": {"membership": "any"}}, headers=headers)
    submitted = client.patch(f"/api/v1/campaigns/{campaign_id}", json={"status": "pending_approval"}, headers=headers)
    assert submitted.json()["status"] == "pending_approval"
    admin_cookies = remember(client)
    manager_headers = login(client, role="campaign_manager", email="manager@example.com")
    own = client.post(
        "/api/v1/campaigns",
        json={"name": "Manager draft", "outreach_channel": "email", "message_template": "Hi {{name}}"},
        headers=manager_headers,
    )
    own_id = own.json()["id"]
    client.patch(f"/api/v1/campaigns/{own_id}", json={"status": "pending_approval"}, headers=manager_headers)
    denied = client.post(f"/api/v1/campaigns/{own_id}/approve", headers=manager_headers)
    assert denied.status_code == 403
    recall(client, admin_cookies)
    approved = client.post(f"/api/v1/campaigns/{campaign_id}/approve", headers=headers)
    assert approved.status_code == 200
    dry = client.post(f"/api/v1/campaigns/{campaign_id}/launch", json={"dry_run": True}, headers=headers)
    assert dry.status_code == 200, dry.text
    assert dry.json()["dry_run"] is True
    assert dry.json()["status"] == "approved"
    unconfirmed = client.post(f"/api/v1/campaigns/{campaign_id}/launch", json={"confirm": False}, headers=headers)
    assert unconfirmed.status_code == 400
    monkeypatch.setattr("app.services.jobs.enqueue_dispatch", lambda _campaign_id: None)
    provider = FakeProvider()
    monkeypatch.setattr("app.services.campaigns.get_provider", lambda _channel: provider)
    launched = client.post(f"/api/v1/campaigns/{campaign_id}/launch", json={"confirm": True}, headers=headers)
    assert launched.status_code == 200, launched.text
    assert launched.json()["messages_queued"] == 1
    duplicate = client.post(f"/api/v1/campaigns/{campaign_id}/launch", json={"confirm": True}, headers=headers)
    assert duplicate.status_code == 409
    client.post(f"/api/v1/contacts/{contact['id']}/suppress", json={"reason": "asked to stop"}, headers=headers)
    from app.services.campaigns import dispatch_campaign

    db = SessionLocal()
    dispatch_campaign(db, campaign_id)
    invitation = db.scalar(select(Invitation).where(Invitation.campaign_id == campaign_id))
    assert invitation.status == "suppressed"
    assert provider.sent == 0
    db.close()


def test_pause_cancel_and_export_permissions(client, monkeypatch):
    headers = login(client)
    phone = numbers(1)[0]
    payload = csv_bytes([{"Phone": phone, "Name": "-Skip formula"}])
    preview = client.post("/api/v1/imports", files={"file": ("one.csv", payload, "text/csv")}, headers=headers).json()
    client.post(f"/api/v1/imports/{preview['id']}/commit", json={"mapping": {"phone": "Phone", "name": "Name"}, "default_region": "GB"}, headers=headers)
    contact_id = client.get("/api/v1/contacts", headers=headers).json()["items"][0]["id"]
    client.post(
        f"/api/v1/contacts/{contact_id}/consents",
        json={"channel": "sms", "purpose": "channel_invitation", "source": "form", "policy_version": "v1"},
        headers=headers,
    )
    created = client.post(
        "/api/v1/campaigns",
        json={"name": "SMS draft", "outreach_channel": "sms", "message_template": "Hello {{name}}", "frequency_cap_days": 0},
        headers=headers,
    ).json()
    client.patch(f"/api/v1/campaigns/{created['id']}", json={"status": "pending_approval"}, headers=headers)
    client.post(f"/api/v1/campaigns/{created['id']}/approve", headers=headers)
    provider = FakeProvider(result=ProviderResult(status="accepted_by_provider", detail="accepted", delivered=False))
    monkeypatch.setattr("app.services.campaigns.get_provider", lambda _channel: provider)
    launched = client.post(f"/api/v1/campaigns/{created['id']}/launch", json={"confirm": True}, headers=headers)
    assert launched.status_code == 200, launched.text
    # Completed immediately because the fake provider finishes the queue.
    assert launched.json()["campaign"]["status"] == "completed"
    paused = client.post(f"/api/v1/campaigns/{created['id']}/pause", headers=headers)
    assert paused.status_code == 409
    copy = client.post(f"/api/v1/campaigns/{created['id']}/duplicate", headers=headers)
    assert copy.status_code == 201
    assert copy.json()["status"] == "draft"
    client.patch(f"/api/v1/campaigns/{copy.json()['id']}", json={"status": "pending_approval"}, headers=headers)
    client.post(f"/api/v1/campaigns/{copy.json()['id']}/approve", headers=headers)
    monkeypatch.setattr("app.services.jobs.enqueue_dispatch", lambda _campaign_id: None)
    held = client.post(f"/api/v1/campaigns/{copy.json()['id']}/launch", json={"confirm": True}, headers=headers)
    assert held.json()["campaign"]["status"] == "running"
    paused = client.post(f"/api/v1/campaigns/{copy.json()['id']}/pause", headers=headers)
    assert paused.json()["status"] == "paused"
    cancelled = client.post(f"/api/v1/campaigns/{copy.json()['id']}/cancel", headers=headers)
    assert cancelled.json()["status"] == "cancelled"
    admin_cookies = remember(client)
    analyst = login(client, role="analyst", email="analyst@example.com")
    analyst_cookies = remember(client)
    exported = client.get("/api/v1/contacts/export", headers=analyst)
    assert exported.status_code == 403
    recall(client, admin_cookies)
    exported = client.get("/api/v1/contacts/export", headers=headers)
    assert exported.status_code == 200
    assert "'-Skip formula" in exported.text
    recall(client, analyst_cookies)
    masked = client.get("/api/v1/contacts", headers=analyst).json()["items"][0]
    assert masked["phone"] is None


def test_telegram_link_membership_and_webhook_security(client, monkeypatch):
    headers = login(client)
    fake = use_telegram(monkeypatch, FakeTelegram())
    created = client.post(
        "/api/v1/campaigns",
        json={"name": "Channel invite", "outreach_channel": "telegram_invite", "message_template": "Join {{invite_link}}"},
        headers=headers,
    ).json()
    client.patch(f"/api/v1/campaigns/{created['id']}", json={"status": "pending_approval"}, headers=headers)
    client.post(f"/api/v1/campaigns/{created['id']}/approve", headers=headers)
    link_resp = client.post(
        f"/api/v1/integrations/telegram/invite-links",
        json={"campaign_id": created["id"]},
        headers=headers,
    )
    assert link_resp.status_code == 201, link_resp.text
    link = link_resp.json()["invite_link"]
    assert link.startswith("https://t.me/+")
    launched = client.post(f"/api/v1/campaigns/{created['id']}/launch", json={"confirm": True}, headers=headers)
    assert launched.status_code == 200, launched.text
    assert launched.json().get("invite_link") is None
    assert "123456:TEST_TOKEN_SHOULD_NOT_LEAK" not in launched.text
    status = client.post("/api/v1/integrations/telegram/test", headers=headers)
    assert status.status_code == 200
    assert "123456:TEST_TOKEN_SHOULD_NOT_LEAK" not in status.text
    assert status.json()["permissions"]["can_invite_users"] is True
    assert fake.links
    open_webhook = client.post("/api/v1/webhooks/telegram", json={"update_id": 1})
    assert open_webhook.status_code == 401
    bad = client.post("/api/v1/webhooks/telegram", json={"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": "nope"})
    assert bad.status_code == 401
    payload = {
        "update_id": 50,
        "chat_member": {
            "chat": {"id": -100555, "type": "channel", "title": "Test"},
            "from": {"id": 7, "is_bot": False, "first_name": "Ada"},
            "date": 1_700_000_000,
            "old_chat_member": {"status": "left", "user": {"id": 77, "is_bot": False, "first_name": "Ada"}},
            "new_chat_member": {"status": "member", "user": {"id": 77, "is_bot": False, "first_name": "Ada"}},
            "invite_link": {"invite_link": link, "name": link_resp.json()["name"]},
        },
    }
    secret = {"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"}
    joined = client.post("/api/v1/webhooks/telegram", json=payload, headers=secret)
    assert joined.status_code == 200, joined.text
    assert joined.json()["status"] == "processed"
    again = client.post("/api/v1/webhooks/telegram", json=payload, headers=secret)
    assert again.json()["status"] == "duplicate"
    leave = {
        "update_id": 51,
        "chat_member": {
            "chat": {"id": -100555, "type": "channel"},
            "date": 1_700_000_100,
            "old_chat_member": {"status": "member", "user": {"id": 88, "is_bot": False, "first_name": "Bea"}},
            "new_chat_member": {"status": "left", "user": {"id": 88, "is_bot": False, "first_name": "Bea"}},
        },
    }
    assert client.post("/api/v1/webhooks/telegram", json=leave, headers=secret).json()["status"] == "processed"
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(MembershipEvent)) == 2
    attributed = db.scalar(select(func.count()).select_from(MembershipEvent).where(MembershipEvent.campaign_id.is_not(None)))
    assert attributed == 1
    db.close()
    overview = client.get("/api/v1/analytics/overview", headers=headers).json()
    cards = {card["key"]: card for card in overview["cards"]}
    assert cards["attributed_joins"]["value"] == 1
    assert cards["verified_departures"]["value"] == 1
    assert cards["net_channel_growth"]["value"] == 0
    set_telegram_client(None)


def test_analytics_zero_denominator_and_missing_membership(client):
    headers = login(client)
    overview = client.get("/api/v1/analytics/overview", headers=headers).json()
    cards = {card["key"]: card for card in overview["cards"]}
    assert cards["imported_contacts"]["value"] == 0
    assert cards["imported_contacts"]["value_state"] == "known"
    assert cards["attributed_joins"]["value_state"] == "missing"
    assert cards["conversion_rate"]["value_state"] == "zero_denominator"
    assert cards["cost_per_attributed_join"]["value_state"] == "missing"
    filtered = client.get("/api/v1/analytics/overview?from=2000-01-01&to=2000-01-02", headers=headers).json()
    assert {card["key"]: card["value"] for card in filtered["cards"]}["imported_contacts"] == 0
    retention = client.get("/api/v1/analytics/retention", headers=headers).json()
    assert retention["completeness"] == "missing"


def test_unknown_membership_is_not_a_confirmed_non_join(client):
    headers = login(client)
    phone = numbers(1)[0]
    payload = csv_bytes([{"Phone": phone, "Name": "Unknown"}])
    preview = client.post("/api/v1/imports", files={"file": ("one.csv", payload, "text/csv")}, headers=headers).json()
    client.post(f"/api/v1/imports/{preview['id']}/commit", json={"mapping": {"phone": "Phone", "name": "Name"}, "default_region": "GB"}, headers=headers)
    contact = client.get("/api/v1/contacts", headers=headers).json()["items"][0]
    assert contact["membership_status"] == "unknown"
    assert contact["lifecycle_status"] != "NOT_JOINED_CONFIRMED"


def test_invalid_telegram_token_and_permissions(client, monkeypatch):
    headers = login(client)
    use_telegram(monkeypatch, FakeTelegram(fail="token"))
    status = client.get("/api/v1/integrations/telegram/status", headers=headers)
    assert "123456:TEST_TOKEN_SHOULD_NOT_LEAK" not in status.text
    assert status.json()["recent_errors"]
    use_telegram(monkeypatch, FakeTelegram(member_status="member"))
    report = client.post("/api/v1/integrations/telegram/test", headers=headers).json()
    assert report["permissions"]["administrator"] is False
    created = client.post(
        "/api/v1/campaigns",
        json={"name": "No rights", "outreach_channel": "telegram_invite", "message_template": "Hi"},
        headers=headers,
    ).json()
    client.patch(f"/api/v1/campaigns/{created['id']}", json={"status": "pending_approval"}, headers=headers)
    client.post(f"/api/v1/campaigns/{created['id']}/approve", headers=headers)
    use_telegram(monkeypatch, FakeTelegram(fail="rights"))
    failed = client.post(f"/api/v1/campaigns/{created['id']}/launch", json={"confirm": True}, headers=headers)
    assert failed.status_code == 422
    set_telegram_client(None)
