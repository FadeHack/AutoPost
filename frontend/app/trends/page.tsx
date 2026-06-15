"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";

type TrendSource = "rss" | "hackernews" | "reddit";
type StatusFilter = "unconsumed" | "consumed" | "all";

type Trend = {
  id: string;
  source: TrendSource;
  source_id: string;
  title: string;
  url: string;
  summary: string | null;
  score: number | null;
  fetched_at: string;
  consumed_at: string | null;
};

type RefreshResult = {
  fetched: number;
  deduped: number;
  inserted: number;
  per_source: Record<string, number>;
};

const SOURCE_COLORS: Record<TrendSource, string> = {
  rss: "border-blue-700 text-blue-300 bg-blue-950/30",
  hackernews: "border-orange-700 text-orange-300 bg-orange-950/30",
  reddit: "border-red-700 text-red-300 bg-red-950/30",
};

function TrendsPage() {
  const router = useRouter();
  const { session, loading: authLoading, signOut } = useAuth();

  const [trends, setTrends] = useState<Trend[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("unconsumed");
  const [sourceFilter, setSourceFilter] = useState<TrendSource | "all">("all");
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);

  useEffect(() => {
    if (!authLoading && !session) router.replace("/login");
  }, [authLoading, session, router]);

  const fetchTrends = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        status: statusFilter,
        limit: "100",
      });
      if (sourceFilter !== "all") params.set("source", sourceFilter);
      const data = await apiGet<Trend[]>(`/trends?${params.toString()}`);
      setTrends(data);
      setSelected(new Set());
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [session, statusFilter, sourceFilter]);

  useEffect(() => {
    fetchTrends();
  }, [fetchTrends]);

  const refresh = async () => {
    setRefreshing(true);
    setError("");
    setFlash("");
    try {
      const r = await apiPost<RefreshResult>("/trends/refresh");
      setFlash(
        `Fetched ${r.fetched}, deduped ${r.deduped}, inserted ${r.inserted} (${Object.entries(
          r.per_source
        )
          .map(([k, v]) => `${k}: ${v}`)
          .join(", ")})`
      );
      await fetchTrends();
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setRefreshing(false);
    }
  };

  const toggleConsumed = async (trend: Trend) => {
    const becomingConsumed = trend.consumed_at === null;
    // Optimistic update
    setTrends((prev) =>
      prev.map((t) =>
        t.id === trend.id
          ? {
              ...t,
              consumed_at: becomingConsumed ? new Date().toISOString() : null,
            }
          : t
      )
    );
    try {
      await apiPatch<Trend>(`/trends/${trend.id}`, {
        consumed: becomingConsumed,
      });
      // Drop from view if it no longer matches the active filter
      if (statusFilter === "unconsumed" && becomingConsumed) {
        setTrends((prev) => prev.filter((t) => t.id !== trend.id));
      } else if (statusFilter === "consumed" && !becomingConsumed) {
        setTrends((prev) => prev.filter((t) => t.id !== trend.id));
      }
    } catch (e) {
      // Revert
      setTrends((prev) =>
        prev.map((t) =>
          t.id === trend.id ? { ...t, consumed_at: trend.consumed_at } : t
        )
      );
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    }
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelected((prev) =>
      prev.size === trends.length ? new Set() : new Set(trends.map((t) => t.id))
    );
  };

  const deleteOne = async (trend: Trend) => {
    if (!confirm(`Delete trend "${trend.title.slice(0, 60)}"?`)) return;
    setError("");
    const snapshot = trends;
    setTrends((prev) => prev.filter((t) => t.id !== trend.id));
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(trend.id);
      return next;
    });
    try {
      await apiDelete(`/trends/${trend.id}`);
    } catch (e) {
      setTrends(snapshot);
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    }
  };

  const bulkDelete = async () => {
    if (selected.size === 0) return;
    if (!confirm(`Delete ${selected.size} selected trend(s)?`)) return;
    setBulkDeleting(true);
    setError("");
    setFlash("");
    const ids = Array.from(selected);
    try {
      const r = await apiPost<{ deleted: number }>("/trends/bulk-delete", {
        ids,
      });
      setFlash(`Deleted ${r.deleted} trend${r.deleted === 1 ? "" : "s"}.`);
      setTrends((prev) => prev.filter((t) => !selected.has(t.id)));
      setSelected(new Set());
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setBulkDeleting(false);
    }
  };

  if (authLoading || !session) {
    return <div className="flex-1 p-8 text-zinc-500">Loading…</div>;
  }

  return (
    <main className="flex-1 px-6 py-10">
      <header className="flex justify-between items-center mb-8 max-w-5xl mx-auto">
        <div className="flex items-center gap-6">
          <Link
            href="/"
            className="text-sm text-zinc-400 hover:text-white"
          >
            ← Dashboard
          </Link>
          <h1 className="text-2xl font-bold tracking-tight">Trends</h1>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span className="text-zinc-500">{session.user.email}</span>
          <button
            onClick={signOut}
            className="text-zinc-400 hover:text-white"
          >
            Sign out
          </button>
        </div>
      </header>

      <div className="max-w-5xl mx-auto space-y-6">
        <section className="flex flex-wrap items-center gap-3 text-sm">
          <select
            value={statusFilter}
            onChange={(e) =>
              setStatusFilter(e.target.value as StatusFilter)
            }
            className="rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
          >
            <option value="unconsumed">Unconsumed</option>
            <option value="consumed">Consumed</option>
            <option value="all">All</option>
          </select>
          <select
            value={sourceFilter}
            onChange={(e) =>
              setSourceFilter(e.target.value as TrendSource | "all")
            }
            className="rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
          >
            <option value="all">All sources</option>
            <option value="rss">RSS</option>
            <option value="hackernews">HackerNews</option>
            <option value="reddit">Reddit</option>
          </select>
          <span className="text-zinc-500">
            {loading ? "Loading…" : `${trends.length} item${trends.length === 1 ? "" : "s"}`}
          </span>
          <div className="flex-1" />
          {selected.size > 0 && (
            <button
              onClick={bulkDelete}
              disabled={bulkDeleting}
              className="rounded border border-red-700 bg-red-950/40 text-red-200 px-3 py-2 text-sm hover:bg-red-900/50 disabled:opacity-50"
            >
              {bulkDeleting ? "Deleting…" : `Delete ${selected.size} selected`}
            </button>
          )}
          <button
            onClick={refresh}
            disabled={refreshing}
            className="rounded bg-white text-black font-medium px-4 py-2 text-sm hover:bg-zinc-200 disabled:opacity-50"
          >
            {refreshing ? "Refreshing…" : "Refresh now"}
          </button>
        </section>

        {trends.length > 0 && (
          <div className="flex items-center gap-2 text-xs text-zinc-500 px-1">
            <input
              type="checkbox"
              checked={selected.size === trends.length && trends.length > 0}
              ref={(el) => {
                if (el) el.indeterminate = selected.size > 0 && selected.size < trends.length;
              }}
              onChange={toggleSelectAll}
              className="accent-zinc-400 cursor-pointer"
            />
            <span>
              {selected.size > 0
                ? `${selected.size} of ${trends.length} selected`
                : "Select all"}
            </span>
          </div>
        )}

        {flash && (
          <div className="rounded border border-green-700 bg-green-950/30 p-3 text-sm font-mono">
            {flash}
          </div>
        )}
        {error && (
          <div className="rounded border border-red-700 bg-red-950/30 p-3 text-sm font-mono break-all">
            {error}
          </div>
        )}

        <ul className="space-y-3">
          {trends.map((t) => (
            <li
              key={t.id}
              className="group rounded border border-zinc-800 bg-zinc-950/50 p-4 flex gap-4 items-start"
            >
              <input
                type="checkbox"
                checked={selected.has(t.id)}
                onChange={() => toggleSelect(t.id)}
                className="accent-zinc-400 cursor-pointer mt-1.5"
                aria-label={`Select trend ${t.title}`}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1.5 text-xs">
                  <span
                    className={`inline-block rounded border px-2 py-0.5 ${SOURCE_COLORS[t.source]}`}
                  >
                    {t.source}
                  </span>
                  {t.score !== null && (
                    <span className="text-zinc-500">
                      {t.score} pts
                    </span>
                  )}
                  <span className="text-zinc-600">
                    {new Date(t.fetched_at).toLocaleString()}
                  </span>
                </div>
                <a
                  href={t.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-medium hover:underline block break-words"
                >
                  {t.title}
                </a>
                {t.summary && (
                  <p className="text-xs text-zinc-500 mt-2 line-clamp-2">
                    {t.summary.replace(/<[^>]+>/g, "")}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => toggleConsumed(t)}
                  className="text-xs text-zinc-400 hover:text-white border border-zinc-700 rounded px-2.5 py-1 whitespace-nowrap"
                >
                  {t.consumed_at ? "Mark unread" : "Mark consumed"}
                </button>
                <button
                  onClick={() => deleteOne(t)}
                  className="text-xs text-zinc-500 hover:text-red-300 border border-zinc-800 hover:border-red-800 rounded px-2 py-1 opacity-0 group-hover:opacity-100 transition-opacity"
                  aria-label="Delete trend"
                  title="Delete trend"
                >
                  ✕
                </button>
              </div>
            </li>
          ))}
          {!loading && trends.length === 0 && (
            <li className="text-sm text-zinc-500 py-12 text-center">
              No trends in this view. Hit{" "}
              <span className="font-medium text-zinc-300">Refresh now</span>{" "}
              to pull fresh items.
            </li>
          )}
        </ul>
      </div>
    </main>
  );
}

export default TrendsPage;
