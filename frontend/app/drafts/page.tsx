"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiDelete, apiGet, apiPost } from "@/lib/api";

type PostStatus =
  | "draft"
  | "approved"
  | "scheduled"
  | "publishing"
  | "published"
  | "failed";

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

const STATUS_COLORS: Record<PostStatus, string> = {
  draft: "border-zinc-700 text-zinc-300 bg-zinc-900/50",
  approved: "border-blue-700 text-blue-300 bg-blue-950/30",
  scheduled: "border-indigo-700 text-indigo-300 bg-indigo-950/30",
  publishing: "border-yellow-700 text-yellow-300 bg-yellow-950/30",
  published: "border-green-700 text-green-300 bg-green-950/30",
  failed: "border-red-700 text-red-300 bg-red-950/30",
};

const GENERATABLE: PostCategory[] = [
  "founder_insight",
  "engineering_lesson",
  "ai_automation",
  "startup_opinion",
];

function DraftsPage() {
  const router = useRouter();
  const { session, loading: authLoading, signOut } = useAuth();

  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [statusFilter, setStatusFilter] = useState<PostStatus | "all">("draft");
  const [genCategory, setGenCategory] = useState<PostCategory>("founder_insight");
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");

  useEffect(() => {
    if (!authLoading && !session) router.replace("/login");
  }, [authLoading, session, router]);

  const fetchPosts = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (statusFilter !== "all") params.set("status", statusFilter);
      const data = await apiGet<Post[]>(`/posts?${params.toString()}`);
      setPosts(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [session, statusFilter]);

  useEffect(() => {
    fetchPosts();
  }, [fetchPosts]);

  const deletePost = async (e: React.MouseEvent, p: Post) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`Delete draft "${p.hook.slice(0, 60)}"?`)) return;
    setError("");
    const snapshot = posts;
    setPosts((prev) => prev.filter((x) => x.id !== p.id));
    try {
      await apiDelete(`/posts/${p.id}`);
    } catch (err) {
      setPosts(snapshot);
      setError(err instanceof ApiError ? err.body : (err as Error).message);
    }
  };

  const generate = async () => {
    setGenerating(true);
    setError("");
    setFlash("");
    try {
      const newPost = await apiPost<Post>("/posts/generate", {
        category: genCategory,
      });
      setFlash(`Generated: ${newPost.hook.slice(0, 80)}`);
      await fetchPosts();
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setGenerating(false);
    }
  };

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
          <h1 className="text-2xl font-bold tracking-tight">Drafts</h1>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span className="text-zinc-500">{session.user.email}</span>
          <button onClick={signOut} className="text-zinc-400 hover:text-white">
            Sign out
          </button>
        </div>
      </header>

      <div className="max-w-5xl mx-auto space-y-6">
        <section className="rounded border border-zinc-800 bg-zinc-950/50 p-5">
          <h2 className="text-sm font-semibold mb-3 text-zinc-300">
            Generate a draft
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={genCategory}
              onChange={(e) => setGenCategory(e.target.value as PostCategory)}
              className="rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
            >
              {GENERATABLE.map((c) => (
                <option key={c} value={c}>
                  {CATEGORY_LABEL[c]}
                </option>
              ))}
            </select>
            <button
              onClick={generate}
              disabled={generating}
              className="rounded bg-white text-black font-medium px-4 py-2 text-sm hover:bg-zinc-200 disabled:opacity-50"
            >
              {generating ? "Generating…" : "Generate draft"}
            </button>
            <span className="text-xs text-zinc-500">
              Pulls the top unconsumed trends, runs the 3-stage pipeline (~5–10s).
            </span>
          </div>
        </section>

        <section className="flex flex-wrap items-center gap-3 text-sm">
          <select
            value={statusFilter}
            onChange={(e) =>
              setStatusFilter(e.target.value as PostStatus | "all")
            }
            className="rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
          >
            <option value="draft">Draft</option>
            <option value="approved">Approved</option>
            <option value="scheduled">Scheduled</option>
            <option value="published">Published</option>
            <option value="failed">Failed</option>
            <option value="all">All</option>
          </select>
          <span className="text-zinc-500">
            {loading
              ? "Loading…"
              : `${posts.length} post${posts.length === 1 ? "" : "s"}`}
          </span>
        </section>

        {flash && (
          <div className="rounded border border-green-700 bg-green-950/30 p-3 text-sm font-mono break-words">
            {flash}
          </div>
        )}
        {error && (
          <div className="rounded border border-red-700 bg-red-950/30 p-3 text-sm font-mono break-all">
            {error}
          </div>
        )}

        <ul className="space-y-3">
          {posts.map((p) => (
            <li key={p.id} className="group relative">
              {(p.status === "draft" || p.status === "failed") && (
                <button
                  onClick={(e) => deletePost(e, p)}
                  className="absolute top-3 right-3 z-10 text-xs text-zinc-500 hover:text-red-300 border border-zinc-800 hover:border-red-800 rounded px-2 py-1 opacity-0 group-hover:opacity-100 transition-opacity bg-zinc-950"
                  aria-label="Delete draft"
                  title="Delete draft"
                >
                  ✕
                </button>
              )}
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
                  <span
                    className={`inline-block rounded border px-2 py-0.5 ${STATUS_COLORS[p.status]}`}
                  >
                    {p.status}
                  </span>
                  <span className="text-zinc-600">
                    {new Date(p.created_at).toLocaleString()}
                  </span>
                </div>
                <p className="text-sm font-medium leading-snug line-clamp-2">
                  {p.hook}
                </p>
                {p.tags.length > 0 && (
                  <p className="text-xs text-zinc-500 mt-2">
                    {p.tags.map((t) => `#${t}`).join(" ")}
                  </p>
                )}
              </Link>
            </li>
          ))}
          {!loading && posts.length === 0 && (
            <li className="text-sm text-zinc-500 py-12 text-center">
              No drafts yet. Pick a category above and hit{" "}
              <span className="font-medium text-zinc-300">Generate draft</span>.
            </li>
          )}
        </ul>
      </div>
    </main>
  );
}

export default DraftsPage;
