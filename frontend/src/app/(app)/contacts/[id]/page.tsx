"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { Banner, Button, Field, Modal, StatusPill, controlClass } from "@/components/ui";

type Contact = {
  id: string;
  name: string | null;
  phone: string | null;
  phone_masked: string;
  source: string;
  consent_status: string;
  suppression_status: boolean;
  membership_status: string;
  lifecycle_status: string;
  is_demo: boolean;
  created_at: string;
};

type TimelineEvent = { at: string; type: string; summary: string; details: Record<string, unknown> };
type Consent = { id: string; channel: string; purpose: string; status: string; source: string; policy_version: string; created_at: string };

export default function ContactDetailPage() {
  const params = useParams<{ id: string }>();
  const [contact, setContact] = useState<Contact | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [consents, setConsents] = useState<Consent[]>([]);
  const [error, setError] = useState("");
  const [token, setToken] = useState("");
  const [confirm, setConfirm] = useState<"suppress" | "erase" | null>(null);
  const [reason, setReason] = useState("Operator suppression");
  const [policy, setPolicy] = useState("v1");

  async function load() {
    const [person, timeline, consentRows] = await Promise.all([
      api<Contact>(`/api/v1/contacts/${params.id}`),
      api<{ events: TimelineEvent[] }>(`/api/v1/contacts/${params.id}/timeline`),
      api<{ items: Consent[] }>(`/api/v1/contacts/${params.id}/consents`),
    ]);
    setContact(person);
    setEvents(timeline.events);
    setConsents(consentRows.items);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [params.id]);

  async function grant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api(`/api/v1/contacts/${params.id}/consents`, {
      method: "POST",
      body: JSON.stringify({
        channel: form.get("channel"),
        purpose: "channel_invitation",
        source: form.get("source"),
        policy_version: policy,
      }),
    });
    await load();
  }

  async function act() {
    if (confirm === "suppress") {
      await api(`/api/v1/contacts/${params.id}/suppress`, { method: "POST", body: JSON.stringify({ reason }) });
    }
    if (confirm === "erase") {
      await api(`/api/v1/contacts/${params.id}/erase`, { method: "POST" });
    }
    setConfirm(null);
    await load();
  }

  if (!contact) return error ? <Banner tone="error">{error}</Banner> : <p>Loading contact…</p>;

  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs uppercase tracking-wide text-ink/50">{contact.is_demo ? "Demo contact" : "Contact"}</p>
        <h1 className="font-display text-4xl">{contact.name || "Unnamed contact"}</h1>
        <p className="mt-1 text-sm">{contact.phone || contact.phone_masked} · {contact.source}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <StatusPill value={contact.consent_status} />
          <StatusPill value={contact.membership_status} />
          <StatusPill value={contact.lifecycle_status} />
        </div>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      {contact.membership_status === "unknown" && <Banner>Membership is unknown. That is not a confirmed non-join.</Banner>}
      <div className="grid gap-4 lg:grid-cols-[1.1fr_.9fr]">
        <section className="rounded-3xl border border-line bg-panel p-4">
          <h2 className="font-display text-2xl">Timeline</h2>
          <ol className="mt-4 space-y-3">
            {events.map((item, index) => (
              <li key={`${item.type}-${index}`} className="border-l-2 border-line pl-3">
                <p className="text-xs text-ink/50">{item.at} · {item.type}</p>
                <p className="text-sm">{item.summary}</p>
              </li>
            ))}
          </ol>
        </section>
        <div className="space-y-4">
          <form onSubmit={(event) => grant(event).catch((err) => setError(err.message))} className="space-y-3 rounded-3xl border border-line bg-panel p-4">
            <h2 className="font-display text-2xl">Record consent</h2>
            <Field label="Channel">
              <select name="channel" className={controlClass} defaultValue="telegram_channel_add">
                <option value="telegram_channel_add">Add to channel</option>
                <option value="telegram_invite">Telegram invite</option>
                <option value="telegram_dm">Telegram bot message</option>
                <option value="email">Email</option>
                <option value="sms">SMS</option>
                <option value="whatsapp">WhatsApp</option>
              </select>
            </Field>
            <Field label="Source of consent">
              <input name="source" className={controlClass} required placeholder="web form, signed notice, operator note" />
            </Field>
            <Field label="Policy version">
              <input className={controlClass} value={policy} onChange={(event) => setPolicy(event.target.value)} />
            </Field>
            <Button type="submit">Save granted consent</Button>
            <p className="text-xs text-ink/60">Saving consent does not remove an existing suppression. Withdrawal suppresses the contact.</p>
          </form>
          <section className="rounded-3xl border border-line bg-panel p-4">
            <h2 className="font-display text-2xl">Consent history</h2>
            <ul className="mt-3 space-y-2 text-sm">
              {consents.length === 0 && <li>No consent records.</li>}
              {consents.map((consent) => (
                <li key={consent.id} className="flex items-center justify-between gap-2">
                  <span>{consent.channel} · {consent.status} · {consent.policy_version}</span>
                  {consent.status === "granted" && <Button tone="ghost" onClick={() => api(`/api/v1/contacts/${params.id}/consents/${consent.id}/withdraw`, { method: "POST" }).then(load).catch((err) => setError(err.message))}>Withdraw</Button>}
                </li>
              ))}
            </ul>
          </section>
          <div className="flex flex-wrap gap-2">
            <Button tone="ghost" onClick={() => setConfirm("suppress")}>Suppress</Button>
            <Button tone="danger" onClick={() => setConfirm("erase")}>Erase personal data</Button>
            <Button tone="ghost" onClick={() => api<{ token: string; instructions: string }>(`/api/v1/contacts/${params.id}/identity-link`, { method: "POST" }).then((data) => setToken(`${data.instructions} Code: ${data.token}`)).catch((err) => setError(err.message))}>Create link code</Button>
          </div>
          {token && <Banner>{token}</Banner>}
        </div>
      </div>
      {confirm && (
        <Modal
          title={confirm === "erase" ? "Erase this contact?" : "Suppress this contact?"}
          body={confirm === "erase" ? "The phone number and name will be removed. Historical events stay attached to an anonymous id." : "Suppression is checked before every campaign action. A later import will not undo it."}
          confirmLabel={confirm === "erase" ? "Erase" : "Suppress"}
          danger={confirm === "erase"}
          onCancel={() => setConfirm(null)}
          onConfirm={() => act().catch((err) => setError(err.message))}
        />
      )}
      {confirm === "suppress" && <span className="sr-only">{reason}</span>}
    </div>
  );
}
