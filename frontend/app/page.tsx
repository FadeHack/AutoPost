"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { Banner } from "@/components/ui/Banner";
import { ApiError, apiGet } from "@/lib/api";
import { tokenExpiry } from "@/lib/tokenExpiry";
import type { PostCategory, PostStatus } from "@/lib/domain";

// Today (DESIGN.md §5A) — the command center the daily loop opens on. Answers
// "what needs me, and is the machine healthy?" then acts in one click. Three
// bands: token-health (only when amber/red) · three worklist counters · the
// pipeline funnel + fresh-trends peek + the primary Generate CTA. Connections
// moved to Settings, so this opens on the work, not on plumbing.

type LinkedInStatus = { expires_at: string | null };

type Trend = {
  id: string;
  source: "rss" | "hackernews" | "reddit";
  title: string;
  url: string;
  created_at: string;
};

type Post = {
  id: string;
  status: PostStatus;
  category: PostCategory;
  hook: string;
  scheduled_at: string | null;
  published_at: string | null;
  created_at: string;
};

// Aggregate counts (GET /posts/stats) — so the funnel/counters render numbers
// without pulling a full row set per status. `published_7d` is the recent slice.
type PostStats = {
  draft: number;
  approved: number;
  scheduled: number;
  publishing: number;
  published: number;
  failed: number;
  published_7d: number;
};
const ZERO_STATS: PostStats = {
  draft: 0,
  approved: 0,
  scheduled: 0,
  publishing: 0,
  published: 0,
  failed: 0,
  published_7d: 0,
};

const PEEK_LIMIT = 5; // fresh-trends preview rows
const NEXTUP_LIMIT = 50; // bounded scheduled fetch, only to find the soonest slot

function relativeFromNow(iso: string, now: number): string {
  const diff = new Date(iso).getTime() - now;
  const past = diff <= 0;
  const mins = Math.round(Math.abs(diff) / 60_000);
  let s: string;
  if (mins < 60) s = `${mins} min`;
  else if (mins < 1440) s = `${Math.round(mins / 60)} hr`;
  else s = `${Math.round(mins / 1440)} day${Math.round(mins / 1440) === 1 ? "" : "s"}`;
  return past ? `${s} ago` : `in ${s}`;
}

const SOURCE_LABEL: Record<Trend["source"], string> = {
  rss: "RSS",
  hackernews: "HN",
  reddit: "Reddit",
};

function Today() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { session, loading: authLoading } = useAuth();

  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [trends, setTrends] = useState<Trend[]>([]);
  const [trendCount, setTrendCount] = useState(0);
  const [stats, setStats] = useState<PostStats>(ZERO_STATS);
  const [scheduled, setScheduled] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [connecting, setConnecting] = useState(false);
  // Snapshot the clock once (lazy init runs a single time, keeping render pure).
  const [now] = useState(() => Date.now());

  // OAuth callbacks redirect here with ?<platform>=connected|error.
  const platformResult = (["linkedin", "mastodon", "threads", "instagram", "x"] as const)
    .map((p) => ({ platform: p, value: searchParams.get(p) }))
    .find((r) => r.value);
  const callbackMessage = searchParams.get("message");
  const [callbackDismissed, setCallbackDismissed] = useState(false);

  useEffect(() => {
    if (!authLoading && !session) router.replace("/login");
  }, [authLoading, session, router]);

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    setError("");
    // Counts come from aggregates, not full row sets. The only rows pulled are
    // the 5-item trends peek + a bounded scheduled list (to find the next slot).
    Promise.all([
      apiGet<LinkedInStatus>("/auth/linkedin/status").catch(() => ({
        expires_at: null,
      })),
      apiGet<PostStats>("/posts/stats").catch(() => ZERO_STATS),
      apiGet<{ unconsumed: number }>("/trends/stats").catch(() => ({
        unconsumed: 0,
      })),
      apiGet<Trend[]>(`/trends?status=unconsumed&limit=${PEEK_LIMIT}`).catch(
        () => [],
      ),
      apiGet<Post[]>(`/posts?status=scheduled&limit=${NEXTUP_LIMIT}`).catch(
        () => [],
      ),
    ])
      .then(([li, st, tc, tr, s]) => {
        setExpiresAt(li.expires_at);
        setStats(st);
        setTrendCount(tc.unconsumed);
        setTrends(tr);
        setScheduled(s);
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.body : (e as Error).message),
      )
      .finally(() => setLoading(false));
  }, [session]);

  const reconnect = useCallback(async () => {
    setConnecting(true);
    try {
      const { authorize_url } = await apiGet<{ authorize_url: string }>(
        "/auth/linkedin/start",
      );
      window.location.href = authorize_url;
    } catch {
      setConnecting(false);
    }
  }, []);

  if (authLoading || !session) {
    return <main className="flex-1 p-8 text-ink-lo">Loading…</main>;
  }

  const expiry = tokenExpiry(expiresAt);

  // Next scheduled post, soonest first.
  const nextScheduled = [...scheduled]
    .filter((p) => p.scheduled_at)
    .sort(
      (a, b) =>
        new Date(a.scheduled_at!).getTime() - new Date(b.scheduled_at!).getTime(),
    )[0];

  const needsReview = stats.draft + stats.failed;

  const funnel = [
    { label: "Inbox", count: trendCount, href: "/trends" },
    { label: "Draft", count: stats.draft, href: "/drafts" },
    { label: "Approved", count: stats.approved, href: "/drafts" },
    { label: "Scheduled", count: stats.scheduled, href: "/scheduled" },
    { label: "Live", count: stats.published, href: "/published" },
  ];

  const dateLabel = new Date(now).toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-10">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl tracking-tight text-ink-hi">Today</h1>
          <p className="mt-1 text-sm text-ink-mid">{dateLabel}</p>
        </div>
        <Link
          href="/drafts"
          className="rounded-md bg-accent px-5 py-2.5 text-sm font-medium text-accent-ink hover:bg-accent/90"
        >
          Generate a draft →
        </Link>
      </header>

      {/* Band 1 — token health (only when it needs attention) */}
      {platformResult && !callbackDismissed && (
        <Banner
          tone={platformResult.value === "connected" ? "success" : "error"}
          className="mb-4"
          onDismiss={() => setCallbackDismissed(true)}
          title={
            platformResult.value === "connected"
              ? `${platformResult.platform[0].toUpperCase()}${platformResult.platform.slice(1)} connected.`
              : `${platformResult.platform[0].toUpperCase()}${platformResult.platform.slice(1)} connection failed.`
          }
        >
          {platformResult.value === "error" && callbackMessage && (
            <span className="font-mono break-all">{callbackMessage}</span>
          )}
        </Banner>
      )}

      {expiry && expiry.level !== "ok" && (
        <Banner
          tone={expiry.level === "red" ? "error" : "warn"}
          className="mb-4"
          title={expiry.title}
        >
          <div className="flex items-center justify-between gap-4">
            <span>{expiry.subtitle}</span>
            <button
              onClick={reconnect}
              disabled={connecting}
              className="shrink-0 rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-ink hover:bg-accent/90 disabled:opacity-50"
            >
              {connecting ? "Redirecting…" : "Reconnect"}
            </button>
          </div>
        </Banner>
      )}

      {error && (
        <Banner tone="error" className="mb-4">
          <span className="font-mono break-all">{error}</span>
        </Banner>
      )}

      {/* Band 2 — worklist counters */}
      <section className="mb-8 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Counter
          href="/drafts"
          label="Needs review"
          value={loading ? "—" : `${needsReview}`}
          sub={
            stats.failed > 0
              ? `${stats.draft} draft${stats.draft === 1 ? "" : "s"} · ${stats.failed} failed`
              : "drafts awaiting review"
          }
          alert={stats.failed > 0}
        />
        <Counter
          href="/scheduled"
          label="Scheduled"
          value={loading ? "—" : `${stats.scheduled}`}
          sub={
            nextScheduled?.scheduled_at
              ? `next ${relativeFromNow(nextScheduled.scheduled_at, now)}`
              : "nothing queued"
          }
        />
        <Counter
          href="/published"
          label="Published"
          value={loading ? "—" : `${stats.published_7d}`}
          sub="last 7 days"
        />
      </section>

      {/* Band 3 — pipeline funnel */}
      <section className="mb-8">
        <h2 className="mb-3 text-xs uppercase tracking-wider text-ink-lo">
          Pipeline
        </h2>
        <div className="flex flex-wrap items-stretch gap-1.5">
          {funnel.map((stage, i) => (
            <div key={stage.label} className="flex items-stretch gap-1.5">
              <Link
                href={stage.href}
                className="group flex min-w-[88px] flex-1 flex-col rounded-md border border-border bg-surface-1 px-4 py-3 transition-colors hover:border-ink-lo"
              >
                <span className="font-serif text-2xl text-ink-hi">
                  {loading ? "—" : stage.count}
                </span>
                <span className="mt-0.5 text-xs text-ink-mid group-hover:text-ink-hi">
                  {stage.label}
                </span>
              </Link>
              {i < funnel.length - 1 && (
                <span className="flex items-center text-ink-lo" aria-hidden>
                  →
                </span>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Band 3 — fresh-trends peek */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xs uppercase tracking-wider text-ink-lo">
            Fresh in the inbox
          </h2>
          <Link href="/trends" className="text-xs text-ink-mid hover:text-ink-hi">
            Browse inbox →
          </Link>
        </div>
        {loading ? (
          <p className="text-sm text-ink-lo">Loading…</p>
        ) : trends.length === 0 ? (
          <p className="text-sm text-ink-lo">
            Nothing unconsumed. The 6-hour cron pulls more, or refresh from the
            inbox.
          </p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {trends.slice(0, 5).map((t) => (
              <li key={t.id}>
                <a
                  href={t.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-3 px-4 py-3 hover:bg-surface-1"
                >
                  <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-ink-lo">
                    {SOURCE_LABEL[t.source]}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm text-ink-hi">
                    {t.title}
                  </span>
                  <span className="shrink-0 text-xs text-ink-lo">
                    {relativeFromNow(t.created_at, now)}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

function Counter({
  href,
  label,
  value,
  sub,
  alert = false,
}: {
  href: string;
  label: string;
  value: string;
  sub: string;
  alert?: boolean;
}) {
  return (
    <Link
      href={href}
      className={
        "flex flex-col rounded-md border bg-surface-1 px-5 py-4 transition-colors hover:border-ink-lo " +
        (alert ? "border-status-failed/40" : "border-border")
      }
    >
      <span className="text-xs uppercase tracking-wider text-ink-lo">
        {label}
      </span>
      <span
        className={
          "mt-1 font-serif text-3xl " +
          (alert ? "text-status-failed" : "text-ink-hi")
        }
      >
        {value}
      </span>
      <span className="mt-1 text-xs text-ink-mid">{sub}</span>
    </Link>
  );
}

export default function HomePage() {
  return (
    <Suspense fallback={<main className="flex-1 p-8 text-ink-lo">Loading…</main>}>
      <Today />
    </Suspense>
  );
}
