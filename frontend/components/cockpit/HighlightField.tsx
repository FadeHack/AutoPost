"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import { scanVoiceTells, segmentByTells, type TellSpan } from "@/lib/voice";

// The inline voice-flagging surface (DESIGN.md §5C). A text layer that wavy-red
// underlines every founder-voice tell in place. Two modes share one renderer so
// the read view and the editor highlight identically:
//   • editable → a transparent <textarea> sits on top of a styled backdrop;
//     the backdrop is what you actually read (it carries the highlights), the
//     textarea only captures keystrokes + caret + selection.
//   • read-only → just the backdrop.
// Because the visible text is always the backdrop, highlights can never drift
// out from under the caret.

type HighlightFieldProps = {
  value: string;
  onChange?: (next: string) => void;
  editable: boolean;
  serif?: boolean;
  placeholder?: string;
  ariaLabel?: string;
  maxLength?: number;
  minRows?: number;
};

// Typography + box metrics MUST match byte-for-byte between backdrop and
// textarea or the caret sits off the glyphs. Both layers carry these; the
// single visible border lives on the wrapper so neither layer offsets the other.
const SHARED_BOX = "block w-full whitespace-pre-wrap break-words px-3 py-2";

function renderSegments(value: string, spans: TellSpan[]) {
  // A trailing newline collapses the backdrop's last line; a zero-width space
  // keeps its height in lockstep with the textarea.
  const padded = value.endsWith("\n") ? value + "​" : value;
  const segments = segmentByTells(padded, spans);
  return segments.map((seg, i) =>
    seg.tell ? (
      <mark
        key={i}
        title={seg.tell.label}
        className="bg-transparent text-status-failed underline decoration-status-failed decoration-wavy underline-offset-4"
      >
        {seg.text}
      </mark>
    ) : (
      <span key={i}>{seg.text}</span>
    ),
  );
}

export function HighlightField({
  value,
  onChange,
  editable,
  serif = false,
  placeholder,
  ariaLabel,
  maxLength,
  minRows = 1,
}: HighlightFieldProps) {
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const { spans } = scanVoiceTells(value);

  // Auto-resize the textarea to its content (no inner scroll → no scroll sync).
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value, editable]);

  const typography = serif
    ? "font-serif text-xl leading-snug text-ink-hi"
    : "font-sans text-sm leading-relaxed text-ink-hi";

  const showPlaceholder = editable && value.length === 0 && placeholder;
  const minHeight: CSSProperties = {
    minHeight: `calc(${minRows} * 1.6em + 1rem)`,
  };

  const backdrop = (
    <div
      aria-hidden
      style={minHeight}
      className={`${SHARED_BOX} ${typography} pointer-events-none`}
    >
      {showPlaceholder ? (
        <span className="text-ink-lo">{placeholder}</span>
      ) : (
        renderSegments(value, spans)
      )}
    </div>
  );

  if (!editable) {
    return backdrop;
  }

  return (
    <div className="relative rounded-md border border-border bg-surface-2 focus-within:border-ink-lo">
      {backdrop}
      <textarea
        ref={taRef}
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        aria-label={ariaLabel}
        maxLength={maxLength}
        spellCheck
        style={minHeight}
        className={`${SHARED_BOX} ${typography} absolute inset-0 resize-none overflow-hidden border-0 bg-transparent text-transparent caret-ink-hi outline-none`}
      />
    </div>
  );
}
