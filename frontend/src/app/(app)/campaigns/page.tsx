"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Banner, StatusPill } from "@/components/ui";

type Campaign = {
  id: string;
  name: string;
  status: string;
  outreach_channel: string;
  objective: string;
  is_demo: boolean;
  invite_link: string | null;
};

export default function CampaignsPage() {
  const [items, setItems] = useState<Campaign[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ items: Campaign[] }>("/api/v1/campaigns")
      .then((data) => setItems(data.items))
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-4xl">Campaigns</h1>
          <p className="text-sm text-ink/70">Configuration stays separate from delivery. Invite campaigns publish a Telegram link. They do not message the phone list.</p>
        </div>
        <Link href="/campaigns/new" className="rounded-full bg-pine px-4 py-2 text-sm font-semibold text-white">New campaign</Link>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      <div className="overflow-x-auto rounded-3xl border border-line bg-panel">
        <table className="min-w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-ink/50">
            <tr><th className="px-4 py-3">Name</th><th className="px-4 py-3">Channel</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Invite</th></tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={4} className="px-4 py-8 text-ink/60">No campaigns yet.</td></tr>}
            {items.map((campaign) => (
              <tr key={campaign.id} className="border-t border-line">
                <td className="px-4 py-3"><Link className="font-medium text-pine" href={`/campaigns/${campaign.id}`}>{campaign.name}{campaign.is_demo ? " · demo" : ""}</Link><p className="text-xs text-ink/50">{campaign.objective}</p></td>
                <td className="px-4 py-3">{campaign.outreach_channel}</td>
                <td className="px-4 py-3"><StatusPill value={campaign.status} /></td>
                <td className="px-4 py-3">{campaign.invite_link ? "Link issued by Telegram" : "No link yet"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
