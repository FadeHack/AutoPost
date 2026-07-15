"use client";

import {
  use,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import PlatformPreview from "@/components/PlatformPreview";
import SchedulePicker from "@/components/SchedulePicker";
import { HighlightField } from "@/components/cockpit/HighlightField";
import { StatusPill } from "@/components/ui/StatusPill";
import { CategoryChip } from "@/components/ui/CategoryChip";
import { PlatformBadge } from "@/components/ui/PlatformBadge";
import { Banner } from "@/components/ui/Banner";
import { ActionBar, ActionButton } from "@/components/ui/ActionBar";
import { VoiceQualityChip } from "@/components/ui/VoiceQualityChip";
import { useToast } from "@/components/ui/Toast";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiUpload } from "@/lib/api";
import { scanVoiceTells } from "@/lib/voice";
import {
  PLATFORM_LABEL,
  type Platform,
  type PostCategory,
  type PostStatus,
} from "@/lib/domain";

type TargetStatus =
  | "pending"
  | "publishing"
  | "published"
  | "failed"
  | "skipped";

type PostExtracts = {
  pull_quote: string | null;
  metric_value: string | null;
  metric_label: string | null;
  carousel_slides: { text: string }[];
};

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

type RenderKind = "template" | "ai_image" | "upload";

// How much brand chrome wraps an AI image: full brand card, full-bleed with a
// small corner mark, or full-bleed with no chrome. Mirrors RenderRequest.frame.
type AIImageFrame = "card" | "mark" | "none";

const AI_IMAGE_FRAMES: { value: AIImageFrame; label: string }[] = [
  { value: "card", label: "Brand card" },
  { value: "mark", label: "Brand mark" },
  { value: "none", label: "Full bleed" },
];

type GeneratedAsset = {
  id: string;
  post_id: string;
  template_id: string | null;
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

const TARGET_STATUS_TONE: Record<TargetStatus, string> = {
  pending: "text-ink-mid",
  publishing: "text-status-publishing",
  published: "text-status-published",
  failed: "text-status-failed",
  skipped: "text-ink-lo",
};

type Working = { hook: string; body: string; tags: string[] };

function arrayEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

// Slugify a hook into a safe, short filename stem.
function fileSlug(hook: string): string {
  const s = hook
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return s || "post";
}

// Force a real download of a cross-origin image. The plain <a download> attr is
// ignored for cross-origin URLs (our assets live on the public Supabase CDN), so
// we fetch the bytes into a blob and save that. Used for manual pasting into
// platforms we don't publish to via API (e.g. X when not connected).
async function downloadImage(url: string, filename: string): Promise<void> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`download failed: ${res.status}`);
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

function DraftDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { session, loading: authLoading } = useAuth();
  const { notify } = useToast();

  const [post, setPost] = useState<Post | null>(null);
  const [working, setWorking] = useState<Working>({
    hook: "",
    body: "",
    tags: [],
  });
  const [tagDraft, setTagDraft] = useState("");
  const [assets, setAssets] = useState<GeneratedAsset[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
  // Only used for the AI-image path: how much brand chrome wraps the Flux
  // image. 'card' = full brand card, 'mark' = full-bleed + corner mark,
  // 'none' = full-bleed no chrome.
  const [frame, setFrame] = useState<AIImageFrame>("card");
  const [pane, setPane] = useState<"editor" | "preview">("preview");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [uploading, setUploading] = useState(false);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);
  const [scheduling, setScheduling] = useState(false);
  const [schedulePickerOpen, setSchedulePickerOpen] = useState(false);
  const schedulePickerRef = useRef<HTMLDivElement>(null);
  const [publishing, setPublishing] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [reversing, setReversing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [logs, setLogs] = useState<PublishingLog[]>([]);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [renderError, setRenderError] = useState("");

  // Sync the editable working copy whenever a fresh post lands (load or any
  // mutation that returns the updated row).
  const applyPost = useCallback((p: Post) => {
    setPost(p);
    setWorking({ hook: p.hook, body: p.body, tags: p.tags });
  }, []);

  useEffect(() => {
    if (!authLoading && !session) router.replace("/login");
  }, [authLoading, session, router]);

  // The schedule picker opens above the sticky ActionBar, so without this it
  // can land off-screen and the Schedule click looks like a no-op. Bring it
  // into view when it opens.
  useEffect(() => {
    if (schedulePickerOpen) {
      schedulePickerRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }
  }, [schedulePickerOpen]);

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
        applyPost(p);
        setAssets(a);
        setTemplates(t);
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.body : (e as Error).message),
      )
      .finally(() => setLoading(false));
  }, [session, id, applyPost]);

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

  const isDraft = post?.status === "draft";

  const dirty = useMemo(
    () =>
      !!post &&
      (working.hook !== post.hook ||
        working.body !== post.body ||
        !arrayEqual(working.tags, post.tags)),
    [post, working],
  );

  const canSave =
    isDraft &&
    dirty &&
    !saving &&
    working.hook.trim().length > 0 &&
    working.body.trim().length > 0;

  // Live founder-voice scan over the working copy — the count feeds the chip,
  // the underlines come from HighlightField scanning the same text.
  const voiceScan = useMemo(
    () => scanVoiceTells(`${working.hook}\n\n${working.body}`),
    [working.hook, working.body],
  );

  const setHook = (hook: string) => setWorking((w) => ({ ...w, hook }));
  const setBody = (body: string) => setWorking((w) => ({ ...w, body }));

  const addTag = (raw: string) => {
    const cleaned = raw.trim().replace(/^#+/, "").toLowerCase();
    if (!cleaned) return;
    setWorking((w) =>
      w.tags.includes(cleaned) ? w : { ...w, tags: [...w.tags, cleaned] },
    );
    setTagDraft("");
  };
  const removeTag = (t: string) =>
    setWorking((w) => ({ ...w, tags: w.tags.filter((x) => x !== t) }));
  const onTagKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(tagDraft);
    } else if (e.key === "Backspace" && tagDraft === "" && working.tags.length) {
      e.preventDefault();
      setWorking((w) => ({ ...w, tags: w.tags.slice(0, -1) }));
    }
  };

  const saveDraft = async () => {
    if (!post || !canSave) return;
    setSaving(true);
    setActionError("");
    try {
      const updated = await apiPatch<Post>(`/posts/${post.id}`, {
        hook: working.hook.trim(),
        body: working.body.trim(),
        tags: working.tags,
      });
      applyPost(updated);
      notify({ tone: "success", title: "Draft saved" });
    } catch (e) {
      setActionError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const revertEdits = () => {
    if (!post) return;
    setWorking({ hook: post.hook, body: post.body, tags: post.tags });
    setActionError("");
  };

  const approveDraft = async () => {
    if (!post) return;
    if (post.targets.length === 0) {
      setActionError(
        "Draft has no targets — regenerate with platforms picked at the top of /drafts.",
      );
      return;
    }
    if (dirty && !confirm("You have unsaved edits. Approve without saving them?"))
      return;
    setApproving(true);
    setActionError("");
    try {
      const updated = await apiPost<Post>(`/posts/${post.id}/approve`, {});
      applyPost(updated);
      notify({ tone: "success", title: "Approved", body: "Ready to schedule or publish." });
    } catch (e) {
      setActionError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setApproving(false);
    }
  };

  const schedulePost = async (isoUtc: string) => {
    if (!post) return;
    setScheduling(true);
    setActionError("");
    try {
      const updated = await apiPost<Post>(`/posts/${post.id}/schedule`, {
        scheduled_at: isoUtc,
      });
      applyPost(updated);
      setSchedulePickerOpen(false);
      notify({ tone: "success", title: "Scheduled" });
    } catch (e) {
      setActionError(e instanceof ApiError ? e.body : (e as Error).message);
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
    )
      return;
    setPublishing(true);
    setActionError("");
    try {
      const updated = await apiPost<Post>(`/posts/${post.id}/publish-now`);
      applyPost(updated);
      notify({
        tone: updated.status === "published" ? "success" : "warn",
        title:
          updated.status === "published" ? "Published" : "Publish finished",
        body: `Status: ${updated.status}`,
      });
    } catch (e) {
      setActionError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setPublishing(false);
    }
  };

  const retryPublish = async () => {
    if (!post) return;
    if (!confirm("Retry publishing this post?")) return;
    setRetrying(true);
    setActionError("");
    try {
      const updated = await apiPost<Post>(`/posts/${post.id}/retry`);
      applyPost(updated);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setRetrying(false);
    }
  };

  const unapprovePost = async () => {
    if (!post) return;
    if (!confirm("Revert this post to draft? Editing will be re-enabled.")) return;
    setReversing(true);
    setActionError("");
    try {
      const updated = await apiPost<Post>(`/posts/${post.id}/unapprove`);
      applyPost(updated);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setReversing(false);
    }
  };

  const unschedulePost = async () => {
    if (!post) return;
    if (!confirm("Cancel the scheduled publish? The post stays approved.")) return;
    setReversing(true);
    setActionError("");
    try {
      const updated = await apiPost<Post>(`/posts/${post.id}/unschedule`);
      applyPost(updated);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setReversing(false);
    }
  };

  const deletePost = async () => {
    if (!post) return;
    if (!confirm("Delete this draft? This cannot be undone.")) return;
    setDeleting(true);
    setActionError("");
    try {
      await apiDelete(`/posts/${post.id}`);
      router.push("/drafts");
    } catch (e) {
      setActionError(e instanceof ApiError ? e.body : (e as Error).message);
      setDeleting(false);
    }
  };

  const generateAnother = async () => {
    if (!post) return;
    setGenerating(true);
    setActionError("");
    try {
      const newPost = await apiPost<Post>("/posts/generate", {
        category: post.category,
      });
      router.push(`/drafts/${newPost.id}`);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.body : (e as Error).message);
      setGenerating(false);
    }
  };

  const isAIImageRender = selectedTemplateId === AI_IMAGE_OPTION;

  // Carousel posts render every slide as its own asset (LinkedIn stitches them
  // into a swipeable item); single-image templates render one. Detect before
  // the click so the button label can adapt.
  const isCarouselRender = (() => {
    if (!post) return false;
    if (isAIImageRender) return false;
    if (selectedTemplateId) {
      const t = templates.find((t) => t.id === selectedTemplateId);
      return t?.name === "carousel_slide";
    }
    return post.category === "carousel";
  })();

  const renderVisual = useCallback(async () => {
    if (!post) return;
    setRendering(true);
    setRenderError("");
    try {
      if (isAIImageRender) {
        const asset = await apiPost<GeneratedAsset>(`/posts/${id}/render`, {
          kind: "ai_image",
          frame,
        });
        setAssets((prev) => [asset, ...prev]);
        return;
      }
      const body = selectedTemplateId
        ? { template_id: selectedTemplateId }
        : {};
      if (isCarouselRender) {
        const newAssets = await apiPost<GeneratedAsset[]>(
          `/posts/${id}/render-carousel`,
          body,
        );
        setAssets((prev) => [...newAssets, ...prev]);
      } else {
        const asset = await apiPost<GeneratedAsset>(`/posts/${id}/render`, body);
        setAssets((prev) => [asset, ...prev]);
      }
    } catch (e) {
      setRenderError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setRendering(false);
    }
  }, [id, selectedTemplateId, isAIImageRender, isCarouselRender, frame, post]);

  // Custom-image upload: raw passthrough — the file becomes the newest asset
  // and publishes exactly as uploaded (no template, no render).
  const uploadCustomImage = useCallback(
    async (file: File) => {
      setUploading(true);
      setRenderError("");
      try {
        const form = new FormData();
        form.append("file", file);
        const asset = await apiUpload<GeneratedAsset>(
          `/posts/${id}/upload-image`,
          form,
        );
        setAssets((prev) => [asset, ...prev]);
      } catch (e) {
        setRenderError(e instanceof ApiError ? e.body : (e as Error).message);
      } finally {
        setUploading(false);
        if (uploadInputRef.current) uploadInputRef.current.value = "";
      }
    },
    [id],
  );

  const templateNameById = (tid: string | null): string =>
    tid === null
      ? "Uploaded image"
      : (templates.find((t) => t.id === tid)?.name ?? tid.slice(0, 8));

  // Save a rendered asset to disk for manual pasting (e.g. into X when we don't
  // publish via API). Filename = brand + hook slug + optional slide index.
  const downloadAsset = async (asset: GeneratedAsset, slide?: number) => {
    const ext = asset.image_path.toLowerCase().endsWith(".jpg") ? "jpg" : "png";
    const stem = fileSlug(post?.hook ?? "post");
    const name = slide ? `${stem}-slide-${slide}.${ext}` : `${stem}.${ext}`;
    try {
      await downloadImage(asset.image_url, `nestwhirr-${name}`);
    } catch {
      notify({ tone: "error", title: "Download failed", body: "Try 'full size' and save manually." });
    }
  };

  // The most recent carousel batch — front-of-list cluster of `carousel_slide`
  // assets rendered close together in time.
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
      const prev = new Date(batch[batch.length - 1].created_at).getTime();
      const cur = new Date(a.created_at).getTime();
      if (Math.abs(prev - cur) > 60_000) break;
      batch.push(a);
    }
    return batch.length > 1 ? batch : [];
  }, [assets, templates]);

  const latest = assets[0];
  const older = assets.slice(currentCarousel.length || 1);

  const failedTargets = post?.targets.filter((t) => t.status === "failed") ?? [];
  const showFailedPanel =
    !!post && (post.status === "failed" || failedTargets.length > 0);

  if (authLoading || !session) {
    return <main className="flex-1 p-8 text-ink-lo">Loading…</main>;
  }

  // ── Panes ────────────────────────────────────────────────────────────────

  const editorPane = post && (
    <section className="order-2 space-y-5 border-border p-5 md:order-none lg:border-r">
      <div className="flex items-center justify-between">
        <h2 className="text-xs uppercase tracking-wider text-ink-lo">Editor</h2>
        <VoiceQualityChip violations={voiceScan.count} />
      </div>

      <div className="space-y-2">
        <label className="block text-xs uppercase tracking-wider text-ink-lo">
          Hook
        </label>
        <HighlightField
          value={working.hook}
          onChange={setHook}
          editable={!!isDraft}
          serif
          minRows={2}
          maxLength={512}
          ariaLabel="Hook"
          placeholder="The first line that has to work alone…"
        />
        {isDraft && (
          <p className="text-right text-[11px] text-ink-lo">
            {working.hook.length} / 512
          </p>
        )}
      </div>

      <div className="space-y-2">
        <label className="block text-xs uppercase tracking-wider text-ink-lo">
          Body
        </label>
        <HighlightField
          value={working.body}
          onChange={setBody}
          editable={!!isDraft}
          minRows={8}
          ariaLabel="Body"
          placeholder="Short lines. One opinion. No closing summary."
        />
      </div>

      <div className="space-y-2">
        <label className="block text-xs uppercase tracking-wider text-ink-lo">
          Tags
        </label>
        {isDraft ? (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface-2 px-2 py-2 focus-within:border-ink-lo">
            {working.tags.map((t) => (
              <span
                key={t}
                className="inline-flex items-center gap-1 rounded bg-surface-1 px-2 py-0.5 text-xs text-ink-mid"
              >
                #{t}
                <button
                  type="button"
                  onClick={() => removeTag(t)}
                  aria-label={`Remove tag ${t}`}
                  className="text-ink-lo hover:text-ink-hi"
                >
                  ×
                </button>
              </span>
            ))}
            <input
              value={tagDraft}
              onChange={(e) => setTagDraft(e.target.value)}
              onKeyDown={onTagKeyDown}
              onBlur={() => addTag(tagDraft)}
              placeholder={working.tags.length === 0 ? "add a tag, Enter" : ""}
              className="min-w-[110px] flex-1 bg-transparent px-1 py-0.5 text-xs text-ink-hi outline-none"
            />
          </div>
        ) : working.tags.length > 0 ? (
          <p className="text-xs text-ink-mid">
            {working.tags.map((t) => `#${t}`).join(" ")}
          </p>
        ) : (
          <p className="text-xs text-ink-lo">No tags.</p>
        )}
      </div>

      {voiceScan.count > 0 ? (
        <div className="rounded-md border border-status-publishing/30 bg-status-publishing/5 p-3">
          <p className="text-xs font-medium text-status-publishing">
            {voiceScan.count} founder-voice tell
            {voiceScan.count === 1 ? "" : "s"} flagged
          </p>
          <ul className="mt-2 space-y-1 text-xs text-ink-mid">
            {Array.from(new Set(voiceScan.spans.map((s) => s.label))).map(
              (label) => (
                <li key={label}>· {label}</li>
              ),
            )}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-ink-lo">
          Voice clean. The hook should land before “see more” expands.
        </p>
      )}
    </section>
  );

  const previewPane = post && (
    <section className="order-1 space-y-3 border-border p-5 md:order-none lg:border-r">
      <h2 className="text-xs uppercase tracking-wider text-ink-lo">
        Platform preview
      </h2>
      <PlatformPreview
        hook={working.hook}
        body={working.body}
        tags={working.tags}
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
      {post.targets.length === 0 && (
        <Banner tone="warn" title="No targets on this draft">
          Regenerate with platforms picked at the top of Drafts, or it can’t be
          approved.
        </Banner>
      )}
    </section>
  );

  const railPane = post && (
    <aside className="order-3 space-y-6 bg-surface-1/40 p-5 md:order-none">
      {/* Status + targets */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill status={post.status} />
          <CategoryChip category={post.category} />
        </div>
        {post.targets.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs uppercase tracking-wider text-ink-lo">
              Targets
            </p>
            <ul className="space-y-1">
              {post.targets.map((t) => (
                <li
                  key={t.id}
                  className="flex items-center justify-between gap-2 text-xs"
                  title={t.error ?? t.external_urn ?? t.status}
                >
                  <PlatformBadge platform={t.platform} />
                  <span
                    className={"capitalize " + TARGET_STATUS_TONE[t.status]}
                    title={
                      t.status === "skipped"
                        ? "Not published via API — post this one by hand"
                        : undefined
                    }
                  >
                    {t.status === "skipped" ? "manual" : t.status}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {post.scheduled_at && post.status === "scheduled" && (
          <Banner tone="info">
            Scheduled for{" "}
            <span className="font-medium text-ink-hi">
              {new Date(post.scheduled_at).toLocaleString()}
            </span>
            . The scheduler fans out to each target at this time.
          </Banner>
        )}
      </div>

      {/* Visual render slot */}
      <div className="space-y-3 border-t border-border pt-5">
        <p className="text-xs uppercase tracking-wider text-ink-lo">Visual</p>
        {latest ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={latest.image_url}
            alt={`Rendered visual for ${post.hook.slice(0, 60)}`}
            className="block w-full rounded-md border border-border bg-black"
          />
        ) : (
          <div className="flex aspect-square w-full items-center justify-center rounded-md border border-dashed border-border bg-surface-2 px-4 text-center text-xs text-ink-lo">
            No image yet. Pick a template and render.
          </div>
        )}

        <select
          value={selectedTemplateId}
          onChange={(e) => setSelectedTemplateId(e.target.value)}
          className="w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-ink-hi outline-none focus:border-ink-lo"
        >
          <option value="">Auto for category</option>
          <option value={AI_IMAGE_OPTION}>✦ AI image (Flux)</option>
          {templates
            .filter((t) => !t.name.startsWith("ai_image_"))
            .map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.category})
              </option>
            ))}
        </select>

        {isAIImageRender && (
          <div className="flex rounded-md border border-border bg-surface-2 p-0.5 text-xs">
            {AI_IMAGE_FRAMES.map((f) => (
              <button
                key={f.value}
                type="button"
                onClick={() => setFrame(f.value)}
                className={`flex-1 rounded px-2 py-1 transition-colors ${
                  frame === f.value
                    ? "bg-surface-1 text-ink-hi"
                    : "text-ink-lo hover:text-ink-hi"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        )}

        <ActionButton
          onClick={renderVisual}
          loading={rendering}
          variant="secondary"
        >
          {isAIImageRender
            ? latest
              ? "Re-generate AI image"
              : "Generate AI image"
            : isCarouselRender
              ? `${latest ? "Re-render" : "Render"} carousel (${post.extracts?.carousel_slides?.length ?? "?"})`
              : latest
                ? "Re-render"
                : "Render"}
        </ActionButton>

        {/* Custom image upload — raw passthrough, posts exactly as uploaded */}
        <input
          ref={uploadInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) uploadCustomImage(f);
          }}
        />
        <ActionButton
          onClick={() => uploadInputRef.current?.click()}
          loading={uploading}
          variant="secondary"
        >
          Upload custom image
        </ActionButton>

        {latest && (
          <p className="text-[11px] text-ink-lo">
            {latest.render_kind === "ai_image" && (
              <span className="mr-1 rounded border border-status-scheduled/40 px-1 py-0.5 text-[9px] uppercase tracking-wider text-status-scheduled">
                AI
              </span>
            )}
            {latest.render_kind === "upload" && (
              <span className="mr-1 rounded border border-ink-lo/40 px-1 py-0.5 text-[9px] uppercase tracking-wider text-ink-lo">
                Uploaded
              </span>
            )}
            {templateNameById(latest.template_id)} · {latest.width}×
            {latest.height} ·{" "}
            <a
              href={latest.image_url}
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-ink-mid"
            >
              full size
            </a>{" "}
            ·{" "}
            <button
              type="button"
              onClick={() => downloadAsset(latest)}
              className="underline hover:text-ink-mid"
            >
              download
            </button>
          </p>
        )}
        {renderError && (
          <Banner tone="error">
            <span className="font-mono break-all">{renderError}</span>
          </Banner>
        )}

        {currentCarousel.length > 1 && (
          <div className="space-y-2">
            <p className="text-[11px] uppercase tracking-wider text-ink-lo">
              Carousel ({currentCarousel.length} slides)
            </p>
            <ul className="grid grid-cols-4 gap-1.5">
              {currentCarousel.map((a, idx) => (
                <li key={a.id} className="space-y-1">
                  <a href={a.image_url} target="_blank" rel="noopener noreferrer">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={a.image_url}
                      alt={`Slide ${idx + 1}`}
                      className="block aspect-square w-full rounded border border-border bg-black hover:border-ink-lo"
                    />
                  </a>
                  <button
                    type="button"
                    onClick={() => downloadAsset(a, idx + 1)}
                    className="block w-full text-center text-[10px] text-ink-lo underline hover:text-ink-mid"
                  >
                    download
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {older.length > 0 && (
          <details>
            <summary className="cursor-pointer text-xs text-ink-lo hover:text-ink-mid">
              {older.length} earlier render{older.length === 1 ? "" : "s"}
            </summary>
            <ul className="mt-2 grid grid-cols-4 gap-1.5">
              {older.map((a) => (
                <li key={a.id}>
                  <a
                    href={a.image_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={`${templateNameById(a.template_id)} · ${new Date(a.created_at).toLocaleString()}`}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={a.image_url}
                      alt=""
                      className="block aspect-square w-full rounded border border-border bg-black hover:border-ink-lo"
                    />
                  </a>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      {/* Failed panel */}
      {showFailedPanel && (
        <div className="space-y-3 border-t border-border pt-5">
          <Banner
            tone="error"
            title={
              post.status === "failed"
                ? "Publish failed"
                : "One or more targets failed"
            }
          >
            {failedTargets.length > 0 ? (
              <ul className="space-y-1">
                {failedTargets.map((t) => (
                  <li key={t.id} className="font-mono break-all">
                    <span className="font-semibold">
                      {PLATFORM_LABEL[t.platform]}:
                    </span>{" "}
                    {t.error ?? "(no error message recorded)"}
                  </li>
                ))}
              </ul>
            ) : (
              <span className="font-mono break-all">
                {post.error ?? "(no error message recorded)"}
              </span>
            )}
          </Banner>
          {logs.length > 0 && (
            <details>
              <summary className="cursor-pointer text-xs text-ink-lo hover:text-ink-mid">
                Attempt history ({logs.length})
              </summary>
              <ul className="mt-2 space-y-2">
                {logs.map((l) => (
                  <li
                    key={l.id}
                    className="rounded border border-border bg-surface-2 p-2 text-[11px]"
                  >
                    <div className="flex justify-between text-ink-mid">
                      <span>
                        Attempt {l.attempt} ·{" "}
                        <span
                          className={
                            l.status === "success"
                              ? "text-status-published"
                              : "text-status-failed"
                          }
                        >
                          {l.status}
                        </span>
                      </span>
                      <span>{new Date(l.attempted_at).toLocaleString()}</span>
                    </div>
                    {l.error && (
                      <p className="mt-1 break-all font-mono text-status-failed">
                        {l.error}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {/* Meta */}
      <div className="space-y-1 border-t border-border pt-5 text-[11px] text-ink-lo">
        <p>Source trends: {post.source_trend_ids.length}</p>
        <p className="break-all">Post ID: {post.id}</p>
        {post.linkedin_urn && (
          <p className="break-all">LinkedIn URN: {post.linkedin_urn}</p>
        )}
        <p>Created {new Date(post.created_at).toLocaleString()}</p>
      </div>
    </aside>
  );

  return (
    <main className="flex min-h-screen flex-1 flex-col">
      <header className="flex items-center justify-between gap-4 border-b border-border px-5 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href="/drafts"
            className="text-sm text-ink-mid hover:text-ink-hi"
          >
            ← Drafts
          </Link>
          {post && (
            <span className="truncate font-serif text-lg text-ink-hi">
              {post.hook.slice(0, 80) || "Untitled draft"}
            </span>
          )}
        </div>
        {post && (
          <div className="hidden shrink-0 items-center gap-2 sm:flex">
            <StatusPill status={post.status} />
          </div>
        )}
      </header>

      {error && (
        <div className="p-5">
          <Banner tone="error">
            <span className="font-mono break-all">{error}</span>
          </Banner>
        </div>
      )}
      {loading && !post && (
        <p className="p-5 text-sm text-ink-lo">Loading draft…</p>
      )}

      {post && (
        <>
          {/* Tablet-only pane toggle (mobile shows both stacked; lg shows all). */}
          <div className="hidden border-b border-border px-5 py-2 md:flex lg:hidden">
            <div className="inline-flex rounded-md border border-border p-0.5 text-xs">
              {(["preview", "editor"] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setPane(p)}
                  className={
                    "rounded px-3 py-1 capitalize transition-colors " +
                    (pane === p
                      ? "bg-surface-2 text-ink-hi"
                      : "text-ink-mid hover:text-ink-hi")
                  }
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-1 flex-col lg:grid lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.35fr)_clamp(280px,24vw,360px)]">
            <div
              className={
                "flex flex-col " +
                (pane === "editor" ? "md:flex" : "md:hidden") +
                " lg:flex"
              }
            >
              {editorPane}
            </div>
            <div
              className={
                "flex flex-col " +
                (pane === "preview" ? "md:flex" : "md:hidden") +
                " lg:flex"
              }
            >
              {previewPane}
            </div>
            <div className="flex flex-col">{railPane}</div>
          </div>

          {schedulePickerOpen && (
            <div ref={schedulePickerRef} className="border-t border-border p-5">
              <SchedulePicker
                initialScheduledAt={post.scheduled_at}
                scheduling={scheduling}
                onSchedule={schedulePost}
                onCancel={() => setSchedulePickerOpen(false)}
              />
            </div>
          )}

          {actionError && (
            <div className="px-5 pt-3">
              <Banner tone="error" onDismiss={() => setActionError("")}>
                <span className="font-mono break-all">{actionError}</span>
              </Banner>
            </div>
          )}

          <ActionBar>
            {isDraft && (
              <>
                <ActionButton
                  onClick={saveDraft}
                  variant={dirty ? "primary" : "secondary"}
                  disabled={!canSave}
                  loading={saving}
                  title={dirty ? "Save your edits" : "No unsaved changes"}
                >
                  {dirty ? "Save changes" : "Saved"}
                </ActionButton>
                {dirty && (
                  <ActionButton onClick={revertEdits} variant="ghost">
                    Revert edits
                  </ActionButton>
                )}
                <ActionButton
                  onClick={approveDraft}
                  variant={dirty ? "secondary" : "primary"}
                  loading={approving}
                  disabled={post.targets.length === 0}
                  title="Mark approved (locks editing)"
                >
                  Approve
                </ActionButton>
              </>
            )}

            {(post.status === "approved" || post.status === "scheduled") && (
              <>
                <ActionButton
                  onClick={() => setSchedulePickerOpen((v) => !v)}
                  variant="secondary"
                >
                  {post.status === "scheduled" ? "Reschedule" : "Schedule"}
                </ActionButton>
                <ActionButton
                  onClick={publishNow}
                  variant="primary"
                  loading={publishing}
                  title="Publish to every target now"
                >
                  Publish now
                </ActionButton>
                {post.status === "scheduled" ? (
                  <ActionButton
                    onClick={unschedulePost}
                    variant="ghost"
                    loading={reversing}
                  >
                    Cancel schedule
                  </ActionButton>
                ) : (
                  <ActionButton
                    onClick={unapprovePost}
                    variant="ghost"
                    loading={reversing}
                  >
                    Revert to draft
                  </ActionButton>
                )}
              </>
            )}

            {post.status === "failed" && (
              <ActionButton
                onClick={retryPublish}
                variant="primary"
                loading={retrying}
              >
                Retry publish
              </ActionButton>
            )}

            <ActionButton
              onClick={generateAnother}
              variant="ghost"
              loading={generating}
            >
              Generate another
            </ActionButton>

            {(post.status === "draft" || post.status === "failed") && (
              <ActionButton
                onClick={deletePost}
                variant="danger"
                loading={deleting}
                title="Permanently delete this draft"
              >
                Delete
              </ActionButton>
            )}
          </ActionBar>
        </>
      )}
    </main>
  );
}

export default DraftDetailPage;
