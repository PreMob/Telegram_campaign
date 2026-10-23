"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { Banner, Button, controlClass } from "@/components/ui";

export default function AnalyticsPage() {
  const [funnel, setFunnel] = useState<{ audience: { label: string; count: number | null }[]; invitation: { label: string; count: number | null }[] } | null>(null);
  const [series, setSeries] = useState<{ date: string; joins: number; departures: number; attributed_joins: number }[]>([]);
  const [campaigns, setCampaigns] = useState<{ name: string; invitations_attempted: number; attributed_joins: number; conversion_rate: number | null; conversion_state: string }[]>([]);
  const [retention, setRetention] = useState<{ cohorts: { week: string; joined: number; retained: number; retention_rate: number | null }[]; note: string; completeness: string } | null>(null);
  const [providers, setProviders] = useState<{ provider: string; statuses: Record<string, number> }[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [error, setError] = useState("");

  async function load() {
    const params = new URLSearchParams();
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    const query = params.toString() ? `?${params.toString()}` : "";
    const [funnelData, membership, comparison, retentionData, overview] = await Promise.all([
      api<{ audience: { label: string; count: number | null }[]; invitation: { label: string; count: number | null }[] }>(`/api/v1/analytics/funnel${query}`),
      api<{ daily: { date: string; joins: number; departures: number; attributed_joins: number }[] }>(`/api/v1/analytics/membership${query}`),
      api<{ campaigns: { name: string; invitations_attempted: number; attributed_joins: number; conversion_rate: number | null; conversion_state: string }[] }>(`/api/v1/analytics/campaigns${query}`),
      api<{ cohorts: { week: string; joined: number; retained: number; retention_rate: number | null }[]; note: string; completeness: string }>("/api/v1/analytics/retention"),
      api<{ providers: { providers: { provider: string; statuses: Record<string, number> }[] } }>(`/api/v1/analytics/overview${query}`),
    ]);
    setFunnel(funnelData);
    setSeries(membership.daily);
    setCampaigns(comparison.campaigns);
    setRetention(retentionData);
    setProviders(overview.providers.providers);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="font-display text-4xl">Analytics</h1>
        <p className="max-w-2xl text-sm text-ink/70">Membership charts count recorded events. They are not a census of everyone who may have joined before the bot was an administrator.</p>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); load().catch((err) => setError(err.message)); }}>
        <label className="text-sm">From<input type="date" className={`${controlClass} mt-1`} value={from} onChange={(event) => setFrom(event.target.value)} /></label>
        <label className="text-sm">To<input type="date" className={`${controlClass} mt-1`} value={to} onChange={(event) => setTo(event.target.value)} /></label>
        <Button type="submit">Apply</Button>
      </form>
      <div className="grid gap-4 lg:grid-cols-2">
        <Chart title="Audience eligibility" data={funnel?.audience || []} />
        <Chart title="Invitation to join" data={funnel?.invitation || []} />
      </div>
      <section className="rounded-3xl border border-line bg-panel p-4">
        <h2 className="font-display text-2xl">Joins and departures</h2>
        <div className="h-72">
          {series.length === 0 ? <p className="mt-6 text-sm text-ink/60">No events in this window.</p> : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series}>
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Line type="monotone" dataKey="attributed_joins" stroke="#1f6f5b" dot={false} />
                <Line type="monotone" dataKey="departures" stroke="#9a5b32" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>
      <section className="rounded-3xl border border-line bg-panel p-4">
        <h2 className="font-display text-2xl">Campaign comparison</h2>
        <table className="mt-3 min-w-full text-left text-sm">
          <thead><tr><th className="py-2">Campaign</th><th>Attempted</th><th>Attributed joins</th><th>Conversion</th></tr></thead>
          <tbody>
            {campaigns.length === 0 && <tr><td colSpan={4} className="py-4 text-ink/60">No campaigns.</td></tr>}
            {campaigns.map((campaign) => (
              <tr key={campaign.name} className="border-t border-line">
                <td className="py-2">{campaign.name}</td>
                <td>{campaign.invitations_attempted}</td>
                <td>{campaign.attributed_joins}</td>
                <td>{campaign.conversion_state === "zero_denominator" ? "Undefined" : `${campaign.conversion_rate}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-3xl border border-line bg-panel p-4">
          <h2 className="font-display text-2xl">Provider results</h2>
          {providers.length === 0 ? <p className="mt-3 text-sm text-ink/60">No provider attempts yet.</p> : providers.map((provider) => (
            <p key={provider.provider} className="mt-2 text-sm">{provider.provider}: {Object.entries(provider.statuses).map(([status, count]) => `${status} ${count}`).join(", ")}</p>
          ))}
        </div>
        <div className="rounded-3xl border border-line bg-panel p-4">
          <h2 className="font-display text-2xl">Retention cohorts</h2>
          <p className="mt-2 text-xs text-ink/60">{retention?.note}</p>
          <ul className="mt-3 space-y-1 text-sm">
            {(retention?.cohorts || []).map((cohort) => <li key={cohort.week}>{cohort.week}: {cohort.retained}/{cohort.joined} still without a recorded departure</li>)}
            {retention?.completeness === "missing" && <li>No cohort can be calculated.</li>}
          </ul>
        </div>
      </section>
    </div>
  );
}

function Chart({ title, data }: { title: string; data: { label: string; count: number | null }[] }) {
  const rows = data.map((item) => ({ ...item, count: item.count ?? 0 }));
  return (
    <section className="rounded-3xl border border-line bg-panel p-4">
      <h2 className="font-display text-2xl">{title}</h2>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows}>
            <XAxis dataKey="label" tick={{ fontSize: 11 }} interval={0} angle={-20} height={70} />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="count" fill="#1f6f5b" radius={6} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
