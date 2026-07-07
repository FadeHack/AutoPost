"use client";

/**
 * PlatformPreview — one preview surface for every publishing target on a draft.
 *
 * The operator picks a platform tab; we render that platform's card variant
 * (LinkedIn keeps its rich feed card via the existing LinkedInPreview; the
 * microblogs + Instagram get lighter variants) and a CharBudgetMeter for the
 * text this platform would actually publish.
 *
 * In the cockpit (DESIGN.md §5C) this is the center pane — the visual center of
 * gravity — and it reads the *live* working copy while you edit, so a word
 * change shows its per-platform consequence immediately.
 *
 * Not pixel-perfect by design. The signal is: line breaks render, hashtags
 * read right, the image/carousel hangs where the real one will, and the
 * operator sees a char-budget problem BEFORE approving. Over-cap is never
 * truncated — the fix is regenerating (or tightening the platform's rewrite
 * prompt) so the variant comes back within budget.
 */

import { useState } from "react";
import LinkedInPreview from "@/components/LinkedInPreview";
import { PlatformTab } from "@/components/ui/PlatformBadge";
import { CharBudgetMeter } from "@/components/ui/CharBudgetMeter";
import { Banner } from "@/components/ui/Banner";
import { PLATFORM_LABEL, PLATFORM_LIMITS, type Platform } from "@/lib/domain";

export type { Platform };

export type PreviewTarget = {
  platform: Platform;
  // Per-platform rewritten body (Bluesky's 300-char variant today). NULL means
  // the platform publishes the canonical hook+body+tags.
  commentary: string | null;
};

type PlatformPreviewProps = {
  hook: string;
  body: string;
  tags: string[];
  imageUrl: string | null;
  carousel?: { url: string }[] | null;
  // Targets attached to this draft. Empty → preview LinkedIn canonical only.
  targets: PreviewTarget[];
  authorName?: string;
};

// Build the canonical hook+body+tags the same way the orchestrator does when a
// target has no per-platform commentary. Approximate (no clean_body), but the
// char count is close enough to flag a cap problem.
function buildCanonical(hook: string, body: string, tags: string[]): string {
  const prose = [hook.trim(), body.trim()].filter(Boolean).join("\n\n");
  const tagLine = tags.map((t) => `#${t}`).join(" ");
  return tagLine ? `${prose}\n\n${tagLine}` : prose;
}

function Handle({ name, accent }: { name: string; accent: string }) {
  return (
    <span className="text-[14px]">
      <span className="font-semibold text-zinc-100">{name}</span>
      <span className={accent}> @{name.toLowerCase().replace(/\s+/g, "")}</span>
    </span>
  );
}

/** Microblog card — Bluesky / Mastodon / Threads. Text-first, single image. */
function MicroblogCard({
  text,
  imageUrl,
  authorName,
  handleAccent,
}: {
  text: string;
  imageUrl: string | null;
  authorName: string;
  handleAccent: string;
}) {
  return (
    <div className="rounded-xl border border-zinc-700 bg-zinc-950 p-4 font-sans">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-zinc-600 to-zinc-800 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <Handle name={authorName} accent={handleAccent} />
          <p className="mt-1 text-[14px] leading-relaxed text-zinc-100 whitespace-pre-wrap break-words">
            {text}
          </p>
          {imageUrl && (
            <div className="mt-3 rounded-lg overflow-hidden border border-zinc-800 bg-black">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={imageUrl} alt="Post visual" className="block w-full" />
            </div>
          )}
          <div className="mt-3 flex gap-6 text-zinc-500 text-xs">
            <span>💬 reply</span>
            <span>🔁 repost</span>
            <span>♡ like</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Instagram card — image-first; flags the no-image case (IG can't post text). */
function InstagramCard({
  caption,
  imageUrl,
  authorName,
}: {
  caption: string;
  imageUrl: string | null;
  authorName: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-300 bg-white text-zinc-900 overflow-hidden font-sans">
      <div className="flex items-center gap-2 px-3 py-2">
        <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-amber-400 via-pink-500 to-violet-600 flex-shrink-0" />
        <span className="text-[13px] font-semibold">
          {authorName.toLowerCase().replace(/\s+/g, "")}
        </span>
        <span className="ml-auto text-zinc-500">⋯</span>
      </div>
      {imageUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={imageUrl}
          alt="Post visual"
          className="block w-full aspect-square object-cover bg-black"
        />
      ) : (
        <div className="aspect-square flex items-center justify-center bg-zinc-100 text-center px-6">
          <p className="text-sm text-red-600 font-medium">
            Instagram requires an image. Render a card before publishing —
            this target will fail the publish gate otherwise.
          </p>
        </div>
      )}
      <div className="px-3 py-2 text-[13px] leading-snug">
        <span className="font-semibold mr-1">
          {authorName.toLowerCase().replace(/\s+/g, "")}
        </span>
        <span className="whitespace-pre-wrap break-words">{caption}</span>
      </div>
    </div>
  );
}

export default function PlatformPreview({
  hook,
  body,
  tags,
  imageUrl,
  carousel,
  targets,
  authorName = "Your name",
}: PlatformPreviewProps) {
  const effectiveTargets: PreviewTarget[] =
    targets.length > 0 ? targets : [{ platform: "linkedin", commentary: null }];

  const [active, setActive] = useState<Platform>(effectiveTargets[0].platform);

  // Derive the rendered platform at render time: if the target set changed
  // (e.g. regenerate) and dropped the stored `active`, fall back to the first
  // available one without a reconciling effect.
  const activeTarget =
    effectiveTargets.find((t) => t.platform === active) ?? effectiveTargets[0];
  const activePlatform = activeTarget.platform;

  const canonical = buildCanonical(hook, body, tags);
  const text = activeTarget.commentary ?? canonical;
  const cap = PLATFORM_LIMITS[activePlatform];
  const overCap = text.length > cap;

  const [copied, setCopied] = useState(false);
  const copyText = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — the operator can still select the preview text */
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {effectiveTargets.map((t) => (
          <PlatformTab
            key={t.platform}
            platform={t.platform}
            active={t.platform === activePlatform}
            onClick={() => setActive(t.platform)}
          />
        ))}
        <button
          type="button"
          onClick={copyText}
          title="Copy this platform's text for manual pasting"
          className="ml-auto rounded-md border border-border px-2.5 py-1 text-xs text-ink-mid hover:bg-surface-1 hover:text-ink-hi"
        >
          {copied ? "Copied ✓" : "Copy text"}
        </button>
      </div>

      {activePlatform === "linkedin" ? (
        <LinkedInPreview
          hook={hook}
          body={body}
          tags={tags}
          imageUrl={imageUrl}
          carousel={carousel}
          authorName={authorName}
        />
      ) : activePlatform === "instagram" ? (
        <InstagramCard
          caption={text}
          imageUrl={
            (carousel && carousel.length > 0 ? carousel[0].url : null) ??
            imageUrl
          }
          authorName={authorName}
        />
      ) : (
        <MicroblogCard
          text={text}
          imageUrl={
            (carousel && carousel.length > 0 ? carousel[0].url : null) ??
            imageUrl
          }
          authorName={authorName}
          handleAccent={
            activePlatform === "mastodon"
              ? "text-violet-400"
              : activePlatform === "threads" || activePlatform === "x"
                ? "text-zinc-400"
                : "text-sky-400"
          }
        />
      )}

      <CharBudgetMeter used={text.length} platform={activePlatform} />

      {overCap && (
        <Banner tone="warn">
          This {PLATFORM_LABEL[activePlatform]} variant is over its {cap}-char
          cap and will fail the publish gate.
          {activeTarget.commentary === null && activePlatform !== "linkedin" ? (
            <>
              {" "}
              No per-platform rewrite is attached, so it&apos;s falling back to
              the LinkedIn-shaped body. Regenerate this draft to get a real{" "}
              {PLATFORM_LABEL[activePlatform]} variant.
            </>
          ) : (
            <>
              {" "}
              The per-platform rewrite came back over budget. Regenerate to roll
              a shorter variant, or tighten the {PLATFORM_LABEL[activePlatform]}{" "}
              rewrite prompt — we never truncate.
            </>
          )}
        </Banner>
      )}
    </div>
  );
}
