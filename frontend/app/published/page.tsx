"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiGet } from "@/lib/api";
import { CategoryChip } from "@/components/ui/CategoryChip";
import { Banner } from "@/components/ui/Banner";
import { PLATFORM_DOT } from "@/components/ui/PlatformBadge";
import { PLATFORM_LABEL, type Platform, type PostCategory } from "@/lib/domain";

// Published — confirm what went live, jump to the real post (DESIGN.md §5F).
// Each row shows every platform target it fanned out to and that target's
// outcome (partial fan-out shows the failed leg red). A reserved-but-empty
// "Performance" column signals the deferred Phase-7 analytics slot WITHOUT
// faking data — `r_member_social` closed in 2026, so there are no real metrics
// to draw yet (see CONTEXT / memory). The column drops in when Member Data
// Portability lands.

type TargetStatus =
  | "pending"
  | "publishing"
  | "published"
  | "failed"
  | "skipped";

type PostTarget = {
  id: string;
  platform: Platform;
  status: TargetStatus;
  external_urn: string | null;
  error: string | null;
  published_at: string | null;
};

type Post = {
  id: string;
  category: PostCategory;
  status: "published";
  hook: string;
  body: string;
  tags: string[];
  scheduled_at: string | null;
  published_at: string | null;
  linkedin_urn: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  targets: PostTarget[];
};

/**
 * Public link to a LinkedIn post from the URN LinkedIn handed us. Pass the URN
 * through as-is — `/feed/update/{urn}/` redirects share, ugcPost, and activity
 * URNs to the canonical post for every post type. Returns null for unrecognized
 * shapes.
 */
function linkedinUrlFromUrn(urn: string | null): string | null {
  if (!urn) return null;
  if (!/^urn:li:(share|ugcPost|activity):\d+$/.test(urn)) return null;
  return `https://www.linkedin.com/feed/update/${urn}/`;
}

// Best-effort public URL per platform from the stored external_urn. Only the
// platforms whose urn is reconstructable get a link; Threads/Instagram store
// opaque media ids, so they show the outcome without an outbound link.
function targetUrl(platform: Platform, urn: string | null): string | null {
  if (!urn) return null;
  switch (platform) {
    case "linkedin":
      return linkedinUrlFromUrn(urn);
    case "bluesky": {
      // at://did:plc:xxx/app.bsky.feed.post/rkey → bsky.app permalink
      const m = urn.match(/^at:\/\/([^/]+)\/[^/]+\/([^/]+)$/);
      return m ? `https://bsky.app/profile/${m[1]}/post/${m[2]}` : null;
    }
    case "mastodon":
      return urn.startsWith("http") ? urn : null;
    case "x":
      // external_urn is the numeric tweet id; the /i/web/status/ form
      // redirects to the tweet regardless of author handle.
      return `https://x.com/i/web/status/${urn}`;
    default:
      return null;
  }
}

function ago(iso: string, now: number): string {
  const diff = now - new Date(iso).getTime();
  const hrs = Math.round(diff / 3_600_000);
  if (hrs < 1) return "just now";
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  return `${months}mo ago`;
}

const PAGE = 30;

function PublishedPage() {
  const router = useRouter();
  const { session, loading: authLoading } = useAuth();

  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState("");
  const [now] = useState(() => Date.now());

  useEffect(() => {
    if (!authLoading && !session) router.replace("/login");
  }, [authLoading, session, router]);

  const load = useCallback(
    async (offset: number) => {
      if (!session) return;
      if (offset === 0) setLoading(true);
      else setLoadingMore(true);
      setError("");
      try {
        const page = await apiGet<Post[]>(
          `/posts?status=published&limit=${PAGE}&offset=${offset}`,
        );
        setPosts((prev) => (offset === 0 ? page : [...prev, ...page]));
        setHasMore(page.length === PAGE);
      } catch (e) {
        setError(e instanceof ApiError ? e.body : (e as Error).message);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [session],
  );

  useEffect(() => {
    load(0);
  }, [load]);

  // Most-recent first by published_at within the loaded set (server pages by
  // created_at desc; for published posts the two orders rarely diverge).
  const sorted = useMemo(
    () =>
      [...posts].sort(
        (a, b) =>
          new Date(b.published_at ?? b.created_at).getTime() -
          new Date(a.published_at ?? a.created_at).getTime(),
      ),
    [posts],
  );

  if (authLoading || !session) {
    return <main className="flex-1 p-8 text-ink-lo">Loading…</main>;
  }

  return (
    <main className="flex h-full flex-col">
      {/* Fixed chrome. */}
      <div className="mx-auto w-full max-w-5xl shrink-0 px-6 pt-10">
        <header className="mb-6">
          <h1 className="font-serif text-3xl tracking-tight text-ink-hi">
            Published
          </h1>
          <p className="mt-2 text-sm text-ink-mid">
            What went live, most recent first.
          </p>
        </header>

        {error && (
          <Banner tone="error" className="mb-6">
            {error}
          </Banner>
        )}

        {/* Column headers — the empty Performance slot is intentional (§5F). */}
        <div className="hidden grid-cols-[1fr_150px] gap-4 border-b border-border px-4 pb-2 text-xs font-medium uppercase tracking-wide text-ink-lo sm:grid">
          <span>Post</span>
          <span className="border-l border-border pl-4">Performance</span>
        </div>
      </div>

      {/* Scrolling list — bounded to this region. */}
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-10">
        <ul className="mx-auto mt-3 w-full max-w-5xl space-y-3">
          {sorted.map((p) => (
            <li
              key={p.id}
              className="grid grid-cols-1 gap-4 rounded-lg border border-border bg-surface-1 p-4 sm:grid-cols-[1fr_150px]"
            >
              <div className="min-w-0">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-ink-lo">
                  <CategoryChip category={p.category} />
                  {p.published_at && (
                    <span>
                      {new Date(p.published_at).toLocaleDateString([], {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}{" "}
                      · {ago(p.published_at, now)}
                    </span>
                  )}
                </div>

                <Link
                  href={`/drafts/${p.id}`}
                  className="block font-serif text-[15px] leading-snug text-ink-hi line-clamp-2 hover:underline"
                >
                  {p.hook}
                </Link>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  {p.targets.length === 0 ? (
                    <LegacyLinkedInChip urn={p.linkedin_urn} />
                  ) : (
                    p.targets.map((t) => <TargetChip key={t.id} target={t} />)
                  )}
                </div>
              </div>

              {/* Reserved Performance cell — no fake charts (§5F). */}
              <div className="hidden items-center border-l border-border pl-4 text-xs text-ink-lo sm:flex">
                <span title="Analytics deferred until Member Data Portability lands">
                  —
                </span>
              </div>
            </li>
          ))}
          {!loading && sorted.length === 0 && (
            <li className="rounded-lg border border-dashed border-border py-12 text-center text-sm text-ink-lo">
              Nothing published yet. Approved drafts ship from the{" "}
              <Link href="/scheduled" className="underline">
                Calendar
              </Link>
              .
            </li>
          )}
        </ul>

        {hasMore && (
          <div className="mx-auto mt-4 w-full max-w-5xl">
            <button
              type="button"
              onClick={() => load(posts.length)}
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

function TargetChip({ target }: { target: PostTarget }) {
  const url = targetUrl(target.platform, target.external_urn);
  const failed = target.status === "failed";
  const skipped = target.status === "skipped";
  const label = PLATFORM_LABEL[target.platform];

  const inner = (
    <>
      <span className={"h-1.5 w-1.5 rounded-full " + PLATFORM_DOT[target.platform]} />
      {label}
      {failed ? (
        <span className="text-status-failed">· failed</span>
      ) : skipped ? (
        <span className="text-ink-lo">· manual</span>
      ) : url ? (
        <span aria-hidden>↗</span>
      ) : (
        <span className="text-status-published">✓</span>
      )}
    </>
  );

  const base =
    "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs " +
    (failed
      ? "border-status-failed/40 text-status-failed"
      : "border-border text-ink-mid");

  if (url && !failed && !skipped) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        title={`View on ${label}`}
        className={base + " hover:border-ink-lo hover:text-ink-hi"}
      >
        {inner}
      </a>
    );
  }
  return (
    <span
      title={
        failed
          ? (target.error ?? "Publish failed")
          : skipped
            ? "Not published via API — posted by hand"
            : label
      }
      className={base}
    >
      {inner}
    </span>
  );
}

// Pre-fan-out posts (only `linkedin_urn`, no PostTarget rows).
function LegacyLinkedInChip({ urn }: { urn: string | null }) {
  const url = linkedinUrlFromUrn(urn);
  const base =
    "inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs text-ink-mid";
  if (url) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className={base + " hover:border-ink-lo hover:text-ink-hi"}
      >
        <span className={"h-1.5 w-1.5 rounded-full " + PLATFORM_DOT.linkedin} />
        LinkedIn <span aria-hidden>↗</span>
      </a>
    );
  }
  return <span className={base}>No external link</span>;
}

export default PublishedPage;
