import { CATEGORY_LABEL, type PostCategory } from "@/lib/domain";

// Categories are quiet on purpose (DESIGN.md §3): a neutral hairline chip, not a
// rainbow. Scannability on the board comes from the serif hook + platform
// badges + status pill — colour is reserved for the pipeline state, not the
// topic. Replaces the per-page CATEGORY_COLORS rainbow maps.

export function CategoryChip({
  category,
  className = "",
}: {
  category: PostCategory;
  className?: string;
}) {
  return (
    <span
      className={
        "inline-flex items-center rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs text-ink-mid " +
        className
      }
    >
      {CATEGORY_LABEL[category]}
    </span>
  );
}
