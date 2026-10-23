"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Banner, Button, Field, controlClass } from "@/components/ui";

export default function NewCampaignPage() {
  const router = useRouter();
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const created = await api<{ id: string }>("/api/v1/campaigns", {
        method: "POST",
        body: JSON.stringify({
          name: form.get("name"),
          description: form.get("description"),
          objective: form.get("objective"),
          outreach_channel: form.get("outreach_channel"),
          message_template: form.get("message_template"),
          frequency_cap_days: Number(form.get("frequency_cap_days") || 7),
          target_audience: { membership: form.get("membership") },
          start_at: form.get("start_at") || null,
          end_at: form.get("end_at") || null,
          actual_cost_cents: form.get("actual_cost") ? Math.round(Number(form.get("actual_cost")) * 100) : null,
        }),
      });
      router.push(`/campaigns/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the campaign");
    }
  }

  return (
    <form onSubmit={onSubmit} className="mx-auto max-w-2xl space-y-4">
      <h1 className="font-display text-4xl">New campaign</h1>
      {error && <Banner tone="error">{error}</Banner>}
      <Field label="Name"><input name="name" className={controlClass} required /></Field>
      <Field label="Objective"><input name="objective" className={controlClass} required /></Field>
      <Field label="Description"><textarea name="description" className={controlClass} rows={3} /></Field>
      <Field label="Channel">
        <select name="outreach_channel" className={controlClass} defaultValue="telegram_channel_add">
          <option value="telegram_channel_add">Add to channel (linked Telegram accounts only)</option>
          <option value="telegram_invite">Telegram invite link (manual, not auto-generated on launch)</option>
          <option value="telegram_dm">Telegram bot message, only after the person starts the bot</option>
          <option value="email">Email, if SMTP is configured</option>
          <option value="sms">SMS, if a provider is configured</option>
          <option value="whatsapp">WhatsApp, if a provider is configured</option>
        </select>
      </Field>
      <Field label="Audience rule">
        <select name="membership" className={controlClass} defaultValue="any">
          <option value="any">Consented contacts who are not verified members</option>
          <option value="confirmed_non_member">Confirmed non-members only</option>
          <option value="unknown">Unknown membership only</option>
        </select>
      </Field>
      <Field label="Message template">
        <textarea name="message_template" className={controlClass} rows={4} defaultValue="Hello {{name}}. The channel invite is {{invite_link}}" />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Starts"><input name="start_at" type="datetime-local" className={controlClass} /></Field>
        <Field label="Ends"><input name="end_at" type="datetime-local" className={controlClass} /></Field>
        <Field label="Frequency cap, days"><input name="frequency_cap_days" type="number" min={0} defaultValue={7} className={controlClass} /></Field>
        <Field label="Actual cost, optional"><input name="actual_cost" type="number" min={0} step="0.01" className={controlClass} /></Field>
      </div>
      <Button type="submit">Save draft</Button>
    </form>
  );
}
