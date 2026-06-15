"use client";

import {
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type DraftEditorProps = {
  initialHook: string;
  initialBody: string;
  initialTags: string[];
  saving: boolean;
  onSave: (updates: {
    hook: string;
    body: string;
    tags: string[];
  }) => void | Promise<void>;
  onCancel: () => void;
};

function useAutoResize(value: string) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);
  return ref;
}

function arrayEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

export default function DraftEditor({
  initialHook,
  initialBody,
  initialTags,
  saving,
  onSave,
  onCancel,
}: DraftEditorProps) {
  const [hook, setHook] = useState(initialHook);
  const [body, setBody] = useState(initialBody);
  const [tags, setTags] = useState<string[]>(initialTags);
  const [tagDraft, setTagDraft] = useState("");

  const hookRef = useAutoResize(hook);
  const bodyRef = useAutoResize(body);

  const isDirty = useMemo(
    () =>
      hook !== initialHook ||
      body !== initialBody ||
      !arrayEqual(tags, initialTags),
    [hook, body, tags, initialHook, initialBody, initialTags]
  );

  const canSave =
    isDirty && !saving && hook.trim().length > 0 && body.trim().length > 0;

  const addTag = useCallback(
    (raw: string) => {
      const cleaned = raw.trim().replace(/^#+/, "").toLowerCase();
      if (!cleaned) return;
      if (tags.includes(cleaned)) return;
      setTags([...tags, cleaned]);
      setTagDraft("");
    },
    [tags]
  );

  const removeTag = (t: string) => setTags(tags.filter((x) => x !== t));

  const onTagKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(tagDraft);
    } else if (e.key === "Backspace" && tagDraft === "" && tags.length > 0) {
      // Backspace on empty input pops the last chip — common chip-input UX.
      e.preventDefault();
      setTags(tags.slice(0, -1));
    }
  };

  const handleSave = () => {
    if (!canSave) return;
    onSave({
      hook: hook.trim(),
      body: body.trim(),
      tags,
    });
  };

  return (
    <section className="rounded border border-zinc-700 bg-zinc-950/70 p-6 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xs uppercase tracking-wider text-zinc-400">
          Editing draft
        </h2>
        <span className="text-xs text-zinc-500">
          {isDirty ? "Unsaved changes" : "No changes"}
        </span>
      </div>

      <div className="space-y-2">
        <label
          htmlFor="hook-edit"
          className="block text-xs uppercase tracking-wider text-zinc-500"
        >
          Hook
        </label>
        <textarea
          id="hook-edit"
          ref={hookRef}
          value={hook}
          onChange={(e) => setHook(e.target.value)}
          rows={2}
          maxLength={512}
          className="w-full resize-none rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-base font-medium leading-snug focus:outline-none focus:border-zinc-500"
        />
        <p className="text-[11px] text-zinc-600 text-right">
          {hook.length} / 512
        </p>
      </div>

      <div className="space-y-2">
        <label
          htmlFor="body-edit"
          className="block text-xs uppercase tracking-wider text-zinc-500"
        >
          Body
        </label>
        <textarea
          id="body-edit"
          ref={bodyRef}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={8}
          className="w-full resize-none rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm leading-relaxed font-sans focus:outline-none focus:border-zinc-500"
        />
      </div>

      <div className="space-y-2">
        <label className="block text-xs uppercase tracking-wider text-zinc-500">
          Tags
        </label>
        <div className="flex flex-wrap items-center gap-2 rounded border border-zinc-700 bg-zinc-900 px-2 py-2 focus-within:border-zinc-500">
          {tags.map((t) => (
            <span
              key={t}
              className="inline-flex items-center gap-1 rounded bg-zinc-800 px-2 py-0.5 text-xs"
            >
              <span>#{t}</span>
              <button
                type="button"
                onClick={() => removeTag(t)}
                aria-label={`Remove tag ${t}`}
                className="text-zinc-500 hover:text-white"
              >
                ×
              </button>
            </span>
          ))}
          <input
            value={tagDraft}
            onChange={(e) => setTagDraft(e.target.value)}
            onKeyDown={onTagKeyDown}
            onBlur={() => addTag(tagDraft)}
            placeholder={tags.length === 0 ? "add a tag and press Enter" : ""}
            className="flex-1 min-w-[120px] bg-transparent px-1 py-0.5 text-xs focus:outline-none"
          />
        </div>
        <p className="text-[11px] text-zinc-600">
          Lowercase. Enter or comma to add. Backspace on empty input removes
          the last tag.
        </p>
      </div>

      <div className="flex items-center gap-3 pt-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={!canSave}
          className="rounded bg-white text-black font-medium px-4 py-2 text-sm hover:bg-zinc-200 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="rounded border border-zinc-700 text-zinc-300 px-4 py-2 text-sm hover:border-zinc-500 disabled:opacity-40"
        >
          Cancel
        </button>
      </div>
    </section>
  );
}
