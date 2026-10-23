"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Banner, Button, Field, controlClass } from "@/components/ui";

export default function ConsentSettingsPage() {
  const [policy, setPolicy] = useState("1");
  const [retention, setRetention] = useState("");
  const [cap, setCap] = useState("7");
  const [region, setRegion] = useState("US");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ policy_version: string; retention_days: number | null; frequency_cap_days: number; default_region: string }>("/api/v1/settings/consent-policy")
      .then((data) => {
        setPolicy(data.policy_version);
        setRetention(data.retention_days ? String(data.retention_days) : "");
        setCap(String(data.frequency_cap_days));
        setRegion(data.default_region);
      })
      .catch((err) => setError(err.message));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api("/api/v1/settings/consent-policy", {
        method: "PUT",
        body: JSON.stringify({
          policy_version: policy,
          retention_days: retention ? Number(retention) : null,
          frequency_cap_days: Number(cap),
          default_region: region,
        }),
      });
      setMessage("Consent policy saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  return (
    <form onSubmit={save} className="mx-auto max-w-xl space-y-4">
      <h1 className="font-display text-4xl">Consent policy</h1>
      <p className="text-sm text-ink/70">Retention is off until you set a number of days. The daily job anonymizes contacts older than that window. Leave it empty to keep records.</p>
      {error && <Banner tone="error">{error}</Banner>}
      {message && <Banner tone="ok">{message}</Banner>}
      <Field label="Policy version"><input className={controlClass} value={policy} onChange={(event) => setPolicy(event.target.value)} /></Field>
      <Field label="Default phone region"><input className={controlClass} value={region} onChange={(event) => setRegion(event.target.value)} /></Field>
      <Field label="Default frequency cap, days"><input className={controlClass} type="number" min={0} value={cap} onChange={(event) => setCap(event.target.value)} /></Field>
      <Field label="Retention days, optional"><input className={controlClass} type="number" min={1} value={retention} onChange={(event) => setRetention(event.target.value)} /></Field>
      <Button type="submit">Save policy</Button>
    </form>
  );
}
