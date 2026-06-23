"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { Banner } from "@/components/ui/Banner";
import { CategoryChip } from "@/components/ui/CategoryChip";
import { PlatformBadge } from "@/components/ui/PlatformBadge";
import { useToast } from "@/components/ui/Toast";
import { type Platform, type PostCategory } from "@/lib/domain";

// Prompts surface (DESIGN.md §5G). The generator resolves a prompt by
// (name, platform, is_active) — so this lists the versioned matrix grouped by
// that key and lets the operator flip which version is live. Read + activate
// only: authoring bodies stays a migration concern (anchor examples are how
// voice quality is held; see CLAUDE.md). "Voice tuning = a DB write, not a deploy."

type Prompt = {
  id: string;
  name: string;
  category: PostCategory;
  platform: Platform | null;
  body: string;
  version: number;
  is_active: boolean;
};

export default function Prompts() {
  const { session } = useAuth();
  const { notify } = useToast();

  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activatingId, setActivatingId] = useState<string | null>(null);

  const fetchPrompts = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      setPrompts(await apiGet<Prompt[]>("/prompts"));
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    fetchPrompts();
  }, [fetchPrompts]);

  // Group by the generator's lookup key: (name, platform).
  const groups = useMemo(() => {
    const map = new Map<string, Prompt[]>();
    for (const p of prompts) {
      const key = `${p.name}|${p.platform ?? "any"}`;
      const arr = map.get(key) ?? [];
      arr.push(p);
      map.set(key, arr);
    }
    return Array.from(map.entries())
      .map(([key, items]) => ({
        key,
        items: [...items].sort((a, b) => b.version - a.version),
      }))
      .sort((a, b) => a.key.localeCompare(b.key));
  }, [prompts]);

  const activate = async (p: Prompt) => {
    setActivatingId(p.id);
    setError("");
    try {
      await apiPost<Prompt>(`/prompts/${p.id}/activate`, {});
      // Flip is_active within the (name, platform) group locally.
      setPrompts((prev) =>
        prev.map((x) =>
          x.name === p.name && x.platform === p.platform
            ? { ...x, is_active: x.id === p.id }
            : x,
        ),
      );
      notify({ tone: "success", title: `Activated v${p.version}`, body: p.name });
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setActivatingId(null);
    }
  };

  if (loading) return <p className="text-sm text-ink-lo">Loading prompts…</p>;

  return (
    <div className="space-y-6">
      {error && <Banner tone="error">{error}</Banner>}

      <p className="text-sm text-ink-mid">
        The versioned prompt matrix the generator reads. Activating a version
        makes it live for its name + platform — no deploy.
      </p>

      {groups.map((g) => {
        const first = g.items[0];
        return (
          <section
            key={g.key}
            className="rounded-lg border border-border bg-surface-1 p-4"
          >
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm text-ink-hi">{first.name}</span>
              {first.platform ? (
                <PlatformBadge platform={first.platform} />
              ) : (
                <span className="rounded-full border border-border px-2 py-0.5 text-xs text-ink-lo">
                  any platform
                </span>
              )}
              <CategoryChip category={first.category} />
            </div>

            <div className="space-y-2">
              {g.items.map((p) => (
                <div
                  key={p.id}
                  className={
                    "rounded-md border p-3 " +
                    (p.is_active
                      ? "border-status-published/40 bg-status-published/5"
                      : "border-border")
                  }
                >
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2 text-xs">
                      <span className="font-medium text-ink-hi">
                        v{p.version}
                      </span>
                      {p.is_active && (
                        <span className="rounded-full border border-status-published/30 bg-status-published/10 px-2 py-0.5 text-status-published">
                          live
                        </span>
                      )}
                    </span>
                    {!p.is_active && (
                      <button
                        type="button"
                        onClick={() => activate(p)}
                        disabled={activatingId === p.id}
                        className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-ink-mid hover:text-ink-hi disabled:opacity-50"
                      >
                        {activatingId === p.id ? "Activating…" : "Activate"}
                      </button>
                    )}
                  </div>
                  <details className="text-xs text-ink-mid">
                    <summary className="cursor-pointer select-none text-ink-lo hover:text-ink-mid">
                      View body
                    </summary>
                    <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-surface-2 p-3 font-mono leading-relaxed text-ink-mid">
                      {p.body}
                    </pre>
                  </details>
                </div>
              ))}
            </div>
          </section>
        );
      })}

      {groups.length === 0 && !error && (
        <p className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-ink-lo">
          No prompts seeded.
        </p>
      )}
    </div>
  );
}
