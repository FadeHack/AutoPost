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
  | "carousel"
  | "dev_tooling"
  | "pricing_business_model"
  | "product_postmortem"
  | "design_thinking";

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
};

const CATEGORY_LABEL: Record<PostCategory, string> = {
  founder_insight: "Founder insight",
  engineering_lesson: "Engineering lesson",
  ai_automation: "AI automation",
  startup_opinion: "Startup opinion",
  technical_humor: "Technical humor",
  carousel: "Carousel",
  dev_tooling: "Dev tooling",
  pricing_business_model: "Pricing & business model",
  product_postmortem: "Product postmortem",
  design_thinking: "Design thinking",
};

const CATEGORY_COLORS: Record<PostCategory, string> = {
  founder_insight: "border-emerald-700 text-emerald-300 bg-emerald-950/30",
  engineering_lesson: "border-sky-700 text-sky-300 bg-sky-950/30",
  ai_automation: "border-violet-700 text-violet-300 bg-violet-950/30",
  startup_opinion: "border-amber-700 text-amber-300 bg-amber-950/30",
  technical_humor: "border-pink-700 text-pink-300 bg-pink-950/30",
  carousel: "border-zinc-700 text-zinc-300 bg-zinc-950/30",
  dev_tooling: "border-teal-700 text-teal-300 bg-teal-950/30",
  pricing_business_model: "border-lime-700 text-lime-300 bg-lime-950/30",
  product_postmortem: "border-rose-700 text-rose-300 bg-rose-950/30",
  design_thinking: "border-fuchsia-700 text-fuchsia-300 bg-fuchsia-950/30",
};

/**
 * Build a public link to the LinkedIn post from the URN LinkedIn handed us.
 * Pass the URN through as-is — substituting `share` → `activity` (numeric id
 * unchanged) is only valid for text and image posts. For document posts the
 * activity URN has a DIFFERENT numeric id than the share, so substitution
 * lands you on a different (or non-existent) post. LinkedIn's
 * `/feed/update/{urn}/` redirects share, ugcPost, and activity URNs to the
 * canonical post URL, so handing it our stored share URN works for every
 * post type. Returns null for unrecognized shapes.
 */
function linkedinUrlFromUrn(urn: string | null): string | null {
  if (!urn) return null;
  if (!/^urn:li:(share|ugcPost|activity):\d+$/.test(urn)) return null;
  return `https://www.linkedin.com/feed/update/${urn}/`;
}

function PublishedPage() {
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
      const data = await apiGet<Post[]>("/posts?status=published&limit=100");
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

  // Most-recent first by published_at. Falls back to created_at if the
  // publisher didn't set published_at for some reason.
  const sorted = useMemo(
    () =>
      [...posts].sort((a, b) => {
        const at = new Date(a.published_at ?? a.created_at).getTime();
        const bt = new Date(b.published_at ?? b.created_at).getTime();
        return bt - at;
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
          <h1 className="text-2xl font-bold tracking-tight">Published</h1>
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
            : `${sorted.length} published post${sorted.length === 1 ? "" : "s"}, most recent first.`}
        </p>

        {error && (
          <div className="rounded border border-red-700 bg-red-950/30 p-3 text-sm font-mono break-all">
            {error}
          </div>
        )}

        <ul className="space-y-3">
          {sorted.map((p) => {
            const liUrl = linkedinUrlFromUrn(p.linkedin_urn);
            return (
              <li key={p.id}>
                <div className="rounded border border-zinc-800 bg-zinc-950/50 p-4 hover:border-zinc-600 transition">
                  <div className="flex items-center gap-2 mb-2 text-xs">
                    <span
                      className={`inline-block rounded border px-2 py-0.5 ${CATEGORY_COLORS[p.category]}`}
                    >
                      {CATEGORY_LABEL[p.category]}
                    </span>
                    <span className="inline-block rounded border border-green-700 text-green-300 bg-green-950/30 px-2 py-0.5">
                      published
                    </span>
                    {p.published_at && (
                      <span className="text-zinc-400">
                        {new Date(p.published_at).toLocaleString()}
                      </span>
                    )}
                  </div>
                  <Link
                    href={`/drafts/${p.id}`}
                    className="block text-sm font-medium leading-snug line-clamp-2 hover:underline"
                  >
                    {p.hook}
                  </Link>
                  <div className="flex items-center gap-3 mt-3 text-xs">
                    {liUrl ? (
                      <a
                        href={liUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-400 hover:underline"
                      >
                        View on LinkedIn →
                      </a>
                    ) : (
                      <span className="text-zinc-500">No LinkedIn link</span>
                    )}
                    {p.linkedin_urn && (
                      <span className="text-zinc-600 font-mono">
                        {p.linkedin_urn}
                      </span>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
          {!loading && sorted.length === 0 && (
            <li className="text-sm text-zinc-500 py-12 text-center">
              Nothing published yet. Drafts ship from{" "}
              <Link href="/scheduled" className="underline">
                /scheduled
              </Link>{" "}
              once the Phase 6 worker is wired.
            </li>
          )}
        </ul>
      </div>
    </main>
  );
}

export default PublishedPage;
