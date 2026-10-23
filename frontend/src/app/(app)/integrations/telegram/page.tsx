"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Banner, Button } from "@/components/ui";

type Status = {
  configured: boolean;
  channel_id: string | null;
  webhook_secret_set: boolean;
  bot_username: string | null;
  administrator: boolean | null;
  permissions: { administrator: boolean; can_invite_users: boolean; can_receive_membership_updates: boolean };
  last_event_at: string | null;
  recent_errors: { message: string; at?: string }[];
  mode: string;
};

export default function TelegramPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");

  async function load() {
    setStatus(await api<Status>("/api/v1/integrations/telegram/status"));
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="font-display text-4xl">Telegram</h1>
        <p className="max-w-2xl text-sm text-ink/70">The bot uses the official Bot API. It can create invite links and record chat member updates when it is an administrator. It cannot search Telegram by phone number or force people into the channel.</p>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      {status && (
        <div className="grid gap-3 md:grid-cols-2">
          <Info label="Bot" value={status.bot_username ? `@${status.bot_username}` : "Not connected"} />
          <Info label="Channel" value={status.channel_id || "Not set"} />
          <Info label="Webhook secret" value={status.webhook_secret_set ? "Set" : "Missing"} />
          <Info label="Last membership event" value={status.last_event_at || "None recorded"} />
          {Object.entries(status.permissions).map(([key, value]) => <Info key={key} label={key.replaceAll("_", " ")} value={value ? "Yes" : "No"} />)}
        </div>
      )}
      <Button onClick={() => api("/api/v1/integrations/telegram/test", { method: "POST" }).then(load).catch((err) => setError(err.message))}>Test connection</Button>
      <section className="rounded-3xl border border-line bg-panel p-4">
        <h2 className="font-display text-2xl">Recent errors</h2>
        <ul className="mt-3 space-y-2 text-sm">
          {(status?.recent_errors || []).length === 0 && <li>No integration errors stored.</li>}
          {(status?.recent_errors || []).map((item, index) => <li key={index}>{item.message}</li>)}
        </ul>
      </section>
      <section className="rounded-3xl border border-line bg-panel p-4 text-sm leading-6">
        <h2 className="font-display text-2xl">Required bot permissions</h2>
        <ul className="mt-2 list-disc pl-5">
          <li>Administrator of the channel.</li>
          <li>Permission to invite users via link.</li>
          <li>Privacy mode disabled is not required for channel membership updates, but the bot must receive chat_member updates.</li>
          <li>Commands: /start, /myid for the configured administrator, and /invite for that same administrator.</li>
        </ul>
        <p className="mt-3">Update mode: {status?.mode || "webhook"}. Point Telegram at /api/v1/webhooks/telegram on the API host, with the secret token header.</p>
      </section>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <article className="rounded-3xl border border-line bg-panel p-4"><p className="text-xs uppercase text-ink/50">{label}</p><p className="mt-1 text-lg">{value}</p></article>;
}
