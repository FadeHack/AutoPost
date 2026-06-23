// Client-side mirror of the backend founder-voice scanner
// (`backend/app/intelligence/voice.py :: strip_ai_tells`). The backend strips
// these tells at generate-time; this re-runs the *detection* half live as the
// operator edits so the cockpit can flag them inline (DESIGN.md §5C / §7 —
// "voice quality you can see and edit"). Detection only: we never rewrite here,
// the human does. Keep the phrase list in lockstep with voice.py.

// Banned phrases — exact mirror of voice.py `_BANNED_PHRASES`, lowercased.
export const BANNED_PHRASES: readonly string[] = [
  "delve",
  "moreover",
  "furthermore",
  "it's worth noting",
  "is also worth noting",
  "is worth noting",
  "in today's fast-paced world",
  "navigating the complexities of",
  "i hope this helps",
  "feel free to",
  "it could be argued",
  "one might say",
  "sparked my interest",
  "this got me thinking",
  "got me thinking",
  "i've seen many teams",
  "i've watched many teams",
  "i've seen countless",
  "i've worked with many",
  "i think the problem lies",
  "one notable aspect",
  "the approach used by",
  "this design choice",
  "valuable lesson for anyone",
];

// Mirror of voice.py `_SUMMARY_OPENERS` — a paragraph that opens with one of
// these is the banned closing-summary tell.
const SUMMARY_OPENERS: readonly string[] = [
  "in summary",
  "in conclusion",
  "to summarize",
  "to conclude",
  "in essence",
  "ultimately,",
  "to sum up",
];

export type TellKind = "em_dash_separator" | "closing_summary" | "banned_phrase";

// One flagged span in the source text. `[start, end)` indexes the raw string so
// the highlight overlay can slice around it.
export type TellSpan = {
  start: number;
  end: number;
  kind: TellKind;
  label: string;
};

export type VoiceScan = {
  spans: TellSpan[];
  // Count matching voice.py's `len(violations)`: em-dash counts once, closing
  // summary once, and each *distinct* banned phrase once — regardless of how
  // many times it occurs. This is the number the VoiceQualityChip shows.
  count: number;
};

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const EM_DASH = /—/g;

/**
 * Scan text for founder-voice tells. Returns every occurrence as a span (for
 * inline highlighting) plus a deduplicated `count` (for the quality chip).
 */
export function scanVoiceTells(text: string): VoiceScan {
  if (!text) return { spans: [], count: 0 };

  const spans: TellSpan[] = [];
  const kinds = new Set<string>();

  // Em-dash-as-separator — the single loudest tell. Highlight each dash glyph.
  for (const m of text.matchAll(EM_DASH)) {
    spans.push({
      start: m.index,
      end: m.index + m[0].length,
      kind: "em_dash_separator",
      label: "Em-dash separator — use a period or line break",
    });
    kinds.add("em_dash_separator");
  }

  // Banned phrases — case-insensitive, every occurrence highlighted, but each
  // distinct phrase counts once toward the chip.
  for (const phrase of BANNED_PHRASES) {
    const re = new RegExp(escapeRegExp(phrase), "gi");
    let found = false;
    for (const m of text.matchAll(re)) {
      spans.push({
        start: m.index,
        end: m.index + m[0].length,
        kind: "banned_phrase",
        label: `Banned phrase: "${phrase}"`,
      });
      found = true;
    }
    if (found) kinds.add(`banned:${phrase}`);
  }

  // Closing-summary paragraph — a paragraph whose first non-space text opens
  // with a summary phrase. Walk paragraphs while tracking absolute offsets.
  let offset = 0;
  for (const para of text.split(/(\n\s*\n)/)) {
    // split keeps the separators (odd indices); only inspect real paragraphs.
    const lead = para.replace(/^\s*/, "");
    const leadStart = offset + (para.length - lead.length);
    const lower = lead.toLowerCase();
    const opener = SUMMARY_OPENERS.find((o) => lower.startsWith(o));
    if (opener) {
      spans.push({
        start: leadStart,
        end: leadStart + opener.length,
        kind: "closing_summary",
        label: "Closing summary — cut it; end on the strongest line",
      });
      kinds.add("closing_summary");
    }
    offset += para.length;
  }

  spans.sort((a, b) => a.start - b.start || b.end - a.end);
  return { spans, count: kinds.size };
}

// Segment a string into plain/flagged runs for rendering. Overlapping spans
// (rare — a banned phrase containing an em-dash) collapse to the first; we
// advance past whatever we've already emitted so indices never cross.
export type TextSegment = { text: string; tell: TellSpan | null };

export function segmentByTells(text: string, spans: TellSpan[]): TextSegment[] {
  if (spans.length === 0) return [{ text, tell: null }];
  const segments: TextSegment[] = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor) continue; // swallowed by a prior overlapping span
    if (span.start > cursor) {
      segments.push({ text: text.slice(cursor, span.start), tell: null });
    }
    segments.push({ text: text.slice(span.start, span.end), tell: span });
    cursor = span.end;
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), tell: null });
  }
  return segments;
}
