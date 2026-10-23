"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { Banner, Button, Modal, StatusPill } from "@/components/ui";

type Campaign = {
  id: string;
  name: string;
  description: string;
  objective: string;
  status: string;
  outreach_channel: string;
  message_template: string;
  invite_link: string | null;
  is_demo: boolean;
  frequency_cap_days: number;
  events: { at: string; type: string; details: Record<string, unknown> }[];
  previews: { at: string; eligible: number; excluded: number; suppressed: number; unknown_consent: number; unknown_membership: number }[];
};

export default function CampaignDetailPage() {
  const params = useParams<{ id: string }>();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState<null | "launch" | "cancel" | "pause">(null);

  async function load() {
    setCampaign(await api<Campaign>(`/api/v1/campaigns/${params.id}`));
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [params.id]);

  async function run(path: string, body?: unknown) {
    setError("");
    await api(`/api/v1/campaigns/${params.id}/${path}`, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
    await load();
    setConfirm(null);
  }

  if (!campaign) return error ? <Banner tone="error">{error}</Banner> : <p>Loading campaign…</p>;
  const preview = campaign.previews?.[0];

  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs uppercase tracking-wide text-ink/50">{campaign.is_demo ? "Demo campaign" : campaign.outreach_channel}</p>
        <h1 className="font-display text-4xl">{campaign.name}</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink/75">{campaign.description || campaign.objective}</p>
        <div className="mt-3"><StatusPill value={campaign.status} /></div>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      {campaign.invite_link && <Banner tone="ok">Telegram issued this invite link: {campaign.invite_link}</Banner>}
      <section className="rounded-3xl border border-line bg-panel p-4">
        <h2 className="font-display text-2xl">Message preview</h2>
        <pre className="mt-3 whitespace-pre-wrap text-sm">{campaign.message_template || "No template."}</pre>
        <p className="mt-2 text-xs text-ink/50">Frequency cap {campaign.frequency_cap_days} days. Placeholders are limited to name and invite link.</p>
      </section>
      {preview && (
        <section className="grid gap-3 sm:grid-cols-5">
          {[
            ["Eligible", preview.eligible],
            ["Excluded", preview.excluded],
            ["Suppressed", preview.suppressed],
            ["Unknown consent", preview.unknown_consent],
            ["Unknown membership", preview.unknown_membership],
          ].map(([label, value]) => (
            <article key={String(label)} className="rounded-3xl border border-line bg-panel p-4">
              <p className="text-xs uppercase text-ink/50">{label}</p>
              <p className="font-display text-3xl">{value}</p>
            </article>
          ))}
        </section>
      )}
      <div className="flex flex-wrap gap-2">
        <Button tone="ghost" onClick={() => run("preview").catch((err) => setError(err.message))}>Preview audience</Button>
        {campaign.status === "draft" && <Button onClick={() => api(`/api/v1/campaigns/${params.id}`, { method: "PATCH", body: JSON.stringify({ status: "pending_approval" }) }).then(load).catch((err) => setError(err.message))}>Submit for approval</Button>}
        {campaign.status === "pending_approval" && <Button onClick={() => run("approve").catch((err) => setError(err.message))}>Approve</Button>}
        {campaign.status === "approved" && <Button onClick={() => setConfirm("launch")}>Launch</Button>}
        {campaign.status === "running" && <Button tone="ghost" onClick={() => setConfirm("pause")}>Pause</Button>}
        {campaign.status === "paused" && <Button onClick={() => run("resume").catch((err) => setError(err.message))}>Resume</Button>}
        {!["completed", "cancelled"].includes(campaign.status) && <Button tone="danger" onClick={() => setConfirm("cancel")}>Cancel</Button>}
        <Button tone="ghost" onClick={() => run("duplicate").then(() => load()).catch((err) => setError(err.message))}>Duplicate</Button>
      </div>
      <section className="rounded-3xl border border-line bg-panel p-4">
        <h2 className="font-display text-2xl">Activity</h2>
        <ul className="mt-3 space-y-2 text-sm">
          {(campaign.events || []).length === 0 && <li>No activity yet.</li>}
          {(campaign.events || []).map((event) => <li key={event.at + event.type}>{event.at} · {event.type}</li>)}
        </ul>
      </section>
      {confirm && (
        <Modal
          title={confirm === "launch" ? "Launch this campaign?" : confirm === "pause" ? "Pause sending?" : "Cancel this campaign?"}
          body={confirm === "launch" ? "Eligibility is checked again immediately before anything is sent. Confirm only if the audience and template are correct." : confirm === "pause" ? "Queued messages stay queued until you resume or cancel." : "Queued messages will be cancelled. Messages already accepted by a provider are not recalled."}
          confirmLabel={confirm === "launch" ? "Launch" : confirm === "pause" ? "Pause" : "Cancel campaign"}
          danger={confirm === "cancel"}
          onCancel={() => setConfirm(null)}
          onConfirm={() => run(confirm === "launch" ? "launch" : confirm, confirm === "launch" ? { confirm: true, dry_run: false } : undefined).catch((err) => { setError(err.message); setConfirm(null); })}
        />
      )}
    </div>
  );
}
