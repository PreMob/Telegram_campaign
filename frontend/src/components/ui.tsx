"use client";

import { ReactNode } from "react";

export function Button({
  children,
  tone = "primary",
  type = "button",
  disabled,
  onClick,
}: {
  children: ReactNode;
  tone?: "primary" | "ghost" | "danger";
  type?: "button" | "submit";
  disabled?: boolean;
  onClick?: () => void;
}) {
  const tones = {
    primary: "bg-pine text-white hover:bg-[#18584a]",
    ghost: "bg-white border border-line text-ink hover:bg-paper",
    danger: "bg-clay text-white hover:bg-[#732f2f]",
  };
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`rounded-full px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${tones[tone]}`}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-ink/80">{label}</span>
      {children}
    </label>
  );
}

export const controlClass =
  "w-full rounded-xl border border-line bg-white px-3 py-2 text-sm outline-none";

export function Banner({ tone = "info", children }: { tone?: "info" | "error" | "ok"; children: ReactNode }) {
  const tones = {
    info: "border-copper/30 bg-[#f8efe6] text-ink",
    error: "border-clay/30 bg-[#f8ecec] text-clay",
    ok: "border-moss/30 bg-[#eef5f0] text-moss",
  };
  return <div className={`rounded-2xl border px-4 py-3 text-sm ${tones[tone]}`}>{children}</div>;
}

export function Modal({
  title,
  body,
  confirmLabel,
  danger,
  onCancel,
  onConfirm,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  danger?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-30 flex items-end justify-center bg-ink/40 p-4 sm:items-center" role="presentation">
      <div role="dialog" aria-modal="true" aria-labelledby="dialog-title" className="w-full max-w-md rounded-3xl bg-panel p-6 shadow-xl">
        <h2 id="dialog-title" className="font-display text-2xl">{title}</h2>
        <p className="mt-2 text-sm leading-6 text-ink/80">{body}</p>
        <div className="mt-6 flex justify-end gap-2">
          <Button tone="ghost" onClick={onCancel}>Cancel</Button>
          <Button tone={danger ? "danger" : "primary"} onClick={onConfirm}>{confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
}

export function StatusPill({ value }: { value: string }) {
  const known = value.toLowerCase();
  const tone = known.includes("fail") || known.includes("withdraw") || known.includes("suppress")
    ? "bg-[#f8ecec] text-clay"
    : known.includes("join") || known.includes("grant") || known.includes("eligible") || known.includes("running") || known.includes("approved")
      ? "bg-[#e7f3ee] text-moss"
      : "bg-paper text-ink/80";
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${tone}`}>{value.replaceAll("_", " ")}</span>;
}
