"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiGet } from "@/lib/api";
import { Banner } from "@/components/ui/Banner";

// Templates surface (DESIGN.md §5G). Visual templates are HTML files + a
// `templates` row; the renderer picks one per post at render time. There's no
// per-template `is_active` flag (selection is per-post, not global), so this is
// a read-only registry — confirm what's installed, preview the thumbnail.
// Adding a template is still "drop an HTML file + insert a row" (CLAUDE.md).

type TemplateCategory = "quote" | "insight" | "metric" | "carousel";

type Template = {
  id: string;
  name: string;
  category: TemplateCategory;
  html_path: string;
  thumbnail_url: string | null;
};

export default function Templates() {
  const { session } = useAuth();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchTemplates = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      setTemplates(await apiGet<Template[]>("/templates"));
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  if (loading) return <p className="text-sm text-ink-lo">Loading templates…</p>;

  return (
    <div className="space-y-6">
      {error && <Banner tone="error">{error}</Banner>}

      <p className="text-sm text-ink-mid">
        Installed visual templates. The renderer picks one per post at render
        time. Adding a template = drop an HTML file + insert a row.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {templates.map((t) => (
          <div
            key={t.id}
            className="overflow-hidden rounded-lg border border-border bg-surface-1"
          >
            <div className="flex aspect-video items-center justify-center bg-surface-2">
              {t.thumbnail_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={t.thumbnail_url}
                  alt={t.name}
                  className="h-full w-full object-cover"
                />
              ) : (
                <span className="text-xs text-ink-lo">No preview</span>
              )}
            </div>
            <div className="space-y-1 p-3">
              <p className="text-sm font-medium text-ink-hi">{t.name}</p>
              <div className="flex items-center justify-between text-xs text-ink-lo">
                <span className="capitalize">{t.category}</span>
                <span className="font-mono">{t.html_path}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {templates.length === 0 && !error && (
        <p className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-ink-lo">
          No templates installed.
        </p>
      )}
    </div>
  );
}
