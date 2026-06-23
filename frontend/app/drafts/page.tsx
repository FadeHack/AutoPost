"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
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

// Drafts — pipeline board (DESIGN.md §5D). The status enum rendered spatially:
// four columns mapping 1:1 to the lifecycle, read left-to-right as a funnel.
// Replaces the old flat status-filtered list. Today's "Generate a draft" CTA
// lands here, so the generate affordance stays on the board (top strip).

// Currently-implemented publishers. Threads + Instagram are Meta-gated — only
// shown when the backend reports them enabled (PLATFORM_{THREADS,INSTAGRAM}_ENABLED).
type GenPlatform = Platform;

const GEN_PLATFORMS: { id: GenPlatform; label: string }[] = [
  { id: "linkedin", label: "LinkedIn" },
  { id: "bluesky", label: "Bluesky" },
  { id: "mastodon", label: "Mastodon" },
];

const THREADS_PLATFORM: { id: GenPlatform; label: string } = {
  id: "threads",
  label: "Threads",
};
const INSTAGRAM_PLATFORM: { id: GenPlatform; label: string } = {
  id: "instagram",
  label: "Instagram",
};

type PostTarget = {
  id: string;
  platform: Platform;
  status: string;
};

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

// The board's columns. Each maps to one or two lifecycle states so every status
// is visible across exactly four columns (DESIGN.md §5D). `publishing` rides in
// the Scheduled column (it's in-flight from a schedule); `failed` rides in the
// Published column rendered red with a retry affordance (it's a terminal outcome
// of the publish attempt).
const COLUMNS: { id: string; label: string; statuses: PostStatus[] }[] = [
  { id: "draft", label: "Draft", statuses: ["draft"] },
  { id: "approved", label: "Approved", statuses: ["approved"] },
  { id: "scheduled", label: "Scheduled", statuses: ["scheduled", "publishing"] },
  { id: "published", label: "Published", statuses: ["published", "failed"] },
];

function DraftsBoard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { session, loading: authLoading } = useAuth();
  const { notify } = useToast();

  // A trend handed in from the Inbox (DESIGN.md §5B "Generate →"). Pins the
  // generation to this trend's content; the operator still picks category +
  // platforms here, then lands in the new draft's cockpit.
  const pinnedTrendId = searchParams.get("trend");
  const pinnedTrendTitle = searchParams.get("t");

  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [genCategory, setGenCategory] = useState<PostCategory>("founder_insight");
  const [genPlatforms, setGenPlatforms] = useState<GenPlatform[]>(["linkedin"]);
  const [threadsEnabled, setThreadsEnabled] = useState(false);
  const [instagramEnabled, setInstagramEnabled] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const platformOptions = [
    ...GEN_PLATFORMS,
    ...(threadsEnabled ? [THREADS_PLATFORM] : []),
    ...(instagramEnabled ? [INSTAGRAM_PLATFORM] : []),
  ];

  useEffect(() => {
    if (!authLoading && !session) router.replace("/login");
  }, [authLoading, session, router]);

  useEffect(() => {
    if (!session) return;
    apiGet<{ enabled: boolean }>("/auth/threads/status")
      .then((s) => setThreadsEnabled(!!s.enabled))
      .catch(() => setThreadsEnabled(false));
    apiGet<{ enabled: boolean }>("/auth/instagram/status")
      .then((s) => setInstagramEnabled(!!s.enabled))
      .catch(() => setInstagramEnabled(false));
  }, [session]);

  const fetchPosts = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const data = await apiGet<Post[]>("/posts?limit=200");
      setPosts(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    fetchPosts();
  }, [fetchPosts]);

  // Bucket once per posts change; voice violations computed here so cards stay
  // presentational. Within a column, newest first.
  const buckets = useMemo(() => {
    const withVoice = posts.map((p) => ({
      post: p,
      violations: scanVoiceTells(`${p.hook}\n\n${p.body}`).count,
    }));
    return COLUMNS.map((col) => ({
      ...col,
      items: withVoice
        .filter((x) => col.statuses.includes(x.post.status))
        .sort(
          (a, b) =>
            new Date(b.post.created_at).getTime() -
            new Date(a.post.created_at).getTime(),
        ),
    }));
  }, [posts]);

  const deletePost = async (p: Post) => {
    if (!confirm(`Delete draft "${p.hook.slice(0, 60)}"?`)) return;
    setError("");
    const snapshot = posts;
    setPosts((prev) => prev.filter((x) => x.id !== p.id));
    try {
      await apiDelete(`/posts/${p.id}`);
      notify({ tone: "success", title: "Draft deleted" });
    } catch (err) {
      setPosts(snapshot);
      setError(err instanceof ApiError ? err.body : (err as Error).message);
    }
  };

  const retryPost = async (p: Post) => {
    setRetryingId(p.id);
    setError("");
    try {
      const updated = await apiPost<Post>(`/posts/${p.id}/retry`);
      setPosts((prev) => prev.map((x) => (x.id === p.id ? updated : x)));
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
      // Generated from an Inbox trend → land straight in the cockpit.
      if (pinnedTrendId) {
        router.push(`/drafts/${newPost.id}`);
        return;
      }
      await fetchPosts();
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const toggleGenPlatform = (p: GenPlatform) => {
    setGenPlatforms((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p],
    );
  };

  if (authLoading || !session) {
    return <main className="flex-1 p-8 text-ink-lo">Loading…</main>;
  }

  return (
    <main className="mx-auto w-full max-w-7xl px-6 py-10">
      <header className="mb-6">
        <h1 className="font-serif text-3xl tracking-tight text-ink-hi">Drafts</h1>
        <p className="mt-2 text-sm text-ink-mid">
          The editorial funnel, left to right. Pull whatever needs you next.
        </p>
      </header>

      {pinnedTrendTitle && (
        <Banner
          tone="info"
          title="Generating from this trend"
          className="mb-4"
          onDismiss={() => router.replace("/drafts")}
        >
          {pinnedTrendTitle}
        </Banner>
      )}

      {/* Generate strip — Today's CTA (and Inbox "Generate →") lands here. */}
      <section className="mb-6 rounded-lg border border-border bg-surface-1 p-4">
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
        <p className="mt-2 text-xs text-ink-lo">
          One draft, one editorial cycle. Each non-LinkedIn platform gets a
          compressed variant generated alongside.
        </p>
      </section>

      {error && (
        <Banner tone="error" className="mb-6">
          {error}
        </Banner>
      )}

      {/* The board. Desktop: 4 columns; tablet: 2×2; mobile: stacked. */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {buckets.map((col) => (
          <section key={col.id} className="min-w-0">
            <div className="mb-3 flex items-center justify-between border-b border-border pb-2">
              <h2 className="text-sm font-medium text-ink-hi">{col.label}</h2>
              <span className="text-xs text-ink-lo">{col.items.length}</span>
            </div>
            <div className="space-y-3">
              {col.items.map(({ post, violations }) => (
                <BoardCard
                  key={post.id}
                  post={post}
                  violations={violations}
                  retrying={retryingId === post.id}
                  onRetry={() => retryPost(post)}
                  onDelete={() => deletePost(post)}
                />
              ))}
              {!loading && col.items.length === 0 && (
                <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-xs text-ink-lo">
                  Nothing here
                </p>
              )}
              {loading && col.items.length === 0 && (
                <p className="px-3 py-6 text-center text-xs text-ink-lo">Loading…</p>
              )}
            </div>
          </section>
        ))}
      </div>
    </main>
  );
}

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
  // De-dupe target platforms (one badge per platform).
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

// useSearchParams (for the pinned-trend deep-link) needs a Suspense boundary.
export default function DraftsPage() {
  return (
    <Suspense
      fallback={<main className="flex-1 p-8 text-ink-lo">Loading…</main>}
    >
      <DraftsBoard />
    </Suspense>
  );
}
