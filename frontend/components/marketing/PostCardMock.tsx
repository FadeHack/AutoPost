// A web-scaled replica of the rendered post card (backend
// `rendering/templates/quote_card.html`) — black field, Newsreader italic
// pull-quote, giant open-quote glyph, hairline rule above an uppercase brand
// strap. This is the literal artifact the studio ships; putting it on the
// landing (and inside the live walkthrough as the draft "renders") is the whole
// "the tool looks like what it produces" thesis (DESIGN.md §3), not decoration.
// The card is ALWAYS dark — the product's output identity is fixed, so it does
// not follow the app's light/dark theme.

export function PostCardMock({
  eyebrow = "Founder insight",
  quote = "Ship the boring version first. The clever one is a bet you haven’t earned yet.",
  brand = "Nestwhirr",
  compact = false,
  className = "",
}: {
  eyebrow?: string;
  quote?: string;
  brand?: string;
  /** Tighter padding + smaller type for embedding in the walkthrough cockpit. */
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      className={
        "flex aspect-square w-full flex-col justify-between rounded-lg border border-white/10 bg-black " +
        (compact ? "p-5" : "p-8 sm:p-10") +
        " " +
        className
      }
    >
      <div
        className={
          "font-sans uppercase text-zinc-500 " +
          (compact
            ? "text-[9px] tracking-[0.2em]"
            : "text-[11px] tracking-[0.22em]")
        }
      >
        {eyebrow}
      </div>

      <div className="flex flex-col">
        <div
          aria-hidden
          className={
            "select-none font-serif leading-none text-zinc-700 " +
            (compact ? "text-4xl" : "text-7xl")
          }
        >
          &ldquo;
        </div>
        <p
          className={
            "font-serif italic leading-snug tracking-tight text-zinc-50 " +
            (compact ? "-mt-2 text-base" : "-mt-3 text-2xl sm:text-[28px]")
          }
        >
          {quote}
        </p>
      </div>

      <div>
        <div
          className={
            "bg-zinc-600 " + (compact ? "mb-2.5 h-px w-8" : "mb-4 h-px w-12")
          }
        />
        <div
          className={
            "font-sans uppercase text-zinc-400 " +
            (compact
              ? "text-[9px] tracking-[0.2em]"
              : "text-[11px] tracking-[0.22em]")
          }
        >
          {brand}
        </div>
      </div>
    </div>
  );
}
