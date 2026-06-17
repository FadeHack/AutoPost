"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import DraftEditor from "@/components/DraftEditor";
import PlatformPreview from "@/components/PlatformPreview";
import SchedulePicker from "@/components/SchedulePicker";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";

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
  | "carousel"
  | "dev_tooling"
  | "pricing_business_model"
  | "product_postmortem"
  | "design_thinking";

type PostExtracts = {
  pull_quote: string | null;
  metric_value: string | null;
  metric_label: string | null;
  carousel_slides: { text: string }[];
};

type Platform = "linkedin" | "bluesky" | "mastodon" | "threads" | "instagram";
type TargetStatus = "pending" | "publishing" | "published" | "failed";

type PostTarget = {
  id: string;
  post_id: string;
  platform: Platform;
  status: TargetStatus;
  scheduled_at: string | null;
  published_at: string | null;
  external_urn: string | null;
  error: string | null;
  // Platform-specific rewritten body, written by the generator at draft-time
  // for non-canonical platforms (currently Bluesky's 300-char compressed
  // variant). NULL = uses Post hook+body+tags.
  commentary: string | null;
  created_at: string;
  updated_at: string;
};

type Post = {
  id: string;
  category: PostCategory;
  status: PostStatus;
  hook: string;
  body: string;
  tags: string[];
  source_trend_ids: string[];
  extracts: PostExtracts | null;
  scheduled_at: string | null;
  published_at: string | null;
  linkedin_urn: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  targets: PostTarget[];
};

const PLATFORM_LABEL: Record<Platform, string> = {
  linkedin: "LinkedIn",
  bluesky: "Bluesky",
  mastodon: "Mastodon",
  threads: "Threads",
  instagram: "Instagram",
};

const TARGET_STATUS_COLORS: Record<TargetStatus, string> = {
  pending: "border-zinc-700 text-zinc-300 bg-zinc-900/50",
  publishing: "border-yellow-700 text-yellow-300 bg-yellow-950/30",
  published: "border-green-700 text-green-300 bg-green-950/30",
  failed: "border-red-700 text-red-300 bg-red-950/30",
};

type TemplateCategory = "quote" | "insight" | "metric" | "carousel";

type Template = {
  id: string;
  name: string;
  category: TemplateCategory;
  html_path: string;
  thumbnail_url: string | null;
};

type PublishingLog = {
  id: string;
  post_id: string;
  attempt: number;
  status: "success" | "failure";
  error: string | null;
  linkedin_response: Record<string, unknown> | null;
  attempted_at: string;
};

type RenderKind = "template" | "ai_image";

type GeneratedAsset = {
  id: string;
  post_id: string;
  template_id: string;
  image_path: string;
  width: number;
  height: number;
  linkedin_asset_urn: string | null;
  render_kind: RenderKind;
  created_at: string;
  image_url: string;
};

// Sentinel value used in the template <select> to mean "use the AI-image
// pipeline" (Flux → brand-wrap composite). Distinct from any real template
// UUID so the render handler can branch on it before sending `template_id`.
const AI_IMAGE_OPTION = "__ai_image__";

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

const STATUS_COLORS: Record<PostStatus, string> = {
  draft: "border-zinc-700 text-zinc-300 bg-zinc-900/50",
  approved: "border-blue-700 text-blue-300 bg-blue-950/30",
  scheduled: "border-indigo-700 text-indigo-300 bg-indigo-950/30",
  publishing: "border-yellow-700 text-yellow-300 bg-yellow-950/30",
  published: "border-green-700 text-green-300 bg-green-950/30",
  failed: "border-red-700 text-red-300 bg-red-950/30",
};

function DraftDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { session, loading: authLoading, signOut } = useAuth();

  const [post, setPost] = useState<Post | null>(null);
  const [assets, setAssets] = useState<GeneratedAsset[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState("");
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState("");
  const [scheduling, setScheduling] = useState(false);
  const [schedulePickerOpen, setSchedulePickerOpen] = useState(false);
  const [scheduleError, setScheduleError] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState("");
  const [retrying, setRetrying] = useState(false);
  const [reversing, setReversing] = useState(false);
  const [reverseError, setReverseError] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [logs, setLogs] = useState<PublishingLog[]>([]);
  const [error, setError] = useState("");
  const [renderError, setRenderError] = useState("");

  useEffect(() => {
    if (!authLoading && !session) router.replace("/login");
  }, [authLoading, session, router]);

  useEffect(() => {
    if (!session || !id) return;
    setLoading(true);
    setError("");
    Promise.all([
      apiGet<Post>(`/posts/${id}`),
      apiGet<GeneratedAsset[]>(`/posts/${id}/assets`),
      apiGet<Template[]>(`/templates`),
    ])
      .then(([p, a, t]) => {
        setPost(p);
        setAssets(a);
        setTemplates(t);
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.body : (e as Error).message)
      )
      .finally(() => setLoading(false));
  }, [session, id]);

  useEffect(() => {
    if (!session || !post) return;
    if (!["failed", "published", "publishing"].includes(post.status)) {
      setLogs([]);
      return;
    }
    apiGet<PublishingLog[]>(`/posts/${post.id}/logs`)
      .then(setLogs)
      .catch(() => setLogs([]));
  }, [session, post]);

  const retryPublish = async () => {
    if (!post) return;
    if (!confirm("Retry publishing this post to LinkedIn?")) return;
    setRetrying(true);
    setPublishError("");
    try {
      const updated = await apiPost<Post>(`/posts/${post.id}/retry`);
      setPost(updated);
    } catch (e) {
      setPublishError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setRetrying(false);
    }
  };

  const saveDraft = useCallback(
    async (updates: { hook: string; body: string; tags: string[] }) => {
      if (!post) return;
      setSaving(true);
      setEditError("");
      try {
        const updated = await apiPatch<Post>(`/posts/${post.id}`, updates);
        setPost(updated);
        setEditing(false);
      } catch (e) {
        setEditError(e instanceof ApiError ? e.body : (e as Error).message);
      } finally {
        setSaving(false);
      }
    },
    [post]
  );

  const cancelEdit = () => {
    setEditing(false);
    setEditError("");
  };

  const approveDraft = async () => {
    if (!post) return;
    if (post.targets.length === 0) {
      setApproveError(
        "Draft has no targets — regenerate with platforms picked at the top of /drafts.",
      );
      return;
    }
    setApproving(true);
    setApproveError("");
    try {
      const updated = await apiPost<Post>(`/posts/${post.id}/approve`, {});
      setPost(updated);
    } catch (e) {
      setApproveError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setApproving(false);
    }
  };

  const schedulePost = async (isoUtc: string) => {
    if (!post) return;
    setScheduling(true);
    setScheduleError("");
    try {
      const updated = await apiPost<Post>(`/posts/${post.id}/schedule`, {
        scheduled_at: isoUtc,
      });
      setPost(updated);
      setSchedulePickerOpen(false);
    } catch (e) {
      setScheduleError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setScheduling(false);
    }
  };

  const publishNow = async () => {
    if (!post) return;
    const targetNames = post.targets
      .map((t) => PLATFORM_LABEL[t.platform])
      .join(", ");
    if (
      !confirm(
        `Publish now to ${targetNames || "every selected platform"}? This goes live immediately and cannot be undone.`,
      )
    ) {
      return;
    }
    setPublishing(true);
    setPublishError("");
    try {
      const updated = await apiPost<Post>(`/posts/${post.id}/publish-now`);
      setPost(updated);
    } catch (e) {
      setPublishError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setPublishing(false);
    }
  };

  const unapprovePost = async () => {
    if (!post) return;
    if (!confirm("Revert this post to draft? Editing will be re-enabled.")) return;
    setReversing(true);
    setReverseError("");
    try {
      const updated = await apiPost<Post>(`/posts/${post.id}/unapprove`);
      setPost(updated);
    } catch (e) {
      setReverseError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setReversing(false);
    }
  };

  const unschedulePost = async () => {
    if (!post) return;
    if (!confirm("Cancel the scheduled publish? The post stays approved.")) return;
    setReversing(true);
    setReverseError("");
    try {
      const updated = await apiPost<Post>(`/posts/${post.id}/unschedule`);
      setPost(updated);
    } catch (e) {
      setReverseError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setReversing(false);
    }
  };

  const deletePost = async () => {
    if (!post) return;
    if (!confirm(`Delete this draft? This cannot be undone.`)) return;
    setDeleting(true);
    setReverseError("");
    try {
      await apiDelete(`/posts/${post.id}`);
      router.push("/drafts");
    } catch (e) {
      setReverseError(e instanceof ApiError ? e.body : (e as Error).message);
      setDeleting(false);
    }
  };

  const generateAnother = async () => {
    if (!post) return;
    setGenerating(true);
    setError("");
    try {
      const newPost = await apiPost<Post>("/posts/generate", {
        category: post.category,
      });
      router.push(`/drafts/${newPost.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
      setGenerating(false);
    }
  };

  const isAIImageRender = selectedTemplateId === AI_IMAGE_OPTION;

  // Carousel posts need every slide rendered as a separate asset so LinkedIn
  // can stitch them into a swipeable feed item. Single-image templates render
  // one asset. Detect which path applies BEFORE the click so the button can
  // adapt its label.
  const isCarouselRender = (() => {
    if (!post) return false;
    if (isAIImageRender) return false; // AI image is always single-asset
    if (selectedTemplateId) {
      const t = templates.find((t) => t.id === selectedTemplateId);
      return t?.name === "carousel_slide";
    }
    // Auto-pick path: backend will pick `carousel_slide` for the `carousel`
    // post category, so dispatch to /render-carousel.
    return post.category === "carousel";
  })();

  const renderVisual = useCallback(async () => {
    if (!post) return;
    setRendering(true);
    setRenderError("");
    try {
      if (isAIImageRender) {
        const asset = await apiPost<GeneratedAsset>(
          `/posts/${id}/render`,
          { kind: "ai_image" }
        );
        setAssets((prev) => [asset, ...prev]);
        return;
      }
      const body = selectedTemplateId
        ? { template_id: selectedTemplateId }
        : {};
      if (isCarouselRender) {
        const newAssets = await apiPost<GeneratedAsset[]>(
          `/posts/${id}/render-carousel`,
          body
        );
        setAssets((prev) => [...newAssets, ...prev]);
      } else {
        const asset = await apiPost<GeneratedAsset>(
          `/posts/${id}/render`,
          body
        );
        setAssets((prev) => [asset, ...prev]);
      }
    } catch (e) {
      setRenderError(
        e instanceof ApiError ? e.body : (e as Error).message
      );
    } finally {
      setRendering(false);
    }
  }, [id, selectedTemplateId, isAIImageRender, isCarouselRender, post]);

  const templateNameById = (tid: string): string =>
    templates.find((t) => t.id === tid)?.name ?? tid.slice(0, 8);

  // The most recent carousel batch — front-of-list cluster of `carousel_slide`
  // assets rendered close together in time. Lives in its own section so we
  // don't bury slides 2..N inside the "earlier renders" expander.
  const currentCarousel = useMemo<GeneratedAsset[]>(() => {
    if (assets.length === 0) return [];
    const carouselTpl = templates.find((t) => t.name === "carousel_slide");
    if (!carouselTpl) return [];
    const isC = (a: GeneratedAsset) => a.template_id === carouselTpl.id;
    if (!isC(assets[0])) return [];
    const batch: GeneratedAsset[] = [assets[0]];
    for (let i = 1; i < assets.length; i++) {
      const a = assets[i];
      if (!isC(a)) break;
      // Carousel batches are rendered atomically (~1-2s per slide). A 60s
      // gap reliably distinguishes "same batch" from "user clicked Render
      // again later." Conservative cap.
      const prev = new Date(batch[batch.length - 1].created_at).getTime();
      const cur = new Date(a.created_at).getTime();
      if (Math.abs(prev - cur) > 60_000) break;
      batch.push(a);
    }
    return batch.length > 1 ? batch : [];
  }, [assets, templates]);

  const latest = assets[0];
  // "earlier renders" starts AFTER the current carousel batch so we don't
  // double-list slides 2..N. Falls back to slice(1) when no carousel batch.
  const older = assets.slice(currentCarousel.length || 1);

  if (authLoading || !session) {
    return <div className="flex-1 p-8 text-zinc-500">Loading…</div>;
  }

  return (
    <main className="flex-1 px-6 py-10">
      <header className="flex justify-between items-center mb-8 max-w-3xl mx-auto">
        <div className="flex items-center gap-6">
          <Link
            href="/drafts"
            className="text-sm text-zinc-400 hover:text-white"
          >
            ← Drafts
          </Link>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span className="text-zinc-500">{session.user.email}</span>
          <button onClick={signOut} className="text-zinc-400 hover:text-white">
            Sign out
          </button>
        </div>
      </header>

      <div className="max-w-3xl mx-auto space-y-6">
        {loading && <p className="text-sm text-zinc-500">Loading draft…</p>}
        {error && (
          <div className="rounded border border-red-700 bg-red-950/30 p-3 text-sm font-mono break-all">
            {error}
          </div>
        )}

        {post && (
          <>
            <div className="flex items-center gap-2 text-xs">
              <span
                className={`inline-block rounded border px-2 py-0.5 ${CATEGORY_COLORS[post.category]}`}
              >
                {CATEGORY_LABEL[post.category]}
              </span>
              <span
                className={`inline-block rounded border px-2 py-0.5 ${STATUS_COLORS[post.status]}`}
              >
                {post.status}
              </span>
              <span className="text-zinc-600">
                Created {new Date(post.created_at).toLocaleString()}
              </span>
            </div>

            <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6">
              <h2 className="text-xs uppercase tracking-wider text-zinc-500 mb-4">
                Visual
              </h2>
              <div className="flex flex-col sm:flex-row gap-6">
                <div className="w-full sm:w-72 flex-shrink-0">
                  {latest ? (
                    // Plain <img> — cross-origin backend asset; no Next.js Image config needed.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={latest.image_url}
                      alt={`Rendered visual for ${post.hook.slice(0, 60)}`}
                      width={288}
                      height={288}
                      className="block w-full aspect-square rounded border border-zinc-800 bg-black"
                    />
                  ) : (
                    <div className="w-full aspect-square rounded border border-dashed border-zinc-800 bg-zinc-950 flex items-center justify-center text-xs text-zinc-600 text-center px-4">
                      No image yet. Pick a template and hit Render.
                    </div>
                  )}
                </div>
                <div className="flex-1 flex flex-col gap-3">
                  <label className="text-xs uppercase tracking-wider text-zinc-500">
                    Template
                  </label>
                  <select
                    value={selectedTemplateId}
                    onChange={(e) => setSelectedTemplateId(e.target.value)}
                    className="rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
                  >
                    <option value="">Auto for category</option>
                    <option value={AI_IMAGE_OPTION}>
                      ✦ AI image (Flux)
                    </option>
                    {templates
                      .filter((t) => t.name !== "ai_image_wrap")
                      .map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name} ({t.category})
                        </option>
                      ))}
                  </select>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={renderVisual}
                      disabled={rendering}
                      className="rounded bg-white text-black font-medium px-4 py-2 text-sm hover:bg-zinc-200 disabled:opacity-50"
                    >
                      {rendering
                        ? isAIImageRender
                          ? "Generating AI image…"
                          : isCarouselRender
                            ? `Rendering ${post.extracts?.carousel_slides?.length ?? "all"} slides…`
                            : "Rendering…"
                        : isAIImageRender
                          ? latest
                            ? "Re-generate AI image"
                            : "Generate AI image"
                          : isCarouselRender
                            ? latest
                              ? `Re-render carousel (${post.extracts?.carousel_slides?.length ?? "?"} slides)`
                              : `Render carousel (${post.extracts?.carousel_slides?.length ?? "?"} slides)`
                            : latest
                              ? "Re-render"
                              : "Render"}
                    </button>
                    {latest && (
                      <a
                        href={latest.image_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-zinc-400 hover:text-white"
                      >
                        Open full size →
                      </a>
                    )}
                  </div>
                  {latest && (
                    <p className="text-xs text-zinc-500">
                      {latest.render_kind === "ai_image" && (
                        <span className="mr-1 inline-block rounded border border-violet-700 bg-violet-950/30 text-violet-300 px-1.5 py-0.5 text-[10px] uppercase tracking-wider">
                          AI image
                        </span>
                      )}
                      {templateNameById(latest.template_id)} · {latest.width}×
                      {latest.height} ·{" "}
                      {new Date(latest.created_at).toLocaleString()}
                    </p>
                  )}
                  {renderError && (
                    <p className="text-xs font-mono text-red-400 break-all">
                      {renderError}
                    </p>
                  )}
                </div>
              </div>
              {currentCarousel.length > 1 && (
                <div className="mt-6 pt-5 border-t border-zinc-800">
                  <h3 className="text-xs uppercase tracking-wider text-zinc-500 mb-3">
                    Carousel slides ({currentCarousel.length})
                  </h3>
                  <ul className="grid grid-cols-3 sm:grid-cols-5 gap-3">
                    {currentCarousel.map((a, idx) => (
                      <li key={a.id}>
                        <a
                          href={a.image_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={`Slide ${idx + 1} of ${currentCarousel.length}`}
                          className="block"
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={a.image_url}
                            alt={`Slide ${idx + 1}`}
                            className="block w-full aspect-square rounded border border-zinc-800 bg-black hover:border-zinc-600"
                          />
                          <p className="text-[10px] text-zinc-500 text-center mt-1 tracking-wider">
                            {idx + 1} / {currentCarousel.length}
                          </p>
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {older.length > 0 && (
                <details className="mt-5 pt-4 border-t border-zinc-800">
                  <summary className="text-xs text-zinc-500 cursor-pointer hover:text-zinc-300">
                    {older.length} earlier render
                    {older.length === 1 ? "" : "s"}
                  </summary>
                  <ul className="grid grid-cols-3 sm:grid-cols-5 gap-2 mt-3">
                    {older.map((a) => (
                      <li key={a.id} className="relative">
                        <a
                          href={a.image_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={`${a.render_kind === "ai_image" ? "AI image · " : ""}${templateNameById(a.template_id)} · ${new Date(a.created_at).toLocaleString()}`}
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={a.image_url}
                            alt=""
                            className="block w-full aspect-square rounded border border-zinc-800 bg-black hover:border-zinc-600"
                          />
                          {a.render_kind === "ai_image" && (
                            <span className="absolute top-1 right-1 rounded border border-violet-700 bg-black/70 text-violet-300 px-1 py-0.5 text-[9px] uppercase tracking-wider">
                              AI
                            </span>
                          )}
                        </a>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </section>

            <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6">
              <h2 className="text-xs uppercase tracking-wider text-zinc-500 mb-4">
                Preview
              </h2>
              <PlatformPreview
                hook={post.hook}
                body={post.body}
                tags={post.tags}
                imageUrl={latest?.image_url ?? null}
                carousel={
                  currentCarousel.length > 1
                    ? currentCarousel.map((a) => ({ url: a.image_url }))
                    : null
                }
                targets={post.targets.map((t) => ({
                  platform: t.platform,
                  commentary: t.commentary,
                }))}
                authorName={session.user.email?.split("@")[0] ?? "You"}
              />
            </section>

            {editing ? (
              <>
                {editError && (
                  <div className="rounded border border-red-700 bg-red-950/30 p-3 text-sm font-mono break-all">
                    {editError}
                  </div>
                )}
                <DraftEditor
                  initialHook={post.hook}
                  initialBody={post.body}
                  initialTags={post.tags}
                  saving={saving}
                  onSave={saveDraft}
                  onCancel={cancelEdit}
                />
              </>
            ) : (
              <>
                <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6">
                  <h2 className="text-xs uppercase tracking-wider text-zinc-500 mb-3">
                    Hook
                  </h2>
                  <p className="text-base font-medium leading-snug">
                    {post.hook}
                  </p>
                </section>

                <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6">
                  <h2 className="text-xs uppercase tracking-wider text-zinc-500 mb-3">
                    Body
                  </h2>
                  <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                    {post.body}
                  </pre>
                  {post.tags.length > 0 && (
                    <p className="text-xs text-zinc-500 mt-4 pt-4 border-t border-zinc-800">
                      {post.tags.map((t) => `#${t}`).join(" ")}
                    </p>
                  )}
                </section>
              </>
            )}

            {(post.status === "failed" ||
              post.targets.some((t) => t.status === "failed")) && (
              <section className="rounded border border-red-700 bg-red-950/40 p-5 space-y-3">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 className="text-sm font-semibold text-red-200">
                      {post.status === "failed"
                        ? "Publish failed"
                        : "One or more targets failed"}
                    </h3>
                    {/* Per-target errors first; they're the source of truth.
                        Fall back to post.error for legacy rows. */}
                    {post.targets.filter((t) => t.status === "failed").length > 0 ? (
                      <ul className="text-xs text-red-300 mt-1 space-y-1">
                        {post.targets
                          .filter((t) => t.status === "failed")
                          .map((t) => (
                            <li key={t.id} className="font-mono break-all">
                              <span className="font-semibold not-italic">
                                {PLATFORM_LABEL[t.platform]}:
                              </span>{" "}
                              {t.error ?? "(no error message recorded)"}
                            </li>
                          ))}
                      </ul>
                    ) : (
                      <p className="text-xs text-red-300 mt-1 font-mono break-all">
                        {post.error ?? "(no error message recorded)"}
                      </p>
                    )}
                  </div>
                  <button
                    onClick={retryPublish}
                    disabled={retrying}
                    className="shrink-0 rounded bg-red-600 text-white font-medium px-4 py-2 text-sm hover:bg-red-500 disabled:opacity-50"
                  >
                    {retrying ? "Retrying…" : "Retry publish"}
                  </button>
                </div>
                {logs.length > 0 && (
                  <details className="pt-3 border-t border-red-900/60">
                    <summary className="text-xs text-red-300 cursor-pointer hover:text-red-100">
                      Attempt history ({logs.length})
                    </summary>
                    <ul className="mt-3 space-y-2">
                      {logs.map((l) => (
                        <li
                          key={l.id}
                          className="rounded border border-zinc-800 bg-zinc-950 p-3 text-xs"
                        >
                          <div className="flex justify-between text-zinc-400">
                            <span>
                              Attempt {l.attempt} ·{" "}
                              <span
                                className={
                                  l.status === "success"
                                    ? "text-green-400"
                                    : "text-red-400"
                                }
                              >
                                {l.status}
                              </span>
                            </span>
                            <span>
                              {new Date(l.attempted_at).toLocaleString()}
                            </span>
                          </div>
                          {l.error && (
                            <p className="font-mono text-red-300 mt-2 break-all">
                              {l.error}
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </section>
            )}

            <section className="rounded border border-zinc-800 bg-zinc-950/50 p-5 text-xs text-zinc-500 space-y-1">
              <p>
                Source trends:{" "}
                <span className="font-mono">
                  {post.source_trend_ids.length}
                </span>
              </p>
              <p>
                Post ID: <span className="font-mono">{post.id}</span>
              </p>
              {post.linkedin_urn && (
                <p>
                  LinkedIn URN:{" "}
                  <span className="font-mono">{post.linkedin_urn}</span>
                </p>
              )}
            </section>

            {!editing && (
              <div className="space-y-3 pt-2">
                {post.targets.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="text-zinc-500">Targets:</span>
                    {post.targets.map((t) => (
                      <span
                        key={t.id}
                        title={
                          t.error
                            ? `${PLATFORM_LABEL[t.platform]}: ${t.error}`
                            : t.external_urn
                              ? `${PLATFORM_LABEL[t.platform]}: ${t.external_urn}`
                              : `${PLATFORM_LABEL[t.platform]}: ${t.status}`
                        }
                        className={
                          "rounded border px-2 py-0.5 " +
                          TARGET_STATUS_COLORS[t.status]
                        }
                      >
                        {PLATFORM_LABEL[t.platform]} · {t.status}
                      </span>
                    ))}
                  </div>
                )}
                {post.status === "draft" && post.targets.length > 0 && (
                  <div className="rounded border border-zinc-800 bg-zinc-950/50 p-3 space-y-2">
                    <p className="text-xs text-zinc-400">
                      Platforms were picked at generate time. Each
                      non-LinkedIn target carries its own platform-shaped
                      rewrite — preview it by expanding the target below.
                    </p>
                    <div className="flex flex-wrap gap-2 text-xs">
                      {post.targets.map((t) => (
                        <span
                          key={t.id}
                          className="rounded border border-zinc-700 px-2 py-0.5 text-zinc-300"
                        >
                          {PLATFORM_LABEL[t.platform]}
                          {t.commentary && (
                            <span className="text-zinc-500 ml-1">
                              · {t.commentary.length} chars
                            </span>
                          )}
                        </span>
                      ))}
                    </div>
                    <details className="text-xs text-zinc-400">
                      <summary className="cursor-pointer text-zinc-500 hover:text-white">
                        Show per-platform commentary
                      </summary>
                      <div className="mt-2 space-y-2">
                        {post.targets.map((t) => (
                          <div
                            key={t.id}
                            className="rounded border border-zinc-800 bg-zinc-900/50 p-2"
                          >
                            <div className="text-zinc-500 mb-1">
                              {PLATFORM_LABEL[t.platform]}
                              {t.commentary === null && (
                                <span className="ml-2">
                                  (uses the canonical hook + body above)
                                </span>
                              )}
                            </div>
                            {t.commentary && (
                              <pre className="whitespace-pre-wrap text-zinc-200 font-sans">
                                {t.commentary}
                              </pre>
                            )}
                          </div>
                        ))}
                      </div>
                    </details>
                  </div>
                )}
                {post.scheduled_at && post.status === "scheduled" && (
                  <div className="rounded border border-indigo-700 bg-indigo-950/30 p-3 text-sm">
                    Scheduled for{" "}
                    <span className="font-medium">
                      {new Date(post.scheduled_at).toLocaleString()}
                    </span>
                    .
                    <span className="text-xs text-zinc-400 ml-2">
                      The scheduler will fan out to each target at this time.
                    </span>
                  </div>
                )}
                {approveError && (
                  <div className="rounded border border-red-700 bg-red-950/30 p-3 text-sm font-mono break-all">
                    {approveError}
                  </div>
                )}
                {scheduleError && (
                  <div className="rounded border border-red-700 bg-red-950/30 p-3 text-sm font-mono break-all">
                    {scheduleError}
                  </div>
                )}
                {publishError && (
                  <div className="rounded border border-red-700 bg-red-950/30 p-3 text-sm font-mono break-all">
                    {publishError}
                  </div>
                )}
                {reverseError && (
                  <div className="rounded border border-red-700 bg-red-950/30 p-3 text-sm font-mono break-all">
                    {reverseError}
                  </div>
                )}
                {schedulePickerOpen && (
                  <SchedulePicker
                    initialScheduledAt={post.scheduled_at}
                    scheduling={scheduling}
                    onSchedule={schedulePost}
                    onCancel={() => {
                      setSchedulePickerOpen(false);
                      setScheduleError("");
                    }}
                  />
                )}
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    onClick={() => setEditing(true)}
                    disabled={post.status !== "draft"}
                    title={
                      post.status === "draft"
                        ? "Edit hook, body, and tags"
                        : `Locked: post is ${post.status}. Only drafts are editable.`
                    }
                    className="rounded border border-zinc-700 text-zinc-200 px-4 py-2 text-sm hover:border-zinc-500 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Edit
                  </button>
                  <button
                    onClick={approveDraft}
                    disabled={post.status !== "draft" || approving}
                    title={
                      post.status === "draft"
                        ? "Mark this draft as approved (locks editing)"
                        : post.status === "approved"
                          ? "Already approved"
                          : `Cannot approve a post in status '${post.status}'`
                    }
                    className="rounded bg-blue-600 text-white font-medium px-4 py-2 text-sm hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {approving
                      ? "Approving…"
                      : post.status === "draft"
                        ? "Approve"
                        : post.status === "approved"
                          ? "Approved ✓"
                          : "Approve"}
                  </button>
                  <button
                    onClick={() => setSchedulePickerOpen((v) => !v)}
                    disabled={
                      post.status !== "approved" && post.status !== "scheduled"
                    }
                    title={
                      post.status === "approved"
                        ? "Pick a future time to publish"
                        : post.status === "scheduled"
                          ? "Change the scheduled time"
                          : `Approve the post first (status: ${post.status})`
                    }
                    className="rounded bg-indigo-600 text-white font-medium px-4 py-2 text-sm hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {post.status === "scheduled" ? "Reschedule" : "Schedule"}
                  </button>
                  <button
                    onClick={publishNow}
                    disabled={
                      publishing ||
                      (post.status !== "approved" && post.status !== "scheduled")
                    }
                    title={
                      post.status === "approved" || post.status === "scheduled"
                        ? "Publish to LinkedIn right now"
                        : `Approve the post first (status: ${post.status})`
                    }
                    className="rounded bg-emerald-600 text-white font-medium px-4 py-2 text-sm hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {publishing ? "Publishing…" : "Publish now"}
                  </button>
                  <button
                    onClick={generateAnother}
                    disabled={generating}
                    className="rounded border border-zinc-700 text-zinc-200 px-4 py-2 text-sm hover:border-zinc-500 disabled:opacity-50"
                  >
                    {generating ? "Generating…" : "Generate another"}
                  </button>
                  {post.status === "scheduled" && (
                    <button
                      onClick={unschedulePost}
                      disabled={reversing}
                      title="Cancel the pending scheduler job and return to approved"
                      className="rounded border border-amber-700 text-amber-200 px-4 py-2 text-sm hover:bg-amber-950/40 disabled:opacity-50"
                    >
                      {reversing ? "Cancelling…" : "Cancel schedule"}
                    </button>
                  )}
                  {post.status === "approved" && (
                    <button
                      onClick={unapprovePost}
                      disabled={reversing}
                      title="Reopen this post for editing"
                      className="rounded border border-amber-700 text-amber-200 px-4 py-2 text-sm hover:bg-amber-950/40 disabled:opacity-50"
                    >
                      {reversing ? "Reverting…" : "Revert to draft"}
                    </button>
                  )}
                  {(post.status === "draft" || post.status === "failed") && (
                    <button
                      onClick={deletePost}
                      disabled={deleting}
                      title="Permanently delete this draft"
                      className="rounded border border-red-800 text-red-300 px-4 py-2 text-sm hover:bg-red-950/40 disabled:opacity-50 ml-auto"
                    >
                      {deleting ? "Deleting…" : "Delete draft"}
                    </button>
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}

export default DraftDetailPage;
