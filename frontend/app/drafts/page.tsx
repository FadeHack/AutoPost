"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiDelete, apiGet, apiPost } from "@/lib/api";
import { CategoryChip } from "@/components/ui/CategoryChip";
import { StatusPill } from "@/components/ui/StatusPill";
import { PlatformBadge } from "@/components/ui/PlatformBadge";
import { VoiceQualityChip } from "@/components/ui/VoiceQualityChip";
import { Banner } from "@/components/ui/Banner";
import { useToast } from "@/components/ui/Toast";
import { scanVoiceTells } from "@/lib/voice";
import {
  CATEGORY_LABEL,
  GENERATABLE,
  type Platform,
  type PostCategory,
  type PostStatus,
} from "@/lib/domain";

// Drafts — pipeline board (DESIGN.md §5D). The lifecycle rendered spatially.
// Overview = four columns, each a *recent slice* (≤5) with a count + "View all →"
// so the board stays an at-a-glance funnel, not an exhaustive dump. `?view=<status>`
// switches to a full single-status list with "Load more" paging. Every scroll
// region is bounded to its own container — the page chrome never scrolls.

const OVERVIEW_PER_COL = 5;
const LIST_PAGE = 30;

type GenPlatform = Platform;

const GEN_PLATFORMS: { id: GenPlatform; label: string }[] = [
  { id: "linkedin", label: "LinkedIn" },
  { id: "bluesky", label: "Bluesky" },
  { id: "mastodon", label: "Mastodon" },
];
const THREADS_PLATFORM = { id: "threads" as GenPlatform, label: "Threads" };
const INSTAGRAM_PLATFORM = { id: "instagram" as GenPlatform, label: "Instagram" };
const X_PLATFORM = { id: "x" as GenPlatform, label: "X" };

type PostTarget = { id: string; platform: Platform; status: string };

type Post = {
  id: string;
  category: PostCategory;
  status: PostStatus;
  hook: string;
  body: string;
  tags: string[];
  source_trend_ids: string[];
  scheduled_at: string | null;
  published_at: string | null;
  linkedin_urn: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  targets: PostTarget[];
};

type PostStats = {
  draft: number;
  approved: number;
  scheduled: number;
  publishing: number;
  published: number;
  failed: number;
};
const ZERO_STATS: PostStats = {
  draft: 0,
  approved: 0,
  scheduled: 0,
  publishing: 0,
  published: 0,
  failed: 0,
};

// Each board column maps to one or two lifecycle states (publishing rides with
// Scheduled, failed rides with Published). `viewAll` points at the fullest
// surface for that bucket: draft/approved have no dedicated page so they expand
// in place via ?view; scheduled → Calendar, published → Published.
type Column = {
  id: string;
  label: string;
  query: string;
  viewAll: string;
  count: (s: PostStats) => number;
};
const COLUMNS: Column[] = [
  {
    id: "draft",
    label: "Draft",
    query: "draft",
    viewAll: "/drafts?view=draft",
    count: (s) => s.draft,
  },
  {
    id: "approved",
    label: "Approved",
    query: "approved",
    viewAll: "/drafts?view=approved",
    count: (s) => s.approved,
  },
  {
    id: "scheduled",
    label: "Scheduled",
    query: "scheduled,publishing",
    viewAll: "/scheduled",
    count: (s) => s.scheduled + s.publishing,
  },
  {
    id: "published",
    label: "Published",
    query: "published,failed",
    viewAll: "/published",
    count: (s) => s.published + s.failed,
  },
];

const violationsOf = (p: Post) =>
  scanVoiceTells(`${p.hook}\n\n${p.body}`).count;

// ---------------------------------------------------------------------------

function BoardOverview() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { notify } = useToast();

  const pinnedTrendId = searchParams.get("trend");
  const pinnedTrendTitle = searchParams.get("t");
  // Category carried from the trends inbox deep-link (the angle chosen when the
  // trend was picked). Only honor it if it's a real generatable category.
  const pinnedCategoryParam = searchParams.get("category");
  const pinnedCategory = GENERATABLE.includes(
    pinnedCategoryParam as PostCategory,
  )
    ? (pinnedCategoryParam as PostCategory)
    : null;

  const [stats, setStats] = useState<PostStats>(ZERO_STATS);
  const [cols, setCols] = useState<Record<string, Post[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [genCategory, setGenCategory] = useState<PostCategory>(
    pinnedCategory ?? "founder_insight",
  );
  const [genPlatforms, setGenPlatforms] = useState<GenPlatform[]>(["linkedin"]);
  const [threadsEnabled, setThreadsEnabled] = useState(false);
  const [instagramEnabled, setInstagramEnabled] = useState(false);
  const [xEnabled, setXEnabled] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const platformOptions = [
    ...GEN_PLATFORMS,
    ...(threadsEnabled ? [THREADS_PLATFORM] : []),
    ...(instagramEnabled ? [INSTAGRAM_PLATFORM] : []),
    ...(xEnabled ? [X_PLATFORM] : []),
  ];

  useEffect(() => {
    apiGet<{ enabled: boolean }>("/auth/threads/status")
      .then((s) => setThreadsEnabled(!!s.enabled))
      .catch(() => setThreadsEnabled(false));
    apiGet<{ enabled: boolean }>("/auth/instagram/status")
      .then((s) => setInstagramEnabled(!!s.enabled))
      .catch(() => setInstagramEnabled(false));
    apiGet<{ enabled: boolean }>("/auth/x/status")
      .then((s) => setXEnabled(!!s.enabled))
      .catch(() => setXEnabled(false));
  }, []);

  const fetchOverview = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [st, ...lists] = await Promise.all([
        apiGet<PostStats>("/posts/stats"),
        ...COLUMNS.map((c) =>
          apiGet<Post[]>(
            `/posts?status=${c.query}&limit=${OVERVIEW_PER_COL}`,
          ).catch(() => [] as Post[]),
        ),
      ]);
      setStats(st);
      const next: Record<string, Post[]> = {};
      COLUMNS.forEach((c, i) => (next[c.id] = lists[i]));
      setCols(next);
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOverview();
  }, [fetchOverview]);

  const deletePost = async (p: Post) => {
    if (!confirm(`Delete draft "${p.hook.slice(0, 60)}"?`)) return;
    const snapshot = cols;
    setCols((prev) => {
      const next: Record<string, Post[]> = {};
      for (const k of Object.keys(prev))
        next[k] = prev[k].filter((x) => x.id !== p.id);
      return next;
    });
    try {
      await apiDelete(`/posts/${p.id}`);
      notify({ tone: "success", title: "Draft deleted" });
      setStats((s) => ({ ...s, [p.status]: Math.max(0, s[p.status] - 1) }));
    } catch (err) {
      setCols(snapshot);
      setError(err instanceof ApiError ? err.body : (err as Error).message);
    }
  };

  const retryPost = async (p: Post) => {
    setRetryingId(p.id);
    setError("");
    try {
      const updated = await apiPost<Post>(`/posts/${p.id}/retry`);
      setCols((prev) => {
        const next: Record<string, Post[]> = {};
        for (const k of Object.keys(prev))
          next[k] = prev[k].map((x) => (x.id === p.id ? updated : x));
        return next;
      });
      notify({ tone: "info", title: "Retrying publish…" });
    } catch (err) {
      setError(err instanceof ApiError ? err.body : (err as Error).message);
    } finally {
      setRetryingId(null);
    }
  };

  const generate = async () => {
    if (genPlatforms.length === 0) {
      setError("Pick at least one platform.");
      return;
    }
    setGenerating(true);
    setError("");
    try {
      const newPost = await apiPost<Post>("/posts/generate", {
        category: genCategory,
        platforms: genPlatforms,
        ...(pinnedTrendId ? { trend_ids: [pinnedTrendId] } : {}),
      });
      notify({
        tone: "success",
        title: "Draft generated",
        body: newPost.hook.slice(0, 80),
      });
      if (pinnedTrendId) {
        router.push(`/drafts/${newPost.id}`);
        return;
      }
      await fetchOverview();
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const toggleGenPlatform = (p: GenPlatform) =>
    setGenPlatforms((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p],
    );

  return (
    <main className="flex h-full flex-col">
      {/* Fixed chrome — header + generate strip. */}
      <div className="shrink-0 px-6 pt-10">
        <header className="mb-6">
          <h1 className="font-display text-3xl tracking-tight text-ink-hi">
            Drafts
          </h1>
          <p className="mt-2 text-sm text-ink-mid">
            The editorial funnel, left to right. Pull whatever needs you next.
          </p>
        </header>

        {pinnedTrendTitle && (
          <Banner
            tone="info"
            title={`Generating from this trend as “${CATEGORY_LABEL[genCategory]}”`}
            className="mb-4"
            onDismiss={() => router.replace("/drafts")}
          >
            {pinnedTrendTitle}
          </Banner>
        )}

        <section className="mb-4 rounded-lg border border-border bg-surface-1 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={genCategory}
              onChange={(e) => setGenCategory(e.target.value as PostCategory)}
              className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-ink-hi focus:border-ink-lo focus:outline-none"
            >
              {GENERATABLE.map((c) => (
                <option key={c} value={c}>
                  {CATEGORY_LABEL[c]}
                </option>
              ))}
            </select>
            <div className="flex flex-wrap gap-2">
              {platformOptions.map((p) => {
                const on = genPlatforms.includes(p.id);
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => toggleGenPlatform(p.id)}
                    className={
                      "rounded-md border px-3 py-1.5 text-xs font-medium transition-colors " +
                      (on
                        ? "border-accent/60 bg-accent/10 text-ink-hi"
                        : "border-border text-ink-mid hover:bg-surface-2 hover:text-ink-hi")
                    }
                  >
                    {on ? "✓ " : ""}
                    {p.label}
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              onClick={generate}
              disabled={generating || genPlatforms.length === 0}
              className="ml-auto rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-ink hover:opacity-90 disabled:opacity-50"
            >
              {generating ? "Generating…" : "Generate a draft"}
            </button>
          </div>
        </section>

        {error && (
          <Banner tone="error" className="mb-4">
            {error}
          </Banner>
        )}
      </div>

      {/* Scrolling board body — bounded to this region, not the page. */}
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-10">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {COLUMNS.map((col) => {
            const items = cols[col.id] ?? [];
            const total = col.count(stats);
            const more = total - items.length;
            return (
              <section key={col.id} className="min-w-0">
                <div className="mb-3 flex items-center justify-between border-b border-border pb-2">
                  <h2 className="text-sm font-medium text-ink-hi">
                    {col.label}
                  </h2>
                  <span className="text-xs text-ink-lo">{total}</span>
                </div>
                <div className="space-y-3">
                  {items.map((post) => (
                    <BoardCard
                      key={post.id}
                      post={post}
                      violations={violationsOf(post)}
                      retrying={retryingId === post.id}
                      onRetry={() => retryPost(post)}
                      onDelete={() => deletePost(post)}
                    />
                  ))}
                  {!loading && items.length === 0 && (
                    <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-xs text-ink-lo">
                      Nothing here
                    </p>
                  )}
                  {loading && items.length === 0 && (
                    <p className="px-3 py-6 text-center text-xs text-ink-lo">
                      Loading…
                    </p>
                  )}
                  {more > 0 && (
                    <Link
                      href={col.viewAll}
                      className="block rounded-md border border-border px-3 py-2 text-center text-xs font-medium text-ink-mid hover:border-ink-lo hover:text-ink-hi"
                    >
                      View all {total} →
                    </Link>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Full single-status list (?view=draft|approved) with "Load more" paging.

function StatusListView({ status }: { status: "draft" | "approved" }) {
  const { notify } = useToast();
  const [items, setItems] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(
    async (offset: number) => {
      if (offset === 0) setLoading(true);
      else setLoadingMore(true);
      setError("");
      try {
        const page = await apiGet<Post[]>(
          `/posts?status=${status}&limit=${LIST_PAGE}&offset=${offset}`,
        );
        setItems((prev) => (offset === 0 ? page : [...prev, ...page]));
        setHasMore(page.length === LIST_PAGE);
      } catch (e) {
        setError(e instanceof ApiError ? e.body : (e as Error).message);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [status],
  );

  useEffect(() => {
    load(0);
  }, [load]);

  const deletePost = async (p: Post) => {
    if (!confirm(`Delete draft "${p.hook.slice(0, 60)}"?`)) return;
    const snapshot = items;
    setItems((prev) => prev.filter((x) => x.id !== p.id));
    try {
      await apiDelete(`/posts/${p.id}`);
      notify({ tone: "success", title: "Draft deleted" });
    } catch (err) {
      setItems(snapshot);
      setError(err instanceof ApiError ? err.body : (err as Error).message);
    }
  };

  const label = status === "draft" ? "Draft" : "Approved";

  return (
    <main className="flex h-full flex-col">
      <div className="shrink-0 px-6 pt-10">
        <Link
          href="/drafts"
          className="text-sm text-ink-mid hover:text-ink-hi"
        >
          ← Board
        </Link>
        <h1 className="mt-2 font-display text-3xl tracking-tight text-ink-hi">
          {label}
        </h1>
        <p className="mb-6 mt-2 text-sm text-ink-mid">
          Every {label.toLowerCase()} post, newest first.
        </p>
        {error && (
          <Banner tone="error" className="mb-4">
            {error}
          </Banner>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-10">
        <div className="mx-auto grid max-w-3xl grid-cols-1 gap-3 sm:grid-cols-2">
          {items.map((post) => (
            <BoardCard
              key={post.id}
              post={post}
              violations={violationsOf(post)}
              retrying={false}
              onRetry={() => {}}
              onDelete={() => deletePost(post)}
            />
          ))}
        </div>
        {!loading && items.length === 0 && (
          <p className="py-12 text-center text-sm text-ink-lo">
            Nothing here.
          </p>
        )}
        {loading && (
          <p className="py-12 text-center text-sm text-ink-lo">Loading…</p>
        )}
        {hasMore && (
          <div className="mx-auto mt-4 max-w-3xl">
            <button
              type="button"
              onClick={() => load(items.length)}
              disabled={loadingMore}
              className="w-full rounded-md border border-border px-4 py-2 text-sm font-medium text-ink-mid hover:border-ink-lo hover:text-ink-hi disabled:opacity-50"
            >
              {loadingMore ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------

function BoardCard({
  post,
  violations,
  retrying,
  onRetry,
  onDelete,
}: {
  post: Post;
  violations: number;
  retrying: boolean;
  onRetry: () => void;
  onDelete: () => void;
}) {
  const isFailed = post.status === "failed";
  const canDelete = post.status === "draft" || post.status === "failed";
  const platforms = Array.from(new Set(post.targets.map((t) => t.platform)));

  return (
    <div className="group relative">
      <Link
        href={`/drafts/${post.id}`}
        className={
          "block rounded-lg border bg-surface-1 p-4 transition-colors hover:border-ink-lo " +
          (isFailed ? "border-status-failed/40" : "border-border")
        }
      >
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <CategoryChip category={post.category} />
          {isFailed && <StatusPill status="failed" />}
        </div>

        <p className="font-serif text-[15px] leading-snug text-ink-hi line-clamp-3">
          {post.hook}
        </p>

        {platforms.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {platforms.map((pl) => (
              <PlatformBadge key={pl} platform={pl} showLabel={false} />
            ))}
          </div>
        )}

        <div className="mt-3 flex items-center justify-between">
          <VoiceQualityChip violations={violations} />
          {isFailed && (
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onRetry();
              }}
              disabled={retrying}
              className="rounded-md border border-status-failed/40 px-2 py-1 text-xs font-medium text-status-failed hover:bg-status-failed/10 disabled:opacity-50"
              title="Retry publish"
            >
              {retrying ? "Retrying…" : "Retry"}
            </button>
          )}
        </div>
      </Link>

      {canDelete && (
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onDelete();
          }}
          className="absolute right-2 top-2 z-10 rounded-md border border-border bg-surface-2 px-1.5 py-0.5 text-xs text-ink-lo opacity-0 transition-opacity hover:border-status-failed/50 hover:text-status-failed group-hover:opacity-100"
          aria-label="Delete draft"
          title="Delete draft"
        >
          ✕
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function DraftsRouter() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { session, loading: authLoading } = useAuth();

  useEffect(() => {
    if (!authLoading && !session) router.replace("/login");
  }, [authLoading, session, router]);

  if (authLoading || !session) {
    return <main className="flex-1 p-8 text-ink-lo">Loading…</main>;
  }

  const view = searchParams.get("view");
  if (view === "draft" || view === "approved") {
    return <StatusListView status={view} />;
  }
  return <BoardOverview />;
}

// useSearchParams (pinned-trend deep-link + ?view) needs a Suspense boundary.
export default function DraftsPage() {
  return (
    <Suspense
      fallback={<main className="flex-1 p-8 text-ink-lo">Loading…</main>}
    >
      <DraftsRouter />
    </Suspense>
  );
}
