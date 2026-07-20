"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch, apiDelete, ApiError } from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import { useMe, type Role } from "@/lib/useMe";

// User management (Phase 14 Chunk G). Change a user's role or hard-revoke them.
// Backend enforces the last-admin + self guards (409) — we surface those as
// toasts and also disable the obvious self-revoke up front.

type UserRow = {
  id: string;
  email: string;
  role: Role;
  workspace_id: string;
  created_at: string;
};

const ROLES: Role[] = ["admin", "editor", "viewer"];

function fmt(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function UsersTable() {
  const { notify } = useToast();
  const { me } = useMe();
  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<UserRow[]>("/admin/users");
      setRows(data);
    } catch (e) {
      notify({ tone: "error", title: "Couldn't load users", body: String(e) });
      setRows([]);
    }
  }, [notify]);

  useEffect(() => {
    load();
  }, [load]);

  const changeRole = async (u: UserRow, role: Role) => {
    if (role === u.role) return;
    setBusy(u.id);
    try {
      await apiPatch(`/admin/users/${u.id}`, { role });
      notify({ tone: "success", title: `${u.email} is now ${role}` });
      load();
    } catch (e) {
      const body = e instanceof ApiError ? e.body : String(e);
      notify({ tone: "error", title: "Role change failed", body });
    } finally {
      setBusy(null);
    }
  };

  const revoke = async (u: UserRow) => {
    if (
      !window.confirm(
        `Revoke ${u.email}? This deletes their workspace, drafts, and connected accounts. This cannot be undone.`,
      )
    )
      return;
    setBusy(u.id);
    try {
      await apiDelete(`/admin/users/${u.id}`);
      notify({ tone: "info", title: `Revoked ${u.email}` });
      load();
    } catch (e) {
      const body = e instanceof ApiError ? e.body : String(e);
      notify({ tone: "error", title: "Revoke failed", body });
    } finally {
      setBusy(null);
    }
  };

  if (rows === null) return <p className="text-sm text-ink-lo">Loading…</p>;

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[34rem] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-ink-lo">
            <th className="py-2 pr-4 font-medium">User</th>
            <th className="py-2 pr-4 font-medium">Role</th>
            <th className="py-2 pr-4 font-medium">Joined</th>
            <th className="py-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => {
            const isSelf = me?.id === u.id;
            return (
              <tr key={u.id} className="border-b border-border/60">
                <td className="py-3 pr-4">
                  <span className="text-ink-hi">{u.email}</span>
                  {isSelf && (
                    <span className="ml-2 text-[11px] text-ink-lo">(you)</span>
                  )}
                </td>
                <td className="py-3 pr-4">
                  <select
                    value={u.role}
                    disabled={busy === u.id}
                    onChange={(e) => changeRole(u, e.target.value as Role)}
                    className="rounded-md border border-border bg-surface-1 px-2 py-1 text-xs text-ink-mid outline-none focus:border-accent disabled:opacity-50"
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="py-3 pr-4 text-xs text-ink-lo">
                  {fmt(u.created_at)}
                </td>
                <td className="py-3 text-right">
                  <button
                    onClick={() => revoke(u)}
                    disabled={isSelf || busy === u.id}
                    title={isSelf ? "You can't revoke yourself" : "Revoke access"}
                    className="text-xs text-status-failed transition-opacity hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-30"
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
