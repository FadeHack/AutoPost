"use client";

/**
 * LinkedInPreview — mimics the LinkedIn feed card so the operator can see
 * roughly how the post will land before approving.
 *
 * Not pixel-perfect. The signal we want is: line breaks render correctly,
 * hashtags read like LinkedIn hashtags, and the image/carousel hangs where
 * the actual one will. Author name/title are placeholders since we don't
 * store the LinkedIn profile display name yet — that lands in Phase 6 when
 * the publisher needs it anyway.
 */

type LinkedInPreviewProps = {
  hook: string;
  body: string;
  tags: string[];
  imageUrl: string | null;
  // Ordered slide list for carousel posts. When provided, the preview shows
  // slide 1 with a "1 / N" badge and a swipe-affordance line.
  carousel?: { url: string }[] | null;
  authorName?: string;
  authorTitle?: string;
};

function Avatar({ name }: { name: string }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
  return (
    <div className="w-12 h-12 rounded-full bg-gradient-to-br from-sky-600 to-indigo-700 flex items-center justify-center text-white font-semibold text-base flex-shrink-0">
      {initials || "?"}
    </div>
  );
}

export default function LinkedInPreview({
  hook,
  body,
  tags,
  imageUrl,
  carousel,
  authorName = "Your name",
  authorTitle = "Founder · Nestwhirr",
}: LinkedInPreviewProps) {
  const commentary = [hook.trim(), body.trim()].filter(Boolean).join("\n\n");
  const carouselSlides = carousel ?? null;
  const showCarousel = carouselSlides !== null && carouselSlides.length > 1;
  const heroImageUrl = showCarousel
    ? (carouselSlides as { url: string }[])[0]?.url
    : imageUrl;

  return (
    <div className="rounded-lg border border-zinc-300 bg-white text-zinc-900 shadow-sm overflow-hidden font-sans">
      {/* Header */}
      <div className="flex items-start gap-3 px-4 pt-3 pb-2">
        <Avatar name={authorName} />
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-[15px] leading-tight truncate">
            {authorName}
            <span className="ml-1 text-xs text-zinc-500 font-normal">
              · 1st
            </span>
          </p>
          <p className="text-xs text-zinc-600 leading-tight truncate">
            {authorTitle}
          </p>
          <p className="text-xs text-zinc-500 mt-0.5 leading-tight">
            now · <span aria-label="public">🌐</span>
          </p>
        </div>
        <button
          type="button"
          aria-label="More"
          className="text-zinc-500 hover:text-zinc-700 text-xl leading-none px-2"
        >
          ⋯
        </button>
      </div>

      {/* Body */}
      <div className="px-4 pb-2 text-[14px] leading-relaxed text-zinc-900">
        <p className="whitespace-pre-wrap break-words">{commentary}</p>
        {tags.length > 0 && (
          <p className="mt-3">
            {tags.map((t, i) => (
              <span key={t}>
                {i > 0 && " "}
                <span className="text-[#0a66c2] font-medium hover:underline cursor-pointer">
                  #{t}
                </span>
              </span>
            ))}
          </p>
        )}
      </div>

      {/* Image / carousel */}
      {heroImageUrl && (
        <div className="relative bg-black">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={heroImageUrl}
            alt="Post visual"
            className="block w-full"
          />
          {showCarousel && (
            <>
              <span className="absolute top-2 right-2 rounded bg-black/70 text-white text-[11px] px-2 py-0.5 font-medium">
                1 / {(carouselSlides as { url: string }[]).length}
              </span>
              <span className="absolute bottom-2 right-2 rounded bg-black/60 text-white text-[10px] px-2 py-0.5">
                swipe →
              </span>
            </>
          )}
        </div>
      )}

      {/* Reactions stub */}
      <div className="px-4 pt-2 pb-1 flex items-center gap-1 text-xs text-zinc-600 border-t border-zinc-100">
        <span className="flex -space-x-1">
          <span className="w-4 h-4 rounded-full bg-[#0a66c2] flex items-center justify-center text-[9px] text-white">
            👍
          </span>
          <span className="w-4 h-4 rounded-full bg-rose-500 flex items-center justify-center text-[9px] text-white">
            ❤
          </span>
        </span>
        <span className="ml-1">42</span>
        <span className="ml-auto">7 comments · 3 reposts</span>
      </div>

      {/* Action bar */}
      <div className="grid grid-cols-4 border-t border-zinc-200 text-zinc-600 text-[13px] font-medium">
        {["Like", "Comment", "Repost", "Send"].map((label) => (
          <button
            key={label}
            type="button"
            className="py-2 hover:bg-zinc-100 transition"
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
