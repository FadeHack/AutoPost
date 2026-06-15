"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiGet } from "@/lib/api";

type PostCategory =
  | "founder_insight"
  | "engineering_lesson"
  | "ai_automation"
  | "startup_opinion"
  | "technical_humor"
  | "carousel";

type Post = {
  id: string;
  category: PostCategory;
  status: "scheduled";
  hook: string;
  body: string;
  tags: string[];
  scheduled_at: string | null;
  published_at: string | null;
  linkedin_urn: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

const CATEGORY_LABEL: Record<PostCategory, string> = {
  founder_insight: "Founder insight",
  engineering_lesson: "Engineering lesson",
  ai_automation: "AI automation",
  startup_opinion: "Startup opinion",
  technical_humor: "Technical humor",
  carousel: "Carousel",
};

const CATEGORY_COLORS: Record<PostCategory, string> = {
  founder_insight: "border-emerald-700 text-emerald-300 bg-emerald-950/30",
  engineering_lesson: "border-sky-700 text-sky-300 bg-sky-950/30",
  ai_automation: "border-violet-700 text-violet-300 bg-violet-950/30",
  startup_opinion: "border-amber-700 text-amber-300 bg-amber-950/30",
  technical_humor: "border-pink-700 text-pink-300 bg-pink-950/30",
  carousel: "border-zinc-700 text-zinc-300 bg-zinc-950/30",
};

function relativeFromNow(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  if (diff <= 0) return "overdue";
  const mins = Math.round(diff / 60_000);
  if (mins < 60) return `in ${mins} min`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `in ${hrs} hr`;
  const days = Math.round(hrs / 24);
  return `in ${days} day${days === 1 ? "" : "s"}`;
}

function ScheduledPage() {
  const router = useRouter();
  const { session, loading: authLoading, signOut } = useAuth();

  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!authLoading && !session) router.replace("/login");
  }, [authLoading, session, router]);

  const fetchPosts = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const data = await apiGet<Post[]>("/posts?status=scheduled&limit=100");
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

  // Backend orders by created_at desc; we want next-up first.
  const sorted = useMemo(
    () =>
      [...posts].sort((a, b) => {
        const at = a.scheduled_at ? new Date(a.scheduled_at).getTime() : 0;
        const bt = b.scheduled_at ? new Date(b.scheduled_at).getTime() : 0;
        return at - bt;
      }),
    [posts]
  );

  if (authLoading || !session) {
    return <div className="flex-1 p-8 text-zinc-500">Loading…</div>;
  }

  return (
    <main className="flex-1 px-6 py-10">
      <header className="flex justify-between items-center mb-8 max-w-5xl mx-auto">
        <div className="flex items-center gap-6">
          <Link href="/" className="text-sm text-zinc-400 hover:text-white">
            ← Dashboard
          </Link>
          <h1 className="text-2xl font-bold tracking-tight">Scheduled</h1>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span className="text-zinc-500">{session.user.email}</span>
          <button onClick={signOut} className="text-zinc-400 hover:text-white">
            Sign out
          </button>
        </div>
      </header>

      <div className="max-w-5xl mx-auto space-y-4">
        <p className="text-sm text-zinc-500">
          {loading
            ? "Loading…"
            : `${sorted.length} scheduled post${sorted.length === 1 ? "" : "s"}, next-up first.`}
        </p>

        {error && (
          <div className="rounded border border-red-700 bg-red-950/30 p-3 text-sm font-mono break-all">
            {error}
          </div>
        )}

        <ul className="space-y-3">
          {sorted.map((p) => (
            <li key={p.id}>
              <Link
                href={`/drafts/${p.id}`}
                className="block rounded border border-zinc-800 bg-zinc-950/50 p-4 hover:border-zinc-600 transition"
              >
                <div className="flex items-center gap-2 mb-2 text-xs">
                  <span
                    className={`inline-block rounded border px-2 py-0.5 ${CATEGORY_COLORS[p.category]}`}
                  >
                    {CATEGORY_LABEL[p.category]}
                  </span>
                  <span className="inline-block rounded border border-indigo-700 text-indigo-300 bg-indigo-950/30 px-2 py-0.5">
                    scheduled
                  </span>
                  {p.scheduled_at && (
                    <span className="text-zinc-400">
                      {new Date(p.scheduled_at).toLocaleString()}{" "}
                      <span className="text-zinc-500">
                        · {relativeFromNow(p.scheduled_at)}
                      </span>
                    </span>
                  )}
                </div>
                <p className="text-sm font-medium leading-snug line-clamp-2">
                  {p.hook}
                </p>
              </Link>
            </li>
          ))}
          {!loading && sorted.length === 0 && (
            <li className="text-sm text-zinc-500 py-12 text-center">
              Nothing scheduled. Approve a draft and pick a time to land it
              here.
            </li>
          )}
        </ul>
      </div>
    </main>
  );
}

export default ScheduledPage;
