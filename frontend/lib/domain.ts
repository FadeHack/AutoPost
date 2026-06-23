// Single source of truth for the domain vocabulary the UI renders (DESIGN.md §4).
// Status/category/platform types + their labels + the per-platform char caps —
// previously duplicated across drafts/scheduled/published. The component kit
// (StatusPill, CategoryChip, PlatformBadge, CharBudgetMeter) reads from here so
// there is exactly one place to change a label or a cap.

export type PostStatus =
  | "draft"
  | "approved"
  | "scheduled"
  | "publishing"
  | "published"
  | "failed";

export type PostCategory =
  | "founder_insight"
  | "engineering_lesson"
  | "ai_automation"
  | "startup_opinion"
  | "technical_humor"
  | "carousel"
  | "dev_tooling"
  | "pricing_business_model"
  | "product_postmortem"
  | "design_thinking";

export type Platform =
  | "linkedin"
  | "bluesky"
  | "mastodon"
  | "threads"
  | "instagram";

export const CATEGORY_LABEL: Record<PostCategory, string> = {
  founder_insight: "Founder insight",
  engineering_lesson: "Engineering lesson",
  ai_automation: "AI automation",
  startup_opinion: "Startup opinion",
  technical_humor: "Technical humor",
  carousel: "Carousel",
  dev_tooling: "Dev tooling",
  pricing_business_model: "Pricing & business model",
  product_postmortem: "Product postmortem",
  design_thinking: "Design thinking",
};

// Categories the operator can generate (technical_humor/carousel are latent —
// no seeded prompts; see CONTEXT.md Phase 12).
export const GENERATABLE: PostCategory[] = [
  "founder_insight",
  "engineering_lesson",
  "ai_automation",
  "startup_opinion",
  "dev_tooling",
  "pricing_business_model",
  "product_postmortem",
  "design_thinking",
];

export const PLATFORM_LABEL: Record<Platform, string> = {
  linkedin: "LinkedIn",
  bluesky: "Bluesky",
  mastodon: "Mastodon",
  threads: "Threads",
  instagram: "Instagram",
};

// Mirrors each backend Publisher.char_limit exactly — keep in sync.
export const PLATFORM_LIMITS: Record<Platform, number> = {
  linkedin: 3000,
  bluesky: 300,
  mastodon: 500,
  threads: 500,
  instagram: 2200,
};
