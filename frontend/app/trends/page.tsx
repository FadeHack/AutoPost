"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { Banner } from "@/components/ui/Banner";
import { useToast } from "@/components/ui/Toast";

// Inbox — trend triage (DESIGN.md §5B). Trends are high-volume and disposable:
// "skim, judge, act" is a list, not a gallery. Dense email-triage rows, filters
// in a left strip, keyboard-navigable (j/k move · e consume · g generate · ⏎
// open). Per-row Generate → deep-links into the board's generate strip with this
// trend pinned, collapsing "read → go to drafts → pick category → find it again"
// into one move.

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

// Source coding is real provenance (like a platform hue), so a small colored dot
// is allowed; the chip chrome stays neutral.
const SOURCE_DOT: Record<TrendSource, string> = {
  rss: "bg-sky-500",
  hackernews: "bg-orange-500",
  reddit: "bg-rose-500",
};
const SOURCE_LABEL: Record<TrendSource, string> = {
  rss: "RSS",
  hackernews: "HN",
  reddit: "Reddit",
};

const STATUS_OPTS: { id: StatusFilter; label: string }[] = [
  { id: "unconsumed", label: "Unconsumed" },
  { id: "consumed", label: "Consumed" },
  { id: "all", label: "All" },
];
const SOURCE_OPTS: { id: TrendSource | "all"; label: string }[] = [
  { id: "all", label: "All sources" },
  { id: "rss", label: "RSS" },
  { id: "hackernews", label: "HackerNews" },
  { id: "reddit", label: "Reddit" },
];

function ago(iso: string, now: number): string {
  const diff = now - new Date(iso).getTime();
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return `${days}d ago`;
}

function TrendsInbox() {
  const router = useRouter();
  const { session, loading: authLoading } = useAuth();
  const { notify } = useToast();

  const [trends, setTrends] = useState<Trend[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("unconsumed");
  const [sourceFilter, setSourceFilter] = useState<TrendSource | "all">("all");
  const [error, setError] = useState("");
  const [cursor, setCursor] = useState(0);
  const [now] = useState(() => Date.now());
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (!authLoading && !session) router.replace("/login");
  }, [authLoading, session, router]);

  const fetchTrends = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ status: statusFilter, limit: "100" });
      if (sourceFilter !== "all") params.set("source", sourceFilter);
      const data = await apiGet<Trend[]>(`/trends?${params.toString()}`);
      setTrends(data);
      setCursor(0);
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
    try {
      const r = await apiPost<RefreshResult>("/trends/refresh");
      notify({
        tone: "success",
        title: `Pulled ${r.inserted} new`,
        body: `fetched ${r.fetched}, deduped ${r.deduped}`,
      });
      await fetchTrends();
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setRefreshing(false);
    }
  };

  const toggleConsumed = useCallback(
    async (trend: Trend) => {
      const becomingConsumed = trend.consumed_at === null;
      setTrends((prev) =>
        prev.map((t) =>
          t.id === trend.id
            ? { ...t, consumed_at: becomingConsumed ? new Date().toISOString() : null }
            : t,
        ),
      );
      try {
        await apiPatch<Trend>(`/trends/${trend.id}`, { consumed: becomingConsumed });
        // Drop from view if it no longer matches the active filter.
        if (
          (statusFilter === "unconsumed" && becomingConsumed) ||
          (statusFilter === "consumed" && !becomingConsumed)
        ) {
          setTrends((prev) => prev.filter((t) => t.id !== trend.id));
        }
      } catch (e) {
        setTrends((prev) =>
          prev.map((t) =>
            t.id === trend.id ? { ...t, consumed_at: trend.consumed_at } : t,
          ),
        );
        setError(e instanceof ApiError ? e.body : (e as Error).message);
      }
    },
    [statusFilter],
  );

  const deleteOne = useCallback(async (trend: Trend) => {
    setError("");
    const snapshot = trends;
    setTrends((prev) => prev.filter((t) => t.id !== trend.id));
    try {
      await apiDelete(`/trends/${trend.id}`);
    } catch (e) {
      setTrends(snapshot);
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    }
  // intentionally only depends on `trends` snapshot
  }, [trends]);

  const generateFrom = useCallback(
    (trend: Trend) => {
      const qs = new URLSearchParams({ trend: trend.id, t: trend.title });
      router.push(`/drafts?${qs.toString()}`);
    },
    [router],
  );

  // Keyboard triage. Ignored while focus is in a form control.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (
        e.metaKey ||
        e.ctrlKey ||
        e.altKey ||
        ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)
      ) {
        return;
      }
      if (trends.length === 0) return;
      const key = e.key;
      if (key === "j" || key === "ArrowDown") {
        e.preventDefault();
        setCursor((c) => Math.min(c + 1, trends.length - 1));
      } else if (key === "k" || key === "ArrowUp") {
        e.preventDefault();
        setCursor((c) => Math.max(c - 1, 0));
      } else if (key === "e") {
        e.preventDefault();
        const t = trends[cursor];
        if (t) toggleConsumed(t);
      } else if (key === "g") {
        e.preventDefault();
        const t = trends[cursor];
        if (t) generateFrom(t);
      } else if (key === "Enter") {
        e.preventDefault();
        const t = trends[cursor];
        if (t) window.open(t.url, "_blank", "noopener,noreferrer");
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [trends, cursor, toggleConsumed, generateFrom]);

  // Keep the active row in view as the cursor moves.
  useEffect(() => {
    const node = listRef.current?.querySelector(`[data-idx="${cursor}"]`);
    node?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const counts = useMemo(
    () => ({ total: trends.length }),
    [trends.length],
  );

  if (authLoading || !session) {
    return <main className="flex-1 p-8 text-ink-lo">Loading…</main>;
  }

  return (
    <main className="mx-auto w-full max-w-6xl px-6 py-10">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl tracking-tight text-ink-hi">Inbox</h1>
          <p className="mt-2 text-sm text-ink-mid">
            Fresh retrieval to triage. Skim, judge, hand straight into a draft.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={refreshing}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-ink hover:opacity-90 disabled:opacity-50"
        >
          {refreshing ? "Refreshing…" : "Refresh now"}
        </button>
      </header>

      {error && (
        <Banner tone="error" className="mb-6">
          {error}
        </Banner>
      )}

      <div className="flex flex-col gap-6 md:grid md:grid-cols-[180px_1fr]">
        {/* Left filter strip. */}
        <aside className="flex flex-col gap-5">
          <FilterGroup label="Status">
            {STATUS_OPTS.map((o) => (
              <FilterRow
                key={o.id}
                active={statusFilter === o.id}
                onClick={() => setStatusFilter(o.id)}
              >
                {o.label}
              </FilterRow>
            ))}
          </FilterGroup>
          <FilterGroup label="Source">
            {SOURCE_OPTS.map((o) => (
              <FilterRow
                key={o.id}
                active={sourceFilter === o.id}
                onClick={() => setSourceFilter(o.id)}
              >
                {o.id !== "all" && (
                  <span
                    className={"h-1.5 w-1.5 rounded-full " + SOURCE_DOT[o.id]}
                  />
                )}
                {o.label}
              </FilterRow>
            ))}
          </FilterGroup>
          <p className="text-xs leading-relaxed text-ink-lo">
            <span className="font-medium text-ink-mid">Keys</span>
            <br />
            <kbd className="text-ink-mid">j/k</kbd> move ·{" "}
            <kbd className="text-ink-mid">e</kbd> consume
            <br />
            <kbd className="text-ink-mid">g</kbd> generate ·{" "}
            <kbd className="text-ink-mid">⏎</kbd> open
          </p>
        </aside>

        {/* Triage list. */}
        <section className="min-w-0">
          <p className="mb-2 text-xs text-ink-lo">
            {loading
              ? "Loading…"
              : `${counts.total} item${counts.total === 1 ? "" : "s"}`}
          </p>
          <ul
            ref={listRef}
            className="divide-y divide-border overflow-hidden rounded-lg border border-border"
          >
            {trends.map((t, i) => {
              const active = i === cursor;
              return (
                <li
                  key={t.id}
                  data-idx={i}
                  onMouseEnter={() => setCursor(i)}
                  className={
                    "group flex items-start gap-3 px-3 py-2.5 text-sm transition-colors " +
                    (active ? "bg-surface-2" : "bg-surface-1 hover:bg-surface-2")
                  }
                >
                  <span
                    className={
                      "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full " +
                      SOURCE_DOT[t.source]
                    }
                    title={SOURCE_LABEL[t.source]}
                  />
                  <div className="min-w-0 flex-1">
                    <a
                      href={t.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={
                        "block break-words font-medium leading-snug hover:underline " +
                        (t.consumed_at ? "text-ink-lo" : "text-ink-hi")
                      }
                    >
                      {t.title}
                    </a>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-ink-lo">
                      <span>{SOURCE_LABEL[t.source]}</span>
                      {t.score !== null && <span>· {t.score} pts</span>}
                      <span>· {ago(t.fetched_at, now)}</span>
                      {t.consumed_at && <span>· consumed</span>}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      onClick={() => generateFrom(t)}
                      className="rounded-md border border-accent/50 px-2 py-1 text-xs font-medium text-ink-hi hover:bg-accent/10"
                      title="Generate a draft from this trend (g)"
                    >
                      Generate →
                    </button>
                    <button
                      type="button"
                      onClick={() => toggleConsumed(t)}
                      className="rounded-md border border-border px-2 py-1 text-xs text-ink-mid hover:text-ink-hi"
                      title="Toggle consumed (e)"
                    >
                      {t.consumed_at ? "Unread" : "Consume"}
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteOne(t)}
                      className="rounded-md border border-border px-1.5 py-1 text-xs text-ink-lo opacity-0 transition-opacity hover:border-status-failed/50 hover:text-status-failed group-hover:opacity-100"
                      aria-label="Delete trend"
                      title="Delete trend"
                    >
                      ✕
                    </button>
                  </div>
                </li>
              );
            })}
            {!loading && trends.length === 0 && (
              <li className="px-3 py-12 text-center text-sm text-ink-lo">
                Nothing here. Hit{" "}
                <span className="font-medium text-ink-mid">Refresh now</span> to
                pull fresh items.
              </li>
            )}
          </ul>
        </section>
      </div>
    </main>
  );
}

function FilterGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-ink-lo">
        {label}
      </p>
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  );
}

function FilterRow({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors " +
        (active
          ? "bg-surface-2 font-medium text-ink-hi"
          : "text-ink-mid hover:text-ink-hi")
      }
    >
      {children}
    </button>
  );
}

export default TrendsInbox;
