import type { PostStatus } from "@/lib/domain";

// The pipeline state, one component, one color map (DESIGN.md §4). Uses the
// semantic status tokens from globals.css. Literal class strings per status —
// Tailwind v4 can't see dynamically-built class names. A single status dot
// (this IS the status, not decorative rainbow) + the label.

const STATUS_STYLE: Record<PostStatus, { chip: string; dot: string }> = {
  draft: {
    chip: "border-status-draft/30 bg-status-draft/10 text-status-draft",
    dot: "bg-status-draft",
  },
  approved: {
    chip: "border-status-approved/30 bg-status-approved/10 text-status-approved",
    dot: "bg-status-approved",
  },
  scheduled: {
    chip: "border-status-scheduled/30 bg-status-scheduled/10 text-status-scheduled",
    dot: "bg-status-scheduled",
  },
  publishing: {
    chip: "border-status-publishing/30 bg-status-publishing/10 text-status-publishing",
    dot: "bg-status-publishing animate-pulse",
  },
  published: {
    chip: "border-status-published/30 bg-status-published/10 text-status-published",
    dot: "bg-status-published",
  },
  failed: {
    chip: "border-status-failed/30 bg-status-failed/10 text-status-failed",
    dot: "bg-status-failed",
  },
};

export function StatusPill({
  status,
  className = "",
}: {
  status: PostStatus;
  className?: string;
}) {
  const s = STATUS_STYLE[status];
  return (
    <span
      className={
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium capitalize " +
        s.chip +
        (className ? " " + className : "")
      }
    >
      <span className={"h-1.5 w-1.5 rounded-full " + s.dot} />
      {status}
    </span>
  );
}
