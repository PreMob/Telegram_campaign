"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Banner, Button, Field, controlClass } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      await api("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      });
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-2">
      <section className="hidden bg-ink px-12 py-16 text-paper lg:block">
        <p className="text-xs uppercase tracking-[0.18em] text-paper/50">Telegram Audience Growth</p>
        <h1 className="mt-6 max-w-md font-display text-5xl leading-tight">Invite people who choose to join. Count only what Telegram confirms.</h1>
        <p className="mt-6 max-w-md text-paper/75">The Bot API cannot discover accounts from a phone list or add those people to a channel. This desk tracks consent, invite links, and membership events instead.</p>
      </section>
      <section className="flex items-center justify-center px-6 py-16">
        <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4">
          <h2 className="font-display text-4xl">Sign in</h2>
          {error && <Banner tone="error">{error}</Banner>}
          <Field label="Email">
            <input className={controlClass} name="email" type="email" autoComplete="username" required />
          </Field>
          <Field label="Password">
            <input className={controlClass} name="password" type="password" autoComplete="current-password" required />
          </Field>
          <Button type="submit" disabled={pending}>{pending ? "Signing in…" : "Sign in"}</Button>
        </form>
      </section>
    </main>
  );
}
