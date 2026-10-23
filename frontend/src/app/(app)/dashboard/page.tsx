"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, MetricCard } from "@/lib/api";
import { metricText } from "@/lib/format";
import { Banner } from "@/components/ui";

export default function DashboardPage() {
  const [cards, setCards] = useState<MetricCard[]>([]);
  const [distribution, setDistribution] = useState<{ status: string; count: number }[]>([]);
  const [jobs, setJobs] = useState<{ id: string; task_name: string; status: string; error?: string }[]>([]);
  const [error, setError] = useState("");
  const [demo, setDemo] = useState(0);

  useEffect(() => {
    api<{ cards: MetricCard[]; distribution: { lifecycle: { status: string; count: number }[] } }>("/api/v1/analytics/overview")
      .then((data) => {
        setCards(data.cards);
        setDistribution(data.distribution.lifecycle);
      })
      .catch((err) => setError(err.message));
    api<{ items: { id: string; task_name: string; status: string; error?: string }[] }>("/api/v1/jobs")
      .then((data) => setJobs(data.items.filter((job) => job.status === "failed").slice(0, 5)))
      .catch(() => setJobs([]));
    api<{ total: number }>("/api/v1/contacts?source=demo_seed&page_size=1")
      .then((data) => setDemo(data.total))
      .catch(() => setDemo(0));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl">Operations</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink/70">Counts come from stored contacts and Telegram events. A missing membership figure means the bot has not reported anything, not that people declined to join.</p>
      </div>
      {demo > 0 && <Banner>Demo records are visible and tagged demo_seed. They are not production contacts.</Banner>}
      {error && <Banner tone="error">{error}</Banner>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <article key={card.key} className="rounded-3xl border border-line bg-panel p-4" title={`${card.definition.numerator}. Source: ${card.definition.event_source}`}>
            <p className="text-xs uppercase tracking-wide text-ink/50">{card.label}</p>
            <p className="mt-2 font-display text-3xl">{metricText(card)}</p>
            {card.note && <p className="mt-2 text-xs leading-5 text-ink/60">{card.note}</p>}
          </article>
        ))}
      </div>
      <section className="rounded-3xl border border-line bg-panel p-4">
        <h2 className="font-display text-2xl">Contact status</h2>
        <div className="h-64">
          {distribution.length === 0 ? <p className="mt-8 text-sm text-ink/60">No contacts stored yet. Import a file to begin.</p> : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={distribution}>
                <XAxis dataKey="status" tick={{ fontSize: 11 }} interval={0} angle={-25} height={70} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#1f6f5b" radius={6} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>
      <section className="rounded-3xl border border-line bg-panel p-4">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-2xl">Failed jobs</h2>
          <Link className="text-sm text-pine" href="/contacts/import">Import contacts</Link>
        </div>
        {jobs.length === 0 ? <p className="mt-3 text-sm text-ink/60">No failed jobs.</p> : (
          <ul className="mt-3 space-y-2 text-sm">
            {jobs.map((job) => <li key={job.id}>{job.task_name}: {job.error || job.status}</li>)}
          </ul>
        )}
      </section>
    </div>
  );
}
