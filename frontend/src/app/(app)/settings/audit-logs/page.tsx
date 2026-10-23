"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Banner, Button } from "@/components/ui";

type Row = { id: string; at: string; actor_id: string | null; action: string; entity_type: string; entity_id: string | null; ip_address: string | null };

export default function AuditPage() {
  const [items, setItems] = useState<Row[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ items: Row[]; total: number }>(`/api/v1/audit-logs?page=${page}&page_size=50`)
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
      })
      .catch((err) => setError(err.message));
  }, [page]);

  return (
    <div className="space-y-4">
      <h1 className="font-display text-4xl">Audit log</h1>
      {error && <Banner tone="error">{error}</Banner>}
      <div className="overflow-x-auto rounded-3xl border border-line bg-panel">
        <table className="min-w-full text-left text-sm">
          <thead><tr><th className="px-4 py-3">When</th><th>Action</th><th>Entity</th><th>IP</th></tr></thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={4} className="px-4 py-8 text-ink/60">No audit events yet.</td></tr>}
            {items.map((row) => (
              <tr key={row.id} className="border-t border-line">
                <td className="px-4 py-3">{row.at}</td>
                <td>{row.action}</td>
                <td>{row.entity_type} {row.entity_id || ""}</td>
                <td>{row.ip_address || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex justify-between text-sm">
        <Button tone="ghost" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>Previous</Button>
        <span>{total} events</span>
        <Button tone="ghost" disabled={page * 50 >= total} onClick={() => setPage((value) => value + 1)}>Next</Button>
      </div>
    </div>
  );
}
