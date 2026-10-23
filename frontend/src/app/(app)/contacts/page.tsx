"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Banner, Button, StatusPill, controlClass } from "@/components/ui";

type Contact = {
  id: string;
  name: string | null;
  phone_masked: string;
  source: string;
  consent_status: string;
  membership_status: string;
  lifecycle_status: string;
  is_demo: boolean;
  suppression_status: boolean;
};

export default function ContactsPage() {
  const [items, setItems] = useState<Contact[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [consent, setConsent] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load(nextPage = page, query = q, consentStatus = consent) {
    const params = new URLSearchParams({ page: String(nextPage), page_size: "25", sort: "created_at", direction: "desc" });
    if (query) params.set("q", query);
    if (consentStatus) params.set("consent_status", consentStatus);
    const data = await api<{ items: Contact[]; total: number }>(`/api/v1/contacts?${params.toString()}`);
    setItems(data.items);
    setTotal(data.total);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [page]);

  async function exportContacts() {
    setMessage("");
    const response = await fetch("/api/v1/contacts/export", { credentials: "include" });
    if (!response.ok) {
      const body = await response.json();
      setError(body.error?.message || "Export failed");
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "contacts.csv";
    link.click();
    URL.revokeObjectURL(url);
    setMessage("Export downloaded. The action was written to the audit log.");
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-4xl">Contacts</h1>
          <p className="text-sm text-ink/70">{total} stored contacts. A phone number is not a Telegram account.</p>
        </div>
        <div className="flex gap-2">
          <Link href="/contacts/import" className="rounded-full bg-pine px-4 py-2 text-sm font-semibold text-white">Import</Link>
          <Button tone="ghost" onClick={exportContacts}>Export</Button>
        </div>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      {message && <Banner tone="ok">{message}</Banner>}
      <form className="flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); setPage(1); load(1).catch((err) => setError(err.message)); }}>
        <input className={`${controlClass} max-w-xs`} placeholder="Search name or last four digits" value={q} onChange={(event) => setQ(event.target.value)} aria-label="Search contacts" />
        <select className={`${controlClass} max-w-[180px]`} value={consent} onChange={(event) => setConsent(event.target.value)} aria-label="Consent status">
          <option value="">Any consent</option>
          <option value="pending">Pending</option>
          <option value="granted">Granted</option>
          <option value="withdrawn">Withdrawn</option>
          <option value="expired">Expired</option>
        </select>
        <Button type="submit">Filter</Button>
      </form>
      <div className="overflow-x-auto rounded-3xl border border-line bg-panel">
        <table className="min-w-full text-left text-sm">
          <caption className="sr-only">Contacts</caption>
          <thead className="text-xs uppercase tracking-wide text-ink/50">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Phone</th>
              <th className="px-4 py-3">Source</th>
              <th className="px-4 py-3">Consent</th>
              <th className="px-4 py-3">Membership</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td className="px-4 py-8 text-ink/60" colSpan={6}>No contacts match this view.</td></tr>}
            {items.map((contact) => (
              <tr key={contact.id} className="border-t border-line">
                <td className="px-4 py-3"><Link className="font-medium text-pine" href={`/contacts/${contact.id}`}>{contact.name || "Unnamed"}{contact.is_demo ? " · demo" : ""}</Link></td>
                <td className="px-4 py-3">{contact.phone_masked}</td>
                <td className="px-4 py-3">{contact.source}</td>
                <td className="px-4 py-3"><StatusPill value={contact.consent_status} /></td>
                <td className="px-4 py-3"><StatusPill value={contact.membership_status} /></td>
                <td className="px-4 py-3"><StatusPill value={contact.lifecycle_status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between text-sm">
        <Button tone="ghost" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>Previous</Button>
        <span>Page {page}</span>
        <Button tone="ghost" disabled={page * 25 >= total} onClick={() => setPage((value) => value + 1)}>Next</Button>
      </div>
    </div>
  );
}
