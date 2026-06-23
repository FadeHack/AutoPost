// The founder-voice differentiator, made visible (DESIGN.md §4, §7). Presentational
// only — it shows the count of AI-tells stripped (`strip_ai_tells` violations)
// and whether the fast-model polish pass escalated. The live client-side
// scanner that feeds `violations` while typing lands in Chunk C; this renders
// whatever count it's given.

export function VoiceQualityChip({
  violations,
  escalated = false,
  className = "",
}: {
  violations: number;
  escalated?: boolean;
  className?: string;
}) {
  const clean = violations === 0;

  return (
    <span
      title={
        clean
          ? "No AI tells detected"
          : `${violations} AI tell${violations === 1 ? "" : "s"} stripped` +
            (escalated ? " · polish pass escalated" : "")
      }
      className={
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium " +
        (clean
          ? "border-status-published/30 bg-status-published/10 text-status-published"
          : "border-status-publishing/30 bg-status-publishing/10 text-status-publishing") +
        (className ? " " + className : "")
      }
    >
      {clean ? (
        <svg
          className="h-3 w-3"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M2.5 6.5 5 9l4.5-5.5" />
        </svg>
      ) : (
        <span className="h-1.5 w-1.5 rounded-full bg-status-publishing" />
      )}
      {clean ? "Voice clean" : `${violations} tell${violations === 1 ? "" : "s"}`}
      {escalated && !clean ? " · polished" : ""}
    </span>
  );
}
