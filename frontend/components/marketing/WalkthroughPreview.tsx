"use client";

import { PostCardMock } from "./PostCardMock";

// Faithful (not pixel-perfect) mini social-post mockups for the landing
// walkthrough — the same idea PlatformPreview.tsx shows in the real cockpit:
// a LinkedIn feed card, dark microblog cards (Bluesky/Mastodon/Threads/X), and
// an Instagram card, each carrying the post text + the chosen VISUAL. The visual
// itself has three sources, mirroring the real Visual panel's render_kind
// (template | ai_image | upload) — so the walkthrough shows both "same idea,
// every platform" AND "your visual can be a brand template, an AI image, or an
// upload". Cards keep their real-platform colors on purpose (that's how they
// look), so they read the same in either app theme.

export type WPlatform =
  | "linkedin"
  | "bluesky"
  | "mastodon"
  | "threads"
  | "instagram"
  | "x";

export type VisualSource = "template" | "ai" | "upload";

export const WALK_PLATFORMS: { id: WPlatform; label: string }[] = [
  { id: "linkedin", label: "LinkedIn" },
  { id: "bluesky", label: "Bluesky" },
  { id: "mastodon", label: "Mastodon" },
  { id: "threads", label: "Threads" },
  { id: "instagram", label: "Instagram" },
  { id: "x", label: "X" },
];

export const WALK_LIMITS: Record<WPlatform, number> = {
  linkedin: 3000,
  bluesky: 300,
  mastodon: 500,
  threads: 500,
  instagram: 2200,
  x: 280,
};

const HOOK = "Ship the boring version first.";
const BODY =
  "The clever one is a bet you haven’t earned yet. Earn it in production, not in the pitch.";
// Bluesky / X get a tighter rewrite (real per-platform behaviour, DESIGN thesis).
const SHORT = "Ship the boring version first. Earn the clever one in production — not the pitch.";

export function textFor(p: WPlatform): { hook: string; body: string; full: string } {
  if (p === "bluesky" || p === "x")
    return { hook: SHORT, body: "", full: SHORT };
  return { hook: HOOK, body: BODY, full: `${HOOK}\n\n${BODY}` };
}

// ---- The visual (three sources) ------------------------------------------

export function Visual({
  source,
  className = "",
}: {
  source: VisualSource;
  className?: string;
}) {
  if (source === "template") {
    return (
      <PostCardMock
        compact
        eyebrow="Founder insight"
        quote="Ship the boring version first. The clever one is a bet you haven’t earned yet."
        brand="Nestwhirr"
        className={className}
      />
    );
  }
  if (source === "upload") {
    // A stand-in "uploaded photo" — a simple landscape so it clearly reads as a
    // real photo, not a brand card.
    return (
      <div
        className={
          "relative aspect-square w-full overflow-hidden rounded-lg border border-white/10 " +
          className
        }
      >
        <div className="absolute inset-0 bg-gradient-to-b from-sky-300 via-sky-100 to-emerald-100" />
        <div className="absolute right-5 top-5 h-8 w-8 rounded-full bg-amber-200" />
        <div className="absolute -bottom-6 -left-6 h-2/3 w-[130%] rotate-[-8deg] rounded-[40%] bg-emerald-600/80" />
        <div className="absolute bottom-2 left-2 rounded bg-black/50 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-white/90">
          Uploaded photo
        </div>
      </div>
    );
  }
  // AI image — a vivid diffusion-style field so it's unmistakably not a template.
  return (
    <div
      className={
        "relative aspect-square w-full overflow-hidden rounded-lg border border-white/10 " +
        className
      }
      style={{
        background:
          "conic-gradient(from 210deg at 40% 30%, #7c3aed, #db2777, #f59e0b, #10b981, #3b82f6, #7c3aed)",
      }}
    >
      <div className="absolute inset-0 backdrop-blur-[6px]" />
      <div className="absolute bottom-2 left-2 rounded bg-black/50 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-white/90">
        AI image
      </div>
    </div>
  );
}

// ---- Per-platform social cards -------------------------------------------

function Avatar({ className = "" }: { className?: string }) {
  return (
    <div
      className={
        "h-8 w-8 shrink-0 rounded-full bg-gradient-to-br from-zinc-500 to-zinc-800 " +
        className
      }
    />
  );
}

function LinkedInCard({ source }: { source: VisualSource }) {
  const { hook, body } = textFor("linkedin");
  return (
    <div className="rounded-xl border border-zinc-300 bg-white p-3 font-sans text-zinc-900 shadow-sm">
      <div className="flex items-center gap-2">
        <Avatar />
        <div className="min-w-0 leading-tight">
          <div className="text-[12px] font-semibold">
            Nestwhirr <span className="font-normal text-zinc-500">· 1st</span>
          </div>
          <div className="text-[10px] text-zinc-500">Founder-led · 2h</div>
        </div>
        <span className="ml-auto text-[13px] font-semibold text-[#0a66c2]">
          in
        </span>
      </div>
      <p className="mt-2 text-[12px] leading-snug">
        <span className="font-semibold">{hook}</span>
        <br />
        {body}
      </p>
      <div className="mt-2 overflow-hidden rounded-md border border-zinc-200">
        <Visual source={source} className="!rounded-none" />
      </div>
      <div className="mt-2 flex gap-5 text-[11px] text-zinc-500">
        <span>👍 Like</span>
        <span>💬 Comment</span>
        <span>🔁 Repost</span>
      </div>
    </div>
  );
}

function MicroblogCard({
  platform,
  source,
}: {
  platform: WPlatform;
  source: VisualSource;
}) {
  const { full } = textFor(platform);
  const accent =
    platform === "bluesky"
      ? "text-sky-400"
      : platform === "mastodon"
        ? "text-violet-400"
        : "text-zinc-400";
  const handle = "nestwhirr";
  return (
    <div className="rounded-xl border border-zinc-700 bg-zinc-950 p-3 font-sans text-zinc-100">
      <div className="flex items-start gap-2.5">
        <Avatar />
        <div className="min-w-0 flex-1">
          <div className="text-[12px]">
            <span className="font-semibold">Nestwhirr</span>{" "}
            <span className={accent}>@{handle}</span>
            {platform === "x" && (
              <span className="ml-1 font-semibold text-zinc-100">𝕏</span>
            )}
          </div>
          <p className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed text-zinc-100">
            {full}
          </p>
          <div className="mt-2 overflow-hidden rounded-lg border border-zinc-800">
            <Visual source={source} className="!rounded-none" />
          </div>
          <div className="mt-2 flex gap-5 text-[11px] text-zinc-500">
            <span>💬</span>
            <span>🔁</span>
            <span>♡</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function InstagramCard({ source }: { source: VisualSource }) {
  const { full } = textFor("instagram");
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-300 bg-white font-sans text-zinc-900">
      <div className="flex items-center gap-2 px-3 py-2">
        <div className="h-7 w-7 rounded-full bg-gradient-to-tr from-amber-400 via-pink-500 to-violet-600" />
        <span className="text-[12px] font-semibold">nestwhirr</span>
        <span className="ml-auto text-zinc-400">⋯</span>
      </div>
      <Visual source={source} className="!rounded-none !border-0" />
      <div className="px-3 py-2 text-[12px] leading-snug">
        <span className="mr-1 font-semibold">nestwhirr</span>
        <span className="whitespace-pre-wrap">{full}</span>
      </div>
    </div>
  );
}

export function SocialCard({
  platform,
  source,
}: {
  platform: WPlatform;
  source: VisualSource;
}) {
  if (platform === "linkedin") return <LinkedInCard source={source} />;
  if (platform === "instagram") return <InstagramCard source={source} />;
  return <MicroblogCard platform={platform} source={source} />;
}
