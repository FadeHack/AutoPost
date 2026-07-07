import { PLATFORM_LABEL, type Platform } from "@/lib/domain";

// Per-platform identity (DESIGN.md §4). A platform's hue is real brand identity
// (not arbitrary rainbow), so a small colored dot is allowed; the label/chrome
// stays neutral. `PlatformBadge` = inline list marker (fan-out targets on a
// row). `PlatformTab` = the cockpit tab-strip button (Chunk C).

export const PLATFORM_DOT: Record<Platform, string> = {
  linkedin: "bg-sky-500",
  bluesky: "bg-sky-400",
  mastodon: "bg-violet-500",
  threads: "bg-zinc-300",
  instagram: "bg-pink-500",
  x: "bg-zinc-100",
};

const PLATFORM_TAB_ON: Record<Platform, string> = {
  linkedin: "border-sky-500/60 text-ink-hi bg-sky-500/10",
  bluesky: "border-sky-400/60 text-ink-hi bg-sky-400/10",
  mastodon: "border-violet-500/60 text-ink-hi bg-violet-500/10",
  threads: "border-zinc-400/60 text-ink-hi bg-zinc-400/10",
  instagram: "border-pink-500/60 text-ink-hi bg-pink-500/10",
  x: "border-zinc-200/60 text-ink-hi bg-zinc-200/10",
};

export function PlatformBadge({
  platform,
  showLabel = true,
  className = "",
}: {
  platform: Platform;
  showLabel?: boolean;
  className?: string;
}) {
  return (
    <span
      title={PLATFORM_LABEL[platform]}
      className={
        "inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-1 px-2 py-0.5 text-xs text-ink-mid " +
        className
      }
    >
      <span className={"h-1.5 w-1.5 rounded-full " + PLATFORM_DOT[platform]} />
      {showLabel && PLATFORM_LABEL[platform]}
    </span>
  );
}

export function PlatformTab({
  platform,
  active,
  onClick,
}: {
  platform: Platform;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors " +
        (active
          ? PLATFORM_TAB_ON[platform]
          : "border-border text-ink-mid hover:bg-surface-1 hover:text-ink-hi")
      }
    >
      <span className={"h-1.5 w-1.5 rounded-full " + PLATFORM_DOT[platform]} />
      {PLATFORM_LABEL[platform]}
    </button>
  );
}
