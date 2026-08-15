"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { EASE, stagger, staggerItem } from "@/lib/motion";
import { SyntheticCursor } from "./SyntheticCursor";
import {
  SocialCard,
  WALK_PLATFORMS,
  WALK_LIMITS,
  textFor,
  type VisualSource,
  type WPlatform,
} from "./WalkthroughPreview";

const VISUAL_SOURCES: { id: VisualSource; label: string }[] = [
  { id: "template", label: "Template" },
  { id: "ai", label: "AI image" },
  { id: "upload", label: "Upload" },
];

// The landing centerpiece (DESIGN.md §5 landing spec). A live, code-based
// simulation of the studio — not an MP4, not a screenshot. A scripted cursor
// walks the WHOLE pipeline spine, trends → draft → approved → scheduled →
// published: a trend arrives → Generate → the draft types itself in the founder
// voice → the voice-quality check flips clean → one Approve fans it out to six
// platforms → Schedule queues each at its own slot → Publish takes them live.
// Autoplays and loops; "Try it yourself" hands the mock controls to the visitor.
// Built from the real design tokens, so it themes with the page (light/dark) for
// free. Reduced-motion → a static labelled end-state.

type Phase =
  | "inbox"
  | "typing"
  | "voice"
  | "approved"
  | "scheduled"
  | "published";

// The progress rail mirrors the real status spine (DESIGN.md §5A funnel), so it
// rhymes with the "How it works" section directly below on the landing.
const RAIL: { label: string; phases: Phase[] }[] = [
  { label: "Trend", phases: ["inbox"] },
  { label: "Draft", phases: ["typing", "voice"] },
  { label: "Approved", phases: ["approved"] },
  { label: "Scheduled", phases: ["scheduled"] },
  { label: "Published", phases: ["published"] },
];
const PHASE_ORDER: Phase[] = [
  "inbox",
  "typing",
  "voice",
  "approved",
  "scheduled",
  "published",
];

const HOOK = "Ship the boring version first.";
const BODY =
  "The clever one is a bet you haven’t earned yet. Earn it in production, not in the pitch.";
const TYPE_MS = 24; // per character

const TRENDS = [
  { src: "HN", title: "Show HN: we deleted our microservices", hot: true },
  { src: "RSS", title: "The quiet return of the monolith", hot: false },
  { src: "Reddit", title: "What “boring tech” actually buys you", hot: false },
];

// Per-platform budget + a staggered publish slot — the fan-out's whole point is
// "same idea, different shape, sane cadence". Numbers/slots are illustrative but
// honest to the real limits.
const PLATFORMS = [
  { name: "LinkedIn", used: 118, limit: 3000, slot: "Tue 9:00" },
  { name: "Bluesky", used: 118, limit: 300, slot: "Tue 13:00" },
  { name: "Mastodon", used: 118, limit: 500, slot: "Wed 9:00" },
  { name: "Threads", used: 118, limit: 500, slot: "Wed 17:00" },
  { name: "Instagram", used: 118, limit: 2200, slot: "Thu 9:00" },
  { name: "X", used: 118, limit: 280, slot: "Fri 11:00" },
];

function StageChrome({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface-1">
      {/* Title bar */}
      <div className="flex items-center gap-2 border-b border-border bg-surface-2/60 px-4 py-2.5">
        <span className="flex gap-1.5" aria-hidden>
          <span className="h-2.5 w-2.5 rounded-full border border-border" />
          <span className="h-2.5 w-2.5 rounded-full border border-border" />
          <span className="h-2.5 w-2.5 rounded-full border border-border" />
        </span>
        <span className="ml-1 flex items-center gap-1.5 font-display text-[13px] tracking-tight text-ink-mid">
          <span className="inline-block h-1.5 w-1.5 rotate-45 bg-accent" aria-hidden />
          Nestwhirr Studio
        </span>
      </div>
      {children}
    </div>
  );
}

function MiniRail({ active }: { active: "inbox" | "drafts" | "calendar" }) {
  const map: Record<string, "inbox" | "drafts" | "calendar"> = {
    Inbox: "inbox",
    Drafts: "drafts",
    Calendar: "calendar",
  };
  return (
    <div className="hidden w-32 shrink-0 border-r border-border bg-surface-1/40 p-2.5 sm:block">
      <div className="mb-3 px-1.5 text-[10px] uppercase tracking-[0.18em] text-ink-lo">
        Studio
      </div>
      <div className="flex flex-col gap-0.5 text-[13px]">
        {["Today", "Inbox", "Drafts", "Calendar", "Published"].map((l) => {
          const on = map[l] === active;
          return (
            <div
              key={l}
              className={
                "rounded-md px-2 py-1.5 transition-colors " +
                (on ? "bg-surface-2 text-ink-hi" : "text-ink-lo")
              }
            >
              <span className={on ? "text-accent" : ""}>·</span>{" "}
              <span className="ml-1">{l}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Meter({ used, limit }: { used: number; limit: number }) {
  const pct = Math.min(100, Math.round((used / limit) * 100));
  return (
    <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-surface-2">
      <motion.div
        className="h-full rounded-full bg-accent/70"
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.6, ease: EASE }}
      />
    </div>
  );
}

// One platform card — its right-hand state tracks the pipeline: a char budget
// while approved, an indigo slot once scheduled, an emerald "Live" once published.
function PlatformCard({
  name,
  used,
  limit,
  slot,
  phase,
}: {
  name: string;
  used: number;
  limit: number;
  slot: string;
  phase: Phase;
}) {
  const scheduled = phase === "scheduled";
  const published = phase === "published";
  return (
    <motion.div
      variants={staggerItem}
      className={
        "rounded-md border bg-surface-1 px-2.5 py-2 transition-colors " +
        (published ? "border-status-published/40" : "border-border")
      }
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs text-ink-hi">{name}</span>
        {published ? (
          <span className="flex items-center gap-1 text-[10px] text-status-published">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-status-published" />
            Live
          </span>
        ) : scheduled ? (
          <span className="font-mono text-[10px] text-status-scheduled">{slot}</span>
        ) : (
          <span className="font-mono text-[10px] text-ink-lo">
            {used}/{limit}
          </span>
        )}
      </div>
      {published ? (
        <div className="mt-1.5 text-[10px] text-ink-lo">Posted ↗</div>
      ) : scheduled ? (
        <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-surface-2">
          <div className="h-full w-full rounded-full bg-status-scheduled/50" />
        </div>
      ) : (
        <Meter used={used} limit={limit} />
      )}
    </motion.div>
  );
}

export function StudioWalkthrough() {
  const reduced = useReducedMotion();
  const [phase, setPhase] = useState<Phase>("inbox");
  const [manual, setManual] = useState(false);
  const [typed, setTyped] = useState(0);
  const [cursor, setCursor] = useState({ x: 40, y: 40 });
  const [clicking, setClicking] = useState(false);
  const [voiceClean, setVoiceClean] = useState(false);
  const [visualSource, setVisualSource] = useState<VisualSource>("template");
  const [previewPlatform, setPreviewPlatform] = useState<WPlatform>("linkedin");

  const stageRef = useRef<HTMLDivElement>(null);
  const generateRef = useRef<HTMLButtonElement>(null);
  const primaryRef = useRef<HTMLButtonElement>(null); // Approve / Schedule / Publish

  const showCursor = !manual && !reduced;

  const moveCursorTo = useCallback((ref: React.RefObject<HTMLElement | null>) => {
    const stage = stageRef.current;
    const el = ref.current;
    if (!stage || !el) return;
    const s = stage.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    setCursor({ x: r.left - s.left + r.width / 2, y: r.top - s.top + r.height / 2 });
  }, []);

  // Typing effect — runs whenever we enter the drafting phase.
  useEffect(() => {
    if (phase !== "typing") return;
    if (reduced) {
      setTyped(HOOK.length + BODY.length);
      return;
    }
    let i = 0;
    setTyped(0);
    const id = setInterval(() => {
      i += 1;
      setTyped(i);
      if (i >= HOOK.length + BODY.length) {
        clearInterval(id);
        // In manual mode, advance to the voice check on its own so the visitor
        // sees the differentiator without another click.
        if (manual) setTimeout(() => setPhase("voice"), 350);
      }
    }, TYPE_MS);
    return () => clearInterval(id);
  }, [phase, reduced, manual]);

  // Voice check flips clean shortly after entering that phase; stays clean after.
  useEffect(() => {
    if (phase === "inbox" || phase === "typing") {
      setVoiceClean(false);
      return;
    }
    if (phase === "voice") {
      const id = setTimeout(() => setVoiceClean(true), reduced ? 0 : 900);
      return () => clearTimeout(id);
    }
    setVoiceClean(true);
  }, [phase, reduced]);

  // While the preview is visible, gently cycle the featured platform so the
  // visitor sees the *same idea* land as a real post on each surface. Manual
  // mode hands this to the tab strip instead.
  const previewLive =
    phase === "voice" ||
    phase === "approved" ||
    phase === "scheduled" ||
    phase === "published";
  useEffect(() => {
    if (manual || reduced || !previewLive) return;
    const id = setInterval(() => {
      setPreviewPlatform((p) => {
        const i = WALK_PLATFORMS.findIndex((x) => x.id === p);
        return WALK_PLATFORMS[(i + 1) % WALK_PLATFORMS.length].id;
      });
    }, 2000);
    return () => clearInterval(id);
  }, [manual, reduced, previewLive]);

  // Autoplay runner — a single cancellable sequence that loops the whole spine.
  useEffect(() => {
    if (manual || reduced) return;
    let cancelled = false;
    const wait = (ms: number) => new Promise<void>((res) => setTimeout(res, ms));
    const raf = () => new Promise<void>((res) => requestAnimationFrame(() => res()));
    const clickAt = async (ref: React.RefObject<HTMLElement | null>, settle = 1400) => {
      await raf();
      moveCursorTo(ref);
      await wait(settle);
      if (cancelled) return;
      setClicking(true);
      await wait(200);
      setClicking(false);
    };

    (async () => {
      while (!cancelled) {
        setPhase("inbox");
        setTyped(0);
        setCursor({ x: 40, y: 40 });
        await wait(650);
        if (cancelled) return;

        await clickAt(generateRef, 950); // Generate
        setPhase("typing");
        await wait(HOOK.length * TYPE_MS + BODY.length * TYPE_MS + 700);
        if (cancelled) return;

        setPhase("voice");
        await clickAt(primaryRef, 1500); // Approve
        setPhase("approved");
        await wait(1500);
        if (cancelled) return;

        await clickAt(primaryRef, 900); // Schedule
        setPhase("scheduled");
        await wait(1700);
        if (cancelled) return;

        await clickAt(primaryRef, 900); // Publish
        setPhase("published");
        await wait(3000);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [manual, reduced, moveCursorTo]);

  // Manual controls advance one pipeline step at a time.
  const advance = () => {
    if (!manual) return;
    setPhase((p) => {
      const i = PHASE_ORDER.indexOf(p);
      // Skip the auto "voice" step from typing — the typing effect handles it.
      if (p === "typing") return p;
      return PHASE_ORDER[Math.min(i + 1, PHASE_ORDER.length - 1)];
    });
  };
  const restart = () => {
    setPhase("inbox");
    setTyped(0);
    setVoiceClean(false);
  };

  const inCockpit = phase !== "inbox";
  const hookShown = HOOK.slice(0, Math.min(typed, HOOK.length));
  const bodyShown = typed > HOOK.length ? BODY.slice(0, typed - HOOK.length) : "";
  const caretVisible = phase === "typing" && typed < HOOK.length + BODY.length;
  // The rendered card appears once the draft is written (voice onward).
  const rendered =
    phase === "voice" ||
    phase === "approved" ||
    phase === "scheduled" ||
    phase === "published";
  const showChips =
    phase === "approved" || phase === "scheduled" || phase === "published";

  // The primary action changes down the spine.
  const primary =
    phase === "voice"
      ? { label: "Approve", onClick: advance, done: false }
      : phase === "approved"
        ? { label: "Schedule", onClick: advance, done: false }
        : phase === "scheduled"
          ? { label: "Publish now", onClick: advance, done: false }
          : phase === "published"
            ? { label: "Published ✓", onClick: () => {}, done: true }
            : null;

  const actionNote =
    phase === "published"
      ? "Live on 6 platforms"
      : phase === "scheduled"
        ? "Queued across the week"
        : phase === "approved"
          ? "Approved · pick a cadence"
          : "Review · verify voice · approve";

  const railActive = RAIL.find((r) => r.phases.includes(phase))!.label;
  const miniRailActive: "inbox" | "drafts" | "calendar" =
    phase === "inbox"
      ? "inbox"
      : phase === "scheduled" || phase === "published"
        ? "calendar"
        : "drafts";

  if (reduced) return <StaticSnapshot />;

  return (
    <div className="w-full">
      <div ref={stageRef} className="relative">
        <StageChrome>
          <div className="flex min-h-[360px]">
            <MiniRail active={miniRailActive} />

            <div className="relative min-w-0 flex-1 p-4 sm:p-5">
              <AnimatePresence mode="wait">
                {!inCockpit ? (
                  <motion.div
                    key="inbox"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.3, ease: EASE }}
                  >
                    <div className="mb-3 flex items-baseline justify-between">
                      <h3 className="font-display text-lg tracking-tight text-ink-hi">
                        Inbox
                      </h3>
                      <span className="text-[11px] uppercase tracking-wider text-ink-lo">
                        Fresh signal
                      </span>
                    </div>
                    <div className="divide-y divide-border rounded-lg border border-border">
                      {TRENDS.map((t, i) => (
                        <div
                          key={t.title}
                          className={
                            "flex items-center gap-3 px-3 py-2.5 " +
                            (i === 0 ? "bg-surface-2/50" : "")
                          }
                        >
                          <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-ink-lo">
                            {t.src}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-sm text-ink-hi">
                            {t.title}
                          </span>
                          {i === 0 ? (
                            <button
                              ref={generateRef}
                              onClick={() => manual && setPhase("typing")}
                              className={
                                "shrink-0 rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-accent-ink transition-opacity " +
                                (manual ? "hover:opacity-90" : "cursor-default")
                              }
                            >
                              Generate →
                            </button>
                          ) : (
                            <span className="shrink-0 text-[11px] text-ink-lo">
                              new
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </motion.div>
                ) : (
                  <motion.div
                    key="cockpit"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.3, ease: EASE }}
                  >
                    <div className="mb-3 flex items-center gap-2">
                      <h3 className="font-display text-lg tracking-tight text-ink-hi">
                        Draft
                      </h3>
                      <StatusChip phase={phase} />
                      <div className="ml-auto">
                        <VoiceChip phase={phase} clean={voiceClean} />
                      </div>
                    </div>

                    {/* The real cockpit shape (DESIGN.md §5C): compose on the
                        left (the editable draft + the Visual source), the live
                        per-platform social preview on the right. The preview is
                        the actual post mockup — the same idea landing as a real
                        LinkedIn / microblog / Instagram post — and the Visual can
                        be a brand template, an AI image, or an upload. */}
                    <div className="grid gap-3 lg:grid-cols-[0.95fr_1.05fr]">
                      {/* Compose */}
                      <div className="space-y-3">
                        <div className="rounded-lg border border-border bg-bg/40 p-4">
                          <p className="min-h-[1.6em] font-display text-xl leading-snug tracking-tight text-ink-hi">
                            {hookShown}
                            {caretVisible && typed <= HOOK.length && <Caret />}
                          </p>
                          <p className="mt-2 min-h-[3em] font-serif text-[15px] leading-relaxed text-ink-mid">
                            {bodyShown}
                            {caretVisible && typed > HOOK.length && <Caret />}
                          </p>
                        </div>

                        {rendered && (
                          <motion.div
                            initial={{ opacity: 0, y: 6 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.3, ease: EASE }}
                            className="rounded-lg border border-border bg-surface-1 p-3"
                          >
                            <div className="mb-2 flex items-baseline justify-between">
                              <span className="text-[11px] uppercase tracking-wider text-ink-lo">
                                Visual
                              </span>
                              <span className="text-[10px] text-ink-lo">
                                brand template · AI · upload
                              </span>
                            </div>
                            <div className="flex gap-1">
                              {VISUAL_SOURCES.map((v) => (
                                <button
                                  key={v.id}
                                  onClick={() => setVisualSource(v.id)}
                                  className={
                                    "flex-1 rounded-md px-2 py-1.5 text-[11px] transition-colors " +
                                    (visualSource === v.id
                                      ? "bg-accent text-accent-ink"
                                      : "border border-border text-ink-mid hover:text-ink-hi")
                                  }
                                >
                                  {v.label}
                                </button>
                              ))}
                            </div>
                          </motion.div>
                        )}

                        {/* Fan-out overview — all six platforms at once, each
                            tracking its pipeline state (char budget → scheduled
                            slot → live). Fills the compose column beside the
                            single-platform live preview. */}
                        {showChips && (
                          <motion.div
                            variants={stagger}
                            initial="hidden"
                            animate="show"
                            className="grid grid-cols-2 gap-2"
                          >
                            {PLATFORMS.map((p) => (
                              <PlatformCard key={p.name} {...p} phase={phase} />
                            ))}
                          </motion.div>
                        )}
                      </div>

                      {/* Preview */}
                      <div className="relative">
                        <AnimatePresence mode="wait">
                          {rendered ? (
                            <motion.div
                              key="preview"
                              initial={{ opacity: 0, y: 6 }}
                              animate={{ opacity: 1, y: 0 }}
                              exit={{ opacity: 0 }}
                              transition={{ duration: 0.35, ease: EASE }}
                            >
                              <div className="mb-2 flex flex-wrap gap-1">
                                {WALK_PLATFORMS.map((p) => (
                                  <button
                                    key={p.id}
                                    onClick={() => manual && setPreviewPlatform(p.id)}
                                    className={
                                      "rounded-md px-2 py-0.5 text-[10px] transition-colors " +
                                      (previewPlatform === p.id
                                        ? "bg-surface-2 text-ink-hi"
                                        : "text-ink-lo hover:text-ink-mid") +
                                      (manual ? "" : " cursor-default")
                                    }
                                  >
                                    {p.label}
                                  </button>
                                ))}
                              </div>
                              <div className="mx-auto max-w-[300px]">
                                {/* Fixed-height slot: the mock cards vary in
                                    height per platform (~352–426px: short X/
                                    microblog vs. tall Instagram/LinkedIn), so
                                    pin the slot ABOVE the tallest and top-align.
                                    A min-height floor isn't enough — the tall
                                    cards overflow it — so this is a hard height,
                                    and swapping cards never resizes the stage. */}
                                <div className="h-[448px]">
                                  <AnimatePresence mode="wait">
                                    <motion.div
                                      key={previewPlatform + visualSource}
                                      initial={{ opacity: 0, y: 8 }}
                                      animate={{ opacity: 1, y: 0 }}
                                      exit={{ opacity: 0, y: -8 }}
                                      transition={{ duration: 0.25, ease: EASE }}
                                    >
                                      <SocialCard
                                        platform={previewPlatform}
                                        source={visualSource}
                                      />
                                    </motion.div>
                                  </AnimatePresence>
                                </div>
                                <PreviewMeter platform={previewPlatform} />
                              </div>
                            </motion.div>
                          ) : (
                            <motion.div
                              key="rendering"
                              initial={{ opacity: 0 }}
                              animate={{ opacity: 1 }}
                              exit={{ opacity: 0 }}
                              className="mx-auto flex aspect-square w-full max-w-[220px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-ink-lo"
                            >
                              <span className="inline-block h-2 w-2 rotate-45 bg-accent/60" aria-hidden />
                              <span className="text-[11px]">Rendering visual…</span>
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </div>
                    </div>

                    {/* Action bar — the primary action walks the spine. */}
                    <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
                      <span className="text-[11px] text-ink-lo">{actionNote}</span>
                      {primary && (
                        <button
                          ref={primaryRef}
                          onClick={primary.onClick}
                          disabled={primary.done}
                          className={
                            "rounded-md px-3 py-1.5 text-xs font-medium transition-colors " +
                            (primary.done
                              ? "border border-border text-status-published"
                              : "bg-accent text-accent-ink " +
                                (manual ? "hover:opacity-90" : "cursor-default"))
                          }
                        >
                          {primary.label}
                        </button>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </StageChrome>

        <SyntheticCursor
          x={cursor.x}
          y={cursor.y}
          clicking={clicking}
          visible={showCursor}
        />
      </div>

      {/* Progress rail (the real status spine) + controls */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-3">
        <ol className="flex flex-1 flex-wrap items-center gap-x-3 gap-y-1 sm:gap-x-4">
          {RAIL.map((r, i) => {
            const active = r.label === railActive;
            const done =
              RAIL.findIndex((x) => x.label === railActive) > i;
            return (
              <li key={r.label} className="flex items-center gap-2">
                <span
                  className={
                    "inline-block h-1.5 w-1.5 rounded-full transition-colors " +
                    (active ? "bg-accent" : done ? "bg-ink-mid" : "bg-border")
                  }
                />
                <span
                  className={
                    "text-[11px] transition-colors " +
                    (active ? "text-ink-hi" : "text-ink-lo")
                  }
                >
                  {r.label}
                </span>
              </li>
            );
          })}
        </ol>

        <div className="flex items-center gap-2">
          {!manual ? (
            <button
              onClick={() => {
                setManual(true);
                restart();
              }}
              className="rounded-md border border-border px-3 py-1.5 text-xs text-ink-mid transition-colors hover:border-ink-lo hover:text-ink-hi"
            >
              Try it yourself
            </button>
          ) : (
            <>
              <button
                onClick={restart}
                className="rounded-md border border-border px-3 py-1.5 text-xs text-ink-mid transition-colors hover:border-ink-lo hover:text-ink-hi"
              >
                Reset
              </button>
              <button
                onClick={() => {
                  setManual(false);
                  restart();
                }}
                className="rounded-md px-3 py-1.5 text-xs text-ink-lo transition-colors hover:text-ink-hi"
              >
                Replay tour
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// Char budget for the featured platform — the per-platform reality the real
// CharBudgetMeter shows (Bluesky 300 vs LinkedIn 3000), so "same idea" visibly
// means "different length" per surface.
function PreviewMeter({ platform }: { platform: WPlatform }) {
  const used = textFor(platform).full.length;
  const limit = WALK_LIMITS[platform];
  const pct = Math.min(100, Math.round((used / limit) * 100));
  return (
    <div className="mt-2 flex items-center gap-2">
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-surface-2">
        <div
          className="h-full rounded-full bg-accent/70"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-[10px] text-ink-lo">
        {used}/{limit}
      </span>
    </div>
  );
}

function Caret() {
  return (
    <motion.span
      aria-hidden
      className="ml-0.5 inline-block h-[0.95em] w-[2px] translate-y-[0.12em] bg-accent"
      animate={{ opacity: [1, 0.15, 1] }}
      transition={{ duration: 0.9, repeat: Infinity, ease: "linear" }}
    />
  );
}

function StatusChip({ phase }: { phase: Phase }) {
  const map: Partial<Record<Phase, { label: string; cls: string }>> = {
    approved: {
      label: "Approved",
      cls: "border-status-approved/40 text-status-approved",
    },
    scheduled: {
      label: "Scheduled",
      cls: "border-status-scheduled/40 text-status-scheduled",
    },
    published: {
      label: "Published",
      cls: "border-status-published/40 text-status-published",
    },
  };
  const s = map[phase] ?? { label: "Draft", cls: "border-border text-ink-lo" };
  return (
    <span
      className={
        "rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider " +
        s.cls
      }
    >
      {s.label}
    </span>
  );
}

function VoiceChip({ phase, clean }: { phase: Phase; clean: boolean }) {
  if (phase === "typing") {
    return (
      <span className="rounded-full border border-border px-2 py-0.5 text-[10px] text-ink-lo">
        · · ·
      </span>
    );
  }
  const analyzing = phase === "voice" && !clean;
  return (
    <motion.span
      initial={{ opacity: 0, scale: 0.94 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.2, ease: EASE }}
      className={
        "rounded-full border px-2 py-0.5 text-[10px] " +
        (analyzing
          ? "border-status-publishing/40 text-status-publishing"
          : "border-status-published/40 text-status-published")
      }
    >
      {analyzing ? "Checking voice…" : "Voice: clean"}
    </motion.span>
  );
}

// Static, motion-free snapshot for reduced-motion users — the full spine as a
// labelled stepped diagram, no cursor, no timers.
function StaticSnapshot() {
  return (
    <StageChrome>
      <div className="p-5">
        <ol className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-5">
          {RAIL.map((r, i) => (
            <li key={r.label} className="bg-surface-1 p-4">
              <div className="font-display text-sm text-accent">
                {String(i + 1).padStart(2, "0")}
              </div>
              <div className="mt-1.5 text-sm text-ink-hi">{r.label}</div>
            </li>
          ))}
        </ol>
        <div className="mt-4 rounded-lg border border-border bg-bg/40 p-4">
          <p className="font-display text-xl leading-snug tracking-tight text-ink-hi">
            {HOOK}
          </p>
          <p className="mt-2 font-serif text-[15px] leading-relaxed text-ink-mid">
            {BODY}
          </p>
        </div>
      </div>
    </StageChrome>
  );
}
