"use client";

import { BANNED_PHRASES } from "@/lib/voice";

// Voice rules surface (DESIGN.md §5G). The founder-voice guardrails are CODE,
// not DB rows: the post-processor `strip_ai_tells` (backend voice.py, mirrored
// in lib/voice.ts) and the prompts enforce them. So this is a read-only
// reference — the same banned-phrase list that drives the cockpit's live
// inline flagging, plus the structural rules from CLAUDE.md. Editing them is a
// code change on purpose (voice quality stays controlled, not user-tunable).

const STRUCTURAL_RULES = [
  "Hook in the first line — must work alone, before “see more”.",
  "Short lines (≤ 12 words). Line breaks for breathing room.",
  "No closing summary paragraph.",
  "Max 3 hashtags, lowercase, at the end.",
  "One opinion per post, not a survey.",
];

const FORMATTING_TELLS = [
  "Em-dash used as a separator → use a period or line break.",
  "Triple-bullet lists with no narrative.",
  "Closing summary openers (“in conclusion”, “to summarize”…).",
];

export default function VoiceRules() {
  return (
    <div className="space-y-8">
      <p className="text-sm text-ink-mid">
        The founder-voice guardrails. These are enforced in code — the output
        post-processor strips them and the cockpit flags them live as you edit.
        Changing them is a deliberate code change, so voice quality stays
        controlled.
      </p>

      <section>
        <h2 className="mb-3 text-sm font-medium text-ink-hi">
          Banned phrases{" "}
          <span className="text-ink-lo">({BANNED_PHRASES.length})</span>
        </h2>
        <div className="flex flex-wrap gap-1.5">
          {BANNED_PHRASES.map((phrase) => (
            <span
              key={phrase}
              className="rounded-full border border-status-failed/30 bg-status-failed/5 px-2 py-0.5 text-xs text-status-failed"
            >
              {phrase}
            </span>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium text-ink-hi">
          Punctuation / formatting tells
        </h2>
        <ul className="space-y-1.5 text-sm text-ink-mid">
          {FORMATTING_TELLS.map((r) => (
            <li key={r} className="flex gap-2">
              <span className="text-ink-lo">·</span>
              {r}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium text-ink-hi">
          Structural rules for every post
        </h2>
        <ul className="space-y-1.5 text-sm text-ink-mid">
          {STRUCTURAL_RULES.map((r) => (
            <li key={r} className="flex gap-2">
              <span className="text-ink-lo">·</span>
              {r}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
