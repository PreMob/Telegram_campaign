"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Banner, Button, Field, controlClass } from "@/components/ui";

type Preview = { id: string; headers: string[]; preview: Record<string, string>[]; row_count_estimate: number };
type Report = { status: string; total_rows: number; inserted_rows: number; invalid_rows: number; duplicate_rows: number; processed_rows: number };

const FIELDS = ["phone", "name", "source", "consent_status", "consent_channel", "consent_purpose"];

export default function ImportPage() {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [region, setRegion] = useState("US");
  const [source, setSource] = useState("import");
  const [busy, setBusy] = useState(false);

  async function onFile(file: File) {
    setError("");
    setReport(null);
    const body = new FormData();
    body.append("file", file);
    try {
      const data = await api<Preview>("/api/v1/imports", { method: "POST", body });
      setPreview(data);
      const next: Record<string, string> = {};
      for (const header of data.headers) {
        const normalized = header.toLowerCase();
        if (normalized.includes("phone")) next.phone = header;
        if (normalized === "name") next.name = header;
        if (normalized === "source") next.source = header;
      }
      setMapping(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    }
  }

  async function commit() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const data = await api<Report>(`/api/v1/imports/${preview.id}/commit`, {
        method: "POST",
        body: JSON.stringify({ mapping, default_region: region, default_source: source, apply_consent_column: false }),
      });
      setReport(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="font-display text-4xl">Import contacts</h1>
        <p className="max-w-2xl text-sm text-ink/70">Files are validated and deduplicated. Nothing in the file is treated as consent unless you explicitly map a consent column and supply a policy version. Imports do not clear suppression.</p>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      <label className="block rounded-3xl border border-dashed border-copper/50 bg-panel p-8 text-center">
        <span className="font-medium">Drop a CSV or XLSX file, or click to browse</span>
        <input className="mt-4 block w-full text-sm" type="file" accept=".csv,.xlsx" aria-label="Contact file" onChange={(event) => { const file = event.target.files?.[0]; if (file) onFile(file); }} />
      </label>
      {preview && (
        <section className="space-y-4 rounded-3xl border border-line bg-panel p-4">
          <p className="text-sm">{preview.row_count_estimate} rows detected in {preview.headers.length} columns. Showing the first rows.</p>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead>{preview.headers.map((header) => <th key={header} className="px-2 py-2">{header}</th>)}</thead>
              <tbody>
                {preview.preview.map((row, index) => (
                  <tr key={index} className="border-t border-line">
                    {preview.headers.map((header) => <td key={header} className="px-2 py-2">{row[header]}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {FIELDS.map((field) => (
              <Field key={field} label={field === "phone" ? "Phone column" : field}>
                <select className={controlClass} value={mapping[field] || ""} onChange={(event) => setMapping({ ...mapping, [field]: event.target.value })}>
                  <option value="">Not mapped</option>
                  {preview.headers.map((header) => <option key={header}>{header}</option>)}
                </select>
              </Field>
            ))}
            <Field label="Default region">
              <input className={controlClass} value={region} onChange={(event) => setRegion(event.target.value)} />
            </Field>
            <Field label="Default source">
              <input className={controlClass} value={source} onChange={(event) => setSource(event.target.value)} />
            </Field>
          </div>
          <Button onClick={commit} disabled={busy || !mapping.phone}>{busy ? "Importing…" : "Start import"}</Button>
        </section>
      )}
      {report && (
        <Banner tone="ok">
          Status {report.status}. Inserted {report.inserted_rows}, duplicates {report.duplicate_rows}, invalid {report.invalid_rows}, of {report.total_rows}.
          {" "}
          <a className="underline" href={`/api/v1/imports/${preview?.id}/errors`}>Download the error report</a>
        </Banner>
      )}
    </div>
  );
}
