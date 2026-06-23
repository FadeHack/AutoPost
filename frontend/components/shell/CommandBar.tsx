"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost } from "@/lib/api";
import { useToast } from "@/components/ui/Toast";

// ⌘K / Ctrl-K palette (DESIGN.md §4) — keyboard-first navigation + safe actions
// for a daily expert tool. Navigation jumps + a couple of low-risk actions
// (generate routes to drafts; refresh trends hits the manual endpoint).

type Command = {
  id: string;
  label: string;
  hint?: string;
  run: () => void | Promise<void>;
};

export function CommandBar() {
  const router = useRouter();
  const { notify } = useToast();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const commands: Command[] = useMemo(() => {
    const go = (href: string) => () => {
      router.push(href);
      setOpen(false);
    };
    return [
      { id: "today", label: "Go to Today", run: go("/") },
      { id: "inbox", label: "Go to Inbox", hint: "trends", run: go("/trends") },
      { id: "drafts", label: "Go to Drafts", run: go("/drafts") },
      { id: "calendar", label: "Go to Calendar", hint: "scheduled", run: go("/scheduled") },
      { id: "published", label: "Go to Published", run: go("/published") },
      { id: "settings", label: "Go to Settings", run: go("/settings") },
      { id: "generate", label: "Generate a draft", hint: "action", run: go("/drafts") },
      {
        id: "refresh",
        label: "Refresh trends",
        hint: "action",
        run: async () => {
          setOpen(false);
          try {
            await apiPost("/trends/refresh");
            notify({ tone: "success", title: "Trend refresh started" });
          } catch {
            notify({ tone: "error", title: "Couldn't refresh trends" });
          }
        },
      },
    ];
  }, [router, notify]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter(
      (c) =>
        c.label.toLowerCase().includes(q) ||
        (c.hint ?? "").toLowerCase().includes(q),
    );
  }, [commands, query]);

  // Global ⌘K / Ctrl-K toggle.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSel(0);
      // Focus after paint.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => {
    setSel(0);
  }, [query]);

  if (!open) return null;

  const onInputKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      filtered[sel]?.run();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-4 pt-[15vh]"
      onMouseDown={() => setOpen(false)}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-lg border border-border bg-surface-1 shadow-2xl shadow-black/70"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onInputKey}
          placeholder="Search commands…"
          className="w-full border-b border-border bg-transparent px-4 py-3 text-sm text-ink-hi outline-none placeholder:text-ink-lo"
        />
        <ul className="max-h-72 overflow-y-auto py-1">
          {filtered.length === 0 && (
            <li className="px-4 py-3 text-sm text-ink-lo">No matches</li>
          )}
          {filtered.map((c, i) => (
            <li key={c.id}>
              <button
                onMouseEnter={() => setSel(i)}
                onClick={() => c.run()}
                className={
                  "flex w-full items-center justify-between px-4 py-2 text-left text-sm " +
                  (i === sel ? "bg-surface-2 text-ink-hi" : "text-ink-mid")
                }
              >
                <span>{c.label}</span>
                {c.hint && (
                  <span className="text-xs text-ink-lo">{c.hint}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
