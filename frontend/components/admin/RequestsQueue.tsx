"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, ApiError } from "@/lib/api";
import { useToast } from "@/components/ui/Toast";

// Access-request review queue (Phase 14 Chunk G). Admin approves (→ Supabase
// invite + provisioned user/workspace) or denies each request. Filter defaults
// to `pending` — the actionable set.

type RequestStatus = "pending" | "approved" | "denied";

type AccessRequest = {
  id: string;
  email: string;
  name: string | null;
  company: string | null;
  reason: string | null;
  status: RequestStatus;
  created_at: string;
  reviewed_at: string | null;
};

const FILTERS: { id: RequestStatus | "all"; label: string }[] = [
  { id: "pending", label: "Pending" },
  { id: "approved", label: "Approved" },
  { id: "denied", label: "Denied" },
  { id: "all", label: "All" },
];

function fmt(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function RequestsQueue() {
  const { notify } = useToast();
  const [filter, setFilter] = useState<RequestStatus | "all">("pending");
  const [rows, setRows] = useState<AccessRequest[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null); // request id mid-action

  const load = useCallback(async () => {
    const q = filter === "all" ? "" : `?status=${filter}`;
    try {
      const data = await apiGet<AccessRequest[]>(`/admin/access-requests${q}`);
      setRows(data);
    } catch (e) {
      notify({ tone: "error", title: "Couldn't load requests", body: String(e) });
      setRows([]);
    }
  }, [filter, notify]);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (id: string, action: "approve" | "deny") => {
    setBusy(id);
    try {
      await apiPost(`/admin/access-requests/${id}/${action}`);
      notify({
        tone: action === "approve" ? "success" : "info",
        title: action === "approve" ? "Invite sent" : "Request denied",
      });
      load();
    } catch (e) {
      const body = e instanceof ApiError ? e.body : String(e);
      notify({ tone: "error", title: `Could not ${action}`, body });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <nav className="mb-5 flex flex-wrap gap-1">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => {
              setRows(null); // show the loading state while the new filter fetches
              setFilter(f.id);
            }}
            className={
              "rounded-full px-3 py-1 text-xs transition-colors " +
              (f.id === filter
                ? "bg-surface-2 text-ink-hi"
                : "text-ink-lo hover:text-ink-mid")
            }
          >
            {f.label}
          </button>
        ))}
      </nav>

      {rows === null ? (
        <p className="text-sm text-ink-lo">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-4 py-10 text-center text-sm text-ink-lo">
          No {filter === "all" ? "" : filter} requests.
        </p>
      ) : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li
              key={r.id}
              className="rounded-md border border-border bg-surface-1/40 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink-hi">
                    {r.email}
                  </p>
                  <p className="mt-0.5 text-xs text-ink-lo">
                    {[r.name, r.company].filter(Boolean).join(" · ") || "—"}
                    <span className="mx-1.5">·</span>
                    {fmt(r.created_at)}
                  </p>
                  {r.reason && (
                    <p className="mt-2 max-w-prose text-xs text-ink-mid">
                      {r.reason}
                    </p>
                  )}
                </div>

                {r.status === "pending" ? (
                  <div className="flex shrink-0 gap-2">
                    <button
                      onClick={() => act(r.id, "approve")}
                      disabled={busy === r.id}
                      className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
                    >
                      {busy === r.id ? "…" : "Approve"}
                    </button>
                    <button
                      onClick={() => act(r.id, "deny")}
                      disabled={busy === r.id}
                      className="rounded-md border border-border px-3 py-1.5 text-xs text-ink-mid transition-colors hover:text-ink-hi disabled:opacity-50"
                    >
                      Deny
                    </button>
                  </div>
                ) : (
                  <span
                    className={
                      "shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium " +
                      (r.status === "approved"
                        ? "bg-status-published/10 text-status-published"
                        : "bg-status-failed/10 text-status-failed")
                    }
                  >
                    {r.status}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
