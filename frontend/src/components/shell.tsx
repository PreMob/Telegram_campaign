"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, User } from "@/lib/api";
import { roleLabel } from "@/lib/format";

const NAV = [
  ["/dashboard", "Dashboard"],
  ["/contacts", "Contacts"],
  ["/contacts/import", "Import"],
  ["/campaigns", "Campaigns"],
  ["/analytics", "Analytics"],
  ["/integrations/telegram", "Telegram"],
  ["/settings/consent", "Consent"],
  ["/settings/users", "Users"],
  ["/settings/audit-logs", "Audit log"],
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api<User>("/api/v1/auth/me")
      .then(setUser)
      .catch(() => router.replace("/login"));
  }, [router]);

  async function logout() {
    try {
      await api("/api/v1/auth/logout", { method: "POST" });
      router.replace("/login");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Logout failed");
    }
  }

  const items = NAV.filter(([href]) => href !== "/settings/users" || user?.role === "super_admin");

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[240px_1fr]">
      <aside className={`${open ? "block" : "hidden"} border-b border-white/10 bg-ink text-paper lg:block`}>
        <div className="px-5 py-6">
          <p className="font-display text-2xl leading-none">Harbor</p>
          <p className="mt-1 text-xs uppercase tracking-[0.16em] text-paper/60">Audience growth</p>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-4 lg:block lg:space-y-1 lg:px-3">
          {items.map(([href, label]) => {
            const active = pathname === href || (href !== "/contacts" && pathname.startsWith(href));
            return (
              <Link
                key={href}
                href={href}
                onClick={() => setOpen(false)}
                className={`block whitespace-nowrap rounded-xl px-3 py-2 text-sm ${active ? "bg-white/10 text-white" : "text-paper/75 hover:bg-white/5"}`}
              >
                {label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div>
        <header className="flex items-center justify-between border-b border-line bg-panel px-4 py-3 lg:px-8">
          <button className="rounded-full border border-line px-3 py-1 text-sm lg:hidden" onClick={() => setOpen((value) => !value)}>
            Menu
          </button>
          <p className="hidden text-sm text-ink/60 lg:block">Voluntary joins, tracked invites, and consented outreach only.</p>
          <div className="flex items-center gap-3 text-sm">
            {user && <span className="text-ink/70">{user.full_name || user.email} · {roleLabel(user.role)}</span>}
            <button className="rounded-full border border-line px-3 py-1" onClick={logout}>Log out</button>
          </div>
        </header>
        <main className="px-4 py-6 lg:px-8">
          {error && <p className="mb-4 text-sm text-clay">{error}</p>}
          {user ? children : <p className="text-sm text-ink/60">Checking your session…</p>}
        </main>
      </div>
    </div>
  );
}
