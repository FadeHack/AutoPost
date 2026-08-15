"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { CategoryChip } from "@/components/ui/CategoryChip";
import { PlatformBadge, PLATFORM_DOT } from "@/components/ui/PlatformBadge";
import { Banner } from "@/components/ui/Banner";
import { useToast } from "@/components/ui/Toast";
import { type Platform, type PostCategory, type PostStatus } from "@/lib/domain";

// Calendar (DESIGN.md §5E). Scheduling is the backbone (APScheduler, jobstore-
// persisted) but had no time view — a flat list can't show "nothing ships
// Thu–Sun" or "three stacked Monday morning." This is a month/week grid: each
// scheduled post is a block at its slot, color = platform. Drag a block to a new
// day to reschedule (preserves time-of-day) through the idempotent `/schedule`
// endpoint. Right rail = "next up" chronological. Mobile collapses to an agenda.

type PostTarget = { id: string; platform: Platform; status: string };

type Post = {
  id: string;
  category: PostCategory;
  status: PostStatus;
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

const MIN_LEAD_MS = 60_000; // backend MIN_SCHEDULE_LEAD_SECONDS
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// --- pure date helpers ---
function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}
function addDays(d: Date, n: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}
function addMonths(d: Date, n: number): Date {
  const x = new Date(d);
  x.setMonth(x.getMonth() + n);
  return x;
}
function startOfWeek(d: Date): Date {
  const x = startOfDay(d);
  return addDays(x, -x.getDay()); // week starts Sunday
}
function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}
function monthGrid(anchor: Date): Date[] {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const start = startOfWeek(first);
  return Array.from({ length: 42 }, (_, i) => addDays(start, i));
}
function weekGrid(anchor: Date): Date[] {
  const start = startOfWeek(anchor);
  return Array.from({ length: 7 }, (_, i) => addDays(start, i));
}
// Reschedule preserves the original time-of-day, only moving the date.
function withDay(originalIso: string | null, day: Date): Date {
  const o = originalIso ? new Date(originalIso) : new Date();
  const d = new Date(day);
  d.setHours(o.getHours(), o.getMinutes(), 0, 0);
  return d;
}
function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

type View = "month" | "week";

function CalendarPage() {
  const router = useRouter();
  const { session, loading: authLoading } = useAuth();
  const { notify } = useToast();

  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("month");
  const [anchor, setAnchor] = useState<Date>(() => new Date());
  const [now] = useState<number>(() => Date.now());
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverKey, setDragOverKey] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !session) router.replace("/login");
  }, [authLoading, session, router]);

  const fetchPosts = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      // Multi-status server filter — only the slots the calendar renders, so a
      // growing published history can't crowd them out of the row budget.
      const data = await apiGet<Post[]>(
        "/posts?status=scheduled,publishing&limit=200",
      );
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

  const scheduled = useMemo(
    () => posts.filter((p) => p.scheduled_at),
    [posts],
  );

  // Chronological "next up" — preserves the old flat-list sort.
  const nextUp = useMemo(
    () =>
      [...scheduled].sort(
        (a, b) =>
          new Date(a.scheduled_at!).getTime() -
          new Date(b.scheduled_at!).getTime(),
      ),
    [scheduled],
  );

  const days = view === "month" ? monthGrid(anchor) : weekGrid(anchor);

  const postsOn = useCallback(
    (day: Date) =>
      scheduled
        .filter((p) => sameDay(new Date(p.scheduled_at!), day))
        .sort(
          (a, b) =>
            new Date(a.scheduled_at!).getTime() -
            new Date(b.scheduled_at!).getTime(),
        ),
    [scheduled],
  );

  const reschedule = async (post: Post, day: Date) => {
    const target = withDay(post.scheduled_at, day);
    if (target.getTime() < now + MIN_LEAD_MS) {
      notify({ tone: "warn", title: "Pick a future slot" });
      return;
    }
    if (post.scheduled_at && sameDay(new Date(post.scheduled_at), day)) return;
    const iso = target.toISOString();
    const snapshot = posts;
    setPosts((prev) =>
      prev.map((p) => (p.id === post.id ? { ...p, scheduled_at: iso } : p)),
    );
    try {
      await apiPost<Post>(`/posts/${post.id}/schedule`, { scheduled_at: iso });
      notify({
        tone: "success",
        title: "Rescheduled",
        body: target.toLocaleString([], {
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
        }),
      });
    } catch (e) {
      setPosts(snapshot);
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    }
  };

  const onDrop = (day: Date) => {
    setDragOverKey(null);
    const post = posts.find((p) => p.id === draggingId);
    setDraggingId(null);
    if (post) reschedule(post, day);
  };

  if (authLoading || !session) {
    return <main className="flex-1 p-8 text-ink-lo">Loading…</main>;
  }

  const periodLabel =
    view === "month"
      ? anchor.toLocaleDateString([], { month: "long", year: "numeric" })
      : (() => {
          const s = weekGrid(anchor)[0];
          const e = weekGrid(anchor)[6];
          return `${s.toLocaleDateString([], { month: "short", day: "numeric" })} – ${e.toLocaleDateString(
            [],
            { month: "short", day: "numeric" },
          )}`;
        })();

  const step = (dir: -1 | 1) =>
    setAnchor((a) => (view === "month" ? addMonths(a, dir) : addDays(a, dir * 7)));

  return (
    <main className="flex h-full flex-col">
      <div className="shrink-0 px-6 pt-10">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl tracking-tight text-ink-hi">
            Calendar
          </h1>
          <p className="mt-2 text-sm text-ink-mid">
            Your publishing cadence. Drag a post to a new day to reschedule.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 rounded-md border border-border p-0.5">
            {(["month", "week"] as View[]).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                className={
                  "rounded px-3 py-1 text-xs font-medium capitalize transition-colors " +
                  (view === v
                    ? "bg-surface-2 text-ink-hi"
                    : "text-ink-mid hover:text-ink-hi")
                }
              >
                {v}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => step(-1)}
              className="rounded-md border border-border px-2 py-1 text-sm text-ink-mid hover:text-ink-hi"
              aria-label="Previous"
            >
              ‹
            </button>
            <button
              type="button"
              onClick={() => setAnchor(new Date())}
              className="rounded-md border border-border px-3 py-1 text-xs font-medium text-ink-mid hover:text-ink-hi"
            >
              Today
            </button>
            <button
              type="button"
              onClick={() => step(1)}
              className="rounded-md border border-border px-2 py-1 text-sm text-ink-mid hover:text-ink-hi"
              aria-label="Next"
            >
              ›
            </button>
          </div>
        </div>
      </header>

      {error && (
        <Banner tone="error" className="mb-6">
          {error}
        </Banner>
      )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-10">
      <div className="flex flex-col gap-6 md:grid md:grid-cols-[1fr_280px]">
        {/* Grid — hidden on mobile (agenda takes over). */}
        <section className="hidden md:block">
          <p className="mb-3 text-sm font-medium text-ink-hi">{periodLabel}</p>
          <div className="grid grid-cols-7 gap-px rounded-lg border border-border bg-border text-xs">
            {WEEKDAYS.map((w) => (
              <div
                key={w}
                className="bg-surface-1 px-2 py-1.5 text-center font-medium text-ink-lo"
              >
                {w}
              </div>
            ))}
            {days.map((day) => {
              const key = day.toISOString();
              const inMonth =
                view === "week" || day.getMonth() === anchor.getMonth();
              const isToday = sameDay(day, new Date(now));
              const isPast = startOfDay(day).getTime() < startOfDay(new Date(now)).getTime();
              const dayPosts = postsOn(day);
              return (
                <div
                  key={key}
                  onDragOver={(e) => {
                    if (draggingId) {
                      e.preventDefault();
                      setDragOverKey(key);
                    }
                  }}
                  onDragLeave={() =>
                    setDragOverKey((k) => (k === key ? null : k))
                  }
                  onDrop={() => onDrop(day)}
                  className={
                    "group relative min-h-[92px] bg-surface-1 p-1.5 align-top " +
                    (view === "week" ? "min-h-[260px] " : "") +
                    (inMonth ? "" : "opacity-40 ") +
                    (dragOverKey === key ? "ring-1 ring-inset ring-accent " : "")
                  }
                >
                  <div className="mb-1 flex items-center justify-between">
                    <span
                      className={
                        "inline-flex h-5 w-5 items-center justify-center rounded-full text-[11px] " +
                        (isToday
                          ? "bg-accent font-semibold text-accent-ink"
                          : isPast
                            ? "text-ink-lo"
                            : "text-ink-mid")
                      }
                    >
                      {day.getDate()}
                    </span>
                    {!isPast && (
                      <Link
                        href="/drafts"
                        title="Generate a draft for this slot"
                        className="text-ink-lo opacity-0 transition-opacity hover:text-ink-hi group-hover:opacity-100"
                      >
                        +
                      </Link>
                    )}
                  </div>
                  <div className="space-y-1">
                    {dayPosts.map((p) => (
                      <CalendarBlock
                        key={p.id}
                        post={p}
                        onDragStart={() => setDraggingId(p.id)}
                        onDragEnd={() => setDraggingId(null)}
                        onClick={() => router.push(`/drafts/${p.id}`)}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Next up — right rail on desktop, the whole view on mobile. */}
        <aside className="min-w-0">
          <p className="mb-3 text-sm font-medium text-ink-hi">
            Next up{" "}
            <span className="text-ink-lo">({nextUp.length})</span>
          </p>
          <div className="space-y-2">
            {nextUp.map((p) => (
              <Link
                key={p.id}
                href={`/drafts/${p.id}`}
                className="block rounded-lg border border-border bg-surface-1 p-3 transition-colors hover:border-ink-lo"
              >
                <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                  <CategoryChip category={p.category} />
                  {Array.from(new Set(p.targets.map((t) => t.platform))).map(
                    (pl) => (
                      <PlatformBadge key={pl} platform={pl} showLabel={false} />
                    ),
                  )}
                </div>
                <p className="font-serif text-sm leading-snug text-ink-hi line-clamp-2">
                  {p.hook}
                </p>
                {p.scheduled_at && (
                  <p className="mt-1.5 text-xs text-ink-mid">
                    {new Date(p.scheduled_at).toLocaleDateString([], {
                      weekday: "short",
                      month: "short",
                      day: "numeric",
                    })}{" "}
                    · {fmtTime(p.scheduled_at)}
                  </p>
                )}
              </Link>
            ))}
            {!loading && nextUp.length === 0 && (
              <p className="rounded-lg border border-dashed border-border px-3 py-10 text-center text-sm text-ink-lo">
                Nothing scheduled. Approve a draft and pick a time to land it
                here.
              </p>
            )}
          </div>
        </aside>
        </div>
      </div>
    </main>
  );
}

function CalendarBlock({
  post,
  onDragStart,
  onDragEnd,
  onClick,
}: {
  post: Post;
  onDragStart: () => void;
  onDragEnd: () => void;
  onClick: () => void;
}) {
  const platforms = Array.from(new Set(post.targets.map((t) => t.platform)));
  const primary = platforms[0] ?? "linkedin";
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onClick}
      title={post.hook}
      className="flex cursor-grab items-stretch gap-1.5 rounded border border-border bg-surface-2 p-1 text-[11px] active:cursor-grabbing hover:border-ink-lo"
    >
      <span className={"w-1 shrink-0 rounded " + PLATFORM_DOT[primary]} />
      <span className="min-w-0 flex-1">
        <span className="block text-ink-lo">
          {post.scheduled_at ? fmtTime(post.scheduled_at) : ""}
        </span>
        <span className="block truncate text-ink-hi">{post.hook}</span>
      </span>
    </div>
  );
}

export default CalendarPage;
