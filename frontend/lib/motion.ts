// Shared, restrained motion vocabulary (DESIGN.md §3 — considered motion, not
// SaaS flourish). One easing, a short scale, a few reusable variants so the
// whole studio moves as one system. Every consumer should also respect
// `useReducedMotion()` from motion/react — these variants are small on purpose,
// and the CSS reduced-motion block in globals.css is the belt-and-braces layer.

import type { Variants, Transition } from "motion/react";

/** Editorial easing — a calm ease-out, no bounce. */
export const EASE: Transition["ease"] = [0.22, 1, 0.36, 1];

export const DUR = {
  fast: 0.18,
  base: 0.32,
  slow: 0.5,
} as const;

/** Section / panel reveal on mount or scroll-in. */
export const reveal: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: DUR.base, ease: EASE },
  },
};

/** Parent that staggers its children (list rows, funnel cells). */
export const stagger: Variants = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.05, delayChildren: 0.02 },
  },
};

/** A single staggered child (pairs with `stagger`). */
export const staggerItem: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: DUR.base, ease: EASE },
  },
};

/** Small pop for state changes (a pill flipping, a chip appearing). */
export const pop: Variants = {
  hidden: { opacity: 0, scale: 0.94 },
  show: {
    opacity: 1,
    scale: 1,
    transition: { duration: DUR.fast, ease: EASE },
  },
};
