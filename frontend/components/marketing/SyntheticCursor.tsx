"use client";

import { motion } from "motion/react";
import { EASE } from "@/lib/motion";

// A scripted, on-screen pointer for the walkthrough — an absolutely-positioned
// element (never the OS cursor) that glides between targets and pulses on
// "click". Coordinates are relative to the walkthrough stage. Hidden entirely
// in manual mode and for reduced-motion users.

export function SyntheticCursor({
  x,
  y,
  clicking,
  visible,
}: {
  x: number;
  y: number;
  clicking: boolean;
  visible: boolean;
}) {
  return (
    <motion.div
      aria-hidden
      className="pointer-events-none absolute left-0 top-0 z-40"
      initial={false}
      animate={{ x, y, opacity: visible ? 1 : 0 }}
      transition={{ x: { duration: 0.7, ease: EASE }, y: { duration: 0.7, ease: EASE }, opacity: { duration: 0.25 } }}
    >
      {/* Click ripple */}
      <motion.span
        className="absolute -left-1 -top-1 h-8 w-8 rounded-full border border-accent"
        initial={{ scale: 0, opacity: 0 }}
        animate={clicking ? { scale: 1.1, opacity: [0, 0.6, 0] } : { scale: 0, opacity: 0 }}
        transition={{ duration: 0.4, ease: EASE }}
      />
      {/* Arrow pointer */}
      <motion.svg
        width="22"
        height="22"
        viewBox="0 0 22 22"
        className="drop-shadow-[0_1px_2px_rgba(0,0,0,0.5)]"
        animate={{ scale: clicking ? 0.82 : 1 }}
        transition={{ duration: 0.12, ease: EASE }}
      >
        <path
          d="M4 3l13 6.5-5.4 1.6L9 17 4 3z"
          className="fill-ink-hi stroke-bg"
          strokeWidth="1.2"
          strokeLinejoin="round"
        />
      </motion.svg>
    </motion.div>
  );
}
