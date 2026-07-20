// A web-scaled replica of the rendered post card (backend
// `rendering/templates/quote_card.html`) — black field, serif italic pull-quote,
// giant open-quote glyph, hairline rule above an uppercase brand strap. This is
// the literal artifact the studio ships; putting it on the landing is the whole
// "the tool looks like what it produces" thesis (DESIGN.md §3), not decoration.

export function PostCardMock({
  eyebrow = "Founder insight",
  quote = "Ship the boring version first. The clever one is a bet you haven’t earned yet.",
  brand = "Nestwhirr",
  className = "",
}: {
  eyebrow?: string;
  quote?: string;
  brand?: string;
  className?: string;
}) {
  return (
    <div
      className={
        "flex aspect-square w-full flex-col justify-between rounded-lg border border-white/10 bg-black p-8 sm:p-10 " +
        className
      }
    >
      <div className="font-sans text-[11px] uppercase tracking-[0.22em] text-zinc-500">
        {eyebrow}
      </div>

      <div className="flex flex-col">
        <div
          aria-hidden
          className="select-none font-serif text-7xl leading-none text-zinc-700"
        >
          &ldquo;
        </div>
        <p className="-mt-3 font-serif text-2xl italic leading-snug tracking-tight text-zinc-50 sm:text-[28px]">
          {quote}
        </p>
      </div>

      <div>
        <div className="mb-4 h-px w-12 bg-zinc-600" />
        <div className="font-sans text-[11px] uppercase tracking-[0.22em] text-zinc-400">
          {brand}
        </div>
      </div>
    </div>
  );
}
