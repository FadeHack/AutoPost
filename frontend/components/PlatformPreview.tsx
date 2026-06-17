"use client";

/**
 * PlatformPreview — one preview surface for every publishing target on a draft.
 *
 * The operator picks a platform tab; we render that platform's card variant
 * (LinkedIn keeps its rich feed card via the existing LinkedInPreview; the
 * microblogs + Instagram get lighter variants) and an inline char-limit
 * warning when the text this platform would publish exceeds its cap.
 *
 * Not pixel-perfect by design. The signal is: line breaks render, hashtags
 * read right, the image/carousel hangs where the real one will, and the
 * operator sees a char-limit problem BEFORE approving. The long-term fix for
 * over-cap bodies is per-platform generation (Phase 12), not truncation — the
 * warning says so.
 */

import { useState } from "react";
import LinkedInPreview from "@/components/LinkedInPreview";

export type Platform =
  | "linkedin"
  | "bluesky"
  | "mastodon"
  | "threads"
  | "instagram";

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

// Mirrors each Publisher.char_limit on the backend exactly — keep in sync.
const PLATFORM_LIMITS: Record<Platform, number> = {
  linkedin: 3000,
  bluesky: 300,
  mastodon: 500,
  threads: 500,
  instagram: 2200,
};

const PLATFORM_LABEL: Record<Platform, string> = {
  linkedin: "LinkedIn",
  bluesky: "Bluesky",
  mastodon: "Mastodon",
  threads: "Threads",
  instagram: "Instagram",
};

// Tab accent per platform.
const PLATFORM_ACCENT: Record<Platform, string> = {
  linkedin: "border-sky-600 text-sky-300 bg-sky-950/30",
  bluesky: "border-sky-500 text-sky-200 bg-sky-950/30",
  mastodon: "border-violet-600 text-violet-300 bg-violet-950/30",
  threads: "border-zinc-400 text-zinc-200 bg-zinc-800/50",
  instagram: "border-pink-600 text-pink-300 bg-pink-950/30",
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

  const [active, setActive] = useState<Platform>(
    effectiveTargets[0].platform,
  );
  const activeTarget =
    effectiveTargets.find((t) => t.platform === active) ?? effectiveTargets[0];

  const canonical = buildCanonical(hook, body, tags);
  const text = activeTarget.commentary ?? canonical;
  const cap = PLATFORM_LIMITS[active];
  const overCap = text.length > cap;

  return (
    <div className="space-y-3">
      {effectiveTargets.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {effectiveTargets.map((t) => {
            const on = t.platform === active;
            return (
              <button
                key={t.platform}
                type="button"
                onClick={() => setActive(t.platform)}
                className={
                  "rounded border px-3 py-1 text-xs font-medium transition " +
                  (on
                    ? PLATFORM_ACCENT[t.platform]
                    : "border-zinc-700 text-zinc-400 hover:text-white")
                }
              >
                {PLATFORM_LABEL[t.platform]}
              </button>
            );
          })}
        </div>
      )}

      {active === "linkedin" ? (
        <LinkedInPreview
          hook={hook}
          body={body}
          tags={tags}
          imageUrl={imageUrl}
          carousel={carousel}
          authorName={authorName}
        />
      ) : active === "instagram" ? (
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
            active === "mastodon"
              ? "text-violet-400"
              : active === "threads"
                ? "text-zinc-400"
                : "text-sky-400"
          }
        />
      )}

      <p className="text-xs text-zinc-500">
        {text.length} / {cap} chars
      </p>

      {overCap && (
        <div className="rounded border border-amber-700 bg-amber-950/30 p-3 text-xs text-amber-200">
          This {PLATFORM_LABEL[active]} variant is{" "}
          <span className="font-semibold">{text.length} chars</span>, over the{" "}
          {cap}-char cap — it will fail the publish gate. The long-term fix is
          per-platform generation (Phase 12), not truncation.
          {activeTarget.commentary === null && active !== "linkedin" && (
            <>
              {" "}
              This target currently falls back to the LinkedIn-shaped body.
            </>
          )}
        </div>
      )}
    </div>
  );
}
