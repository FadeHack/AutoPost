"use client";

import { useState } from "react";
import { ApiError, apiPatch } from "@/lib/api";
import { useMe, setCachedMe, type Me } from "@/lib/useMe";
import { useToast } from "@/components/ui/Toast";

// Rename the caller's own workspace — the name shown in the BrandSwitcher.
// One field, sits above the Connections/Prompts/Templates/Voice sub-nav since
// it's identity metadata, not a connection. Any role can rename their own
// workspace (display-only write, no tenant-isolation implications).

export default function WorkspaceName() {
  const { me } = useMe();
  const { notify } = useToast();
  const [value, setValue] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const current = value ?? me?.workspace_name ?? "";
  const dirty = me != null && value != null && value.trim() !== me.workspace_name;

  async function save() {
    if (!dirty || saving) return;
    const name = current.trim();
    if (!name) {
      setError("Name can't be blank.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const updated = await apiPatch<Me>("/me/workspace", { name });
      setCachedMe(updated);
      setValue(null);
      notify({ tone: "success", title: "Workspace renamed" });
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!me) return null;

  return (
    <section className="mb-8 rounded-md border border-border bg-surface-1 p-4">
      <h2 className="text-xs font-medium uppercase tracking-wide text-ink-lo">
        Workspace
      </h2>
      <p className="mt-1 text-sm text-ink-mid">
        The brand name shown in the switcher and across the studio.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={current}
          onChange={(e) => setValue(e.target.value)}
          maxLength={255}
          disabled={saving}
          className="min-w-0 flex-1 rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm text-ink-hi outline-none focus:border-accent"
        />
        <button
          type="button"
          onClick={save}
          disabled={!dirty || saving}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-ink transition-opacity disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-status-failed">{error}</p>}
    </section>
  );
}
