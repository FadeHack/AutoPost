"use client";

import { useMemo, useState } from "react";

type SchedulePickerProps = {
  /** Pre-populate with an existing scheduled time (e.g. when rescheduling). */
  initialScheduledAt?: string | null;
  scheduling: boolean;
  /** Receives an ISO 8601 string with timezone offset. */
  onSchedule: (isoUtc: string) => void | Promise<void>;
  onCancel: () => void;
};

/**
 * Returns a string in the `YYYY-MM-DDTHH:mm` shape that <input type="datetime-local">
 * accepts, expressed in the LOCAL timezone (not UTC). The input is always naive
 * local — we only translate to UTC when submitting.
 */
function toDatetimeLocal(date: Date): string {
  const pad = (n: number) => n.toString().padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

function defaultLocalValue(initial?: string | null): string {
  if (initial) {
    const d = new Date(initial);
    if (!Number.isNaN(d.getTime())) return toDatetimeLocal(d);
  }
  // Default: now + 15 minutes, rounded up to the next 5-minute mark.
  const d = new Date();
  d.setMinutes(d.getMinutes() + 15);
  d.setMinutes(Math.ceil(d.getMinutes() / 5) * 5);
  d.setSeconds(0, 0);
  return toDatetimeLocal(d);
}

function describeRelative(target: Date): string {
  const diffMs = target.getTime() - Date.now();
  if (diffMs <= 0) return "in the past";
  const mins = Math.round(diffMs / 60_000);
  if (mins < 60) return `in ${mins} min`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `in ${hrs} hr`;
  const days = Math.round(hrs / 24);
  return `in ${days} day${days === 1 ? "" : "s"}`;
}

export default function SchedulePicker({
  initialScheduledAt,
  scheduling,
  onSchedule,
  onCancel,
}: SchedulePickerProps) {
  const [value, setValue] = useState(() => defaultLocalValue(initialScheduledAt));

  const parsed = useMemo(() => {
    if (!value) return null;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }, [value]);

  // Backend rejects anything within 60s. Mirror that here so the user sees
  // an inline error before they click, plus a small buffer for clock skew.
  const minMs = Date.now() + 70_000;
  const tooSoon = parsed !== null && parsed.getTime() < minMs;
  const canSubmit = parsed !== null && !tooSoon && !scheduling;

  const localTzLabel = useMemo(
    () =>
      Intl.DateTimeFormat().resolvedOptions().timeZone ||
      `UTC${new Date().getTimezoneOffset() <= 0 ? "+" : "-"}${Math.abs(new Date().getTimezoneOffset() / 60)}`,
    []
  );

  const handleSchedule = () => {
    if (!parsed || !canSubmit) return;
    // Send an explicit UTC ISO string — `new Date(local).toISOString()` is
    // already UTC. Backend parses with pydantic; naive datetimes get UTC
    // tagged, so this is unambiguous either way.
    onSchedule(parsed.toISOString());
  };

  return (
    <section className="rounded border border-zinc-700 bg-zinc-950/70 p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xs uppercase tracking-wider text-zinc-400">
          {initialScheduledAt ? "Reschedule" : "Schedule"}
        </h2>
        <span className="text-xs text-zinc-500">Local: {localTzLabel}</span>
      </div>

      <div className="space-y-2">
        <label
          htmlFor="schedule-at"
          className="block text-xs uppercase tracking-wider text-zinc-500"
        >
          When should this post?
        </label>
        <input
          id="schedule-at"
          type="datetime-local"
          value={value}
          step={60}
          onChange={(e) => setValue(e.target.value)}
          className="w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
        />
        {parsed && (
          <p
            className={`text-xs ${tooSoon ? "text-amber-400" : "text-zinc-500"}`}
          >
            {tooSoon
              ? "Pick at least ~1 minute in the future."
              : `${parsed.toLocaleString()} · ${describeRelative(parsed)}`}
          </p>
        )}
      </div>

      <div className="flex items-center gap-3 pt-1">
        <button
          type="button"
          onClick={handleSchedule}
          disabled={!canSubmit}
          className="rounded bg-blue-600 text-white font-medium px-4 py-2 text-sm hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {scheduling
            ? "Saving…"
            : initialScheduledAt
              ? "Update schedule"
              : "Schedule"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={scheduling}
          className="rounded border border-zinc-700 text-zinc-300 px-4 py-2 text-sm hover:border-zinc-500 disabled:opacity-40"
        >
          Cancel
        </button>
      </div>
    </section>
  );
}
