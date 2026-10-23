"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, User } from "@/lib/api";
import { Banner, Button, Field, controlClass } from "@/components/ui";

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    const data = await api<{ items: User[] }>("/api/v1/users");
    setUsers(data.items);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      await api("/api/v1/users", {
        method: "POST",
        body: JSON.stringify({
          email: form.get("email"),
          password: form.get("password"),
          full_name: form.get("full_name"),
          role: form.get("role"),
        }),
      });
      setMessage("User created.");
      event.currentTarget.reset();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the user");
    }
  }

  return (
    <div className="space-y-5">
      <h1 className="font-display text-4xl">Users</h1>
      {error && <Banner tone="error">{error}</Banner>}
      {message && <Banner tone="ok">{message}</Banner>}
      <div className="overflow-x-auto rounded-3xl border border-line bg-panel">
        <table className="min-w-full text-left text-sm">
          <thead><tr><th className="px-4 py-3">Name</th><th>Email</th><th>Role</th><th>Active</th></tr></thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id} className="border-t border-line">
                <td className="px-4 py-3">{user.full_name || "—"}</td>
                <td>{user.email}</td>
                <td>{user.role}</td>
                <td>{user.is_active ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form onSubmit={create} className="grid max-w-xl gap-3 rounded-3xl border border-line bg-panel p-4">
        <h2 className="font-display text-2xl">Add an operator</h2>
        <Field label="Name"><input name="full_name" className={controlClass} /></Field>
        <Field label="Email"><input name="email" type="email" className={controlClass} required /></Field>
        <Field label="Password"><input name="password" type="password" minLength={12} className={controlClass} required /></Field>
        <Field label="Role">
          <select name="role" className={controlClass} defaultValue="campaign_manager">
            <option value="super_admin">Super admin</option>
            <option value="campaign_manager">Campaign manager</option>
            <option value="analyst">Analyst</option>
            <option value="read_only">Read only</option>
          </select>
        </Field>
        <Button type="submit">Create user</Button>
      </form>
    </div>
  );
}
