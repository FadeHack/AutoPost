import { PLATFORM_LIMITS, PLATFORM_LABEL, type Platform } from "@/lib/domain";

// Makes the per-platform char reality visible (DESIGN.md §4) instead of failing
// loudly at publish: a thin track that fills toward the cap and turns amber when
// over. The honest fix for over-cap is per-platform generation, not truncation —
// the consumer (cockpit) surfaces that copy; this is the meter only.

export function CharBudgetMeter({
  used,
  platform,
  limit,
}: {
  used: number;
  platform: Platform;
  limit?: number;
}) {
  const cap = limit ?? PLATFORM_LIMITS[platform];
  const over = used > cap;
  const pct = Math.min(100, (used / cap) * 100);
  const near = !over && pct >= 85;

  const fill = over
    ? "bg-status-failed"
    : near
      ? "bg-status-publishing"
      : "bg-accent";

  return (
    <div className="space-y-1">
      <div className="h-1 w-full overflow-hidden rounded-full bg-surface-2">
        <div
          className={"h-full rounded-full transition-all " + fill}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p
        className={
          "text-xs tabular-nums " +
          (over ? "text-status-failed" : "text-ink-lo")
        }
      >
        {used.toLocaleString()} / {cap.toLocaleString()} chars
        {over && (
          <span className="ml-1 font-medium">
            · over the {PLATFORM_LABEL[platform]} cap
          </span>
        )}
      </p>
    </div>
  );
}
