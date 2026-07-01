# DESIGN.md — UI/UX Direction

**Product:** AutoPost — *by Nestwhirr*. "AutoPost" is the tool; "Nestwhirr" is the maker (vendor), and also the brand currently published-as (it appears as a selected brand in the switcher and on the rendered cards — never as the app name). Keep the two roles separate: the app is brand-neutral so the multi-company switcher holds.

The locked design direction for the AutoPost frontend. This is the **why and the shape** of the interface — read it before touching `frontend/`. It governs information architecture, visual language, the component kit, and per-screen blueprints. When a UI decision changes the direction, update this file in the same change (same rule as `CONTEXT.md`).

**Status:** Direction approved 2026-06-22. Not yet implemented — the current `frontend/` is the pre-redesign card-wall UI. This is the target.

**Decisions that shaped it (user-confirmed 2026-06-22):**
- Deliverable = written direction (this doc), build comes later.
- **Fully responsive** — every screen works on phone and desktop.
- **Multi-company is coming soon** — a brand/workspace switcher belongs in the IA now (not a later rewrite). Today it's a single static brand; the seam is what matters.

---

## What this product is (and the central design mistake to avoid)

This is **not** a multi-tenant SaaS dashboard, and designing it like one is the central mistake.

- **A single-operator editorial cockpit.** One power user, one company page (Nestwhirr) for now, run repeatedly. No customer onboarding, no billing surface. The user is an expert doing the *same loop* over and over.
- **A content pipeline with a hard status spine:** `trends → draft → approved → scheduled → published`, fanning out to 5 platforms (LinkedIn, Bluesky, Mastodon, Threads, Instagram) from one editorial decision. The value is **speed of the review loop + founder-voice quality + multi-platform fan-out from a single approve**.
- **A tool that produces a specific aesthetic** — the locked "minimal dark" Nestwhirr card identity (black bg, serif headline, sans body, accent line above brand strap). The app chrome must echo it.

### The differentiation thesis
The tool should look and behave like **the artifact it produces**: an editorial studio that wears the same identity as the cards it ships, not a Vercel-clone dashboard. Borrow the mental model from a **newsroom CMS / code editor** (single expert, keyboard-driven, status-pipeline, dense-but-calm) — *not* an analytics dashboard. The chrome adopts the same minimal-dark + serif-display identity as the rendered cards, so the studio feels like an extension of the brand. That single move is what makes it "intentionally designed for this product."

---

## 1. Design principles (the spine everything hangs on)

| Principle | Why it's true *for this product* |
|---|---|
| **The studio looks like the artifact** | The tool produces minimal-dark serif cards. The chrome adopts that identity so the app feels like the brand it publishes, not a template. This is the differentiation. |
| **One operator, expert mode** | No onboarding wizards. Optimize for a repeated loop done fast: density, keyboard, status-at-a-glance. Code editor / newsroom CMS, not analytics dashboard. |
| **The pipeline is the product** | `trends → draft → approved → scheduled → published` is a literal spine. The IA makes the funnel and "what needs me now" visible, not buried across disconnected pages. |
| **Voice quality is a first-class surface** | The whole philosophy is founder-voice-not-AI-spam. The backend already computes AI-tell violations (`strip_ai_tells`) — surface them. Make quality visible and editable, never hidden. |
| **Multi-platform is one decision, many shapes** | You approve once; it fans out to 5 platforms with different char budgets and rewrites. The UI shows "same idea, per-platform reality" side by side — that's the core review act. |

---

## 2. Information Architecture & Navigation

### The shift
Kill the current ~800-line home wall (`frontend/app/page.tsx`), which mixes *settings* (5 "Connect X" account cards) with *navigation* (Trends/Drafts/Scheduled/Published link cards). Split into three zones: a persistent **left rail** (navigation), a **brand switcher** (multi-company seam, now), and a content area. Configuration moves entirely into **Settings** — it is not daily work.

### Structure

```
┌────────────────────────────────────────────────────────────────┐
│ [◆ Nestwhirr ▾]  ← brand/workspace switcher (top of rail)       │
│                                                                  │
│  ● Today          ← command center / default landing            │
│  ◷ Inbox     (3)  ← trends, badge = unconsumed count            │
│  ✎ Drafts    (2)  ← pipeline board, badge = needs-action        │
│  ▤ Calendar       ← scheduled queue, time view                  │
│  ✓ Published       ← live history + (future) performance        │
│  ───────────────                                                 │
│  ⚙ Settings       ← connections, prompts, templates, voice      │
│                                                                  │
│  [token health pill]  ← LinkedIn day-60 expiry, always visible  │
│  [shivam@…  ▾]                                                   │
└────────────────────────────────────────────────────────────────┘
```

- **Left rail, not top tabs:** 5 pipeline stages + settings is too many for top tabs, and a vertical rail leaves full canvas width for side-by-side platform previews (which need width). Rails scale to a multi-company switcher gracefully.
- **Brand switcher lives now:** CLAUDE.md mandates multi-company without rewrites. A `[◆ Nestwhirr ▾]` switcher at the top of the rail makes the mental model "I'm working *inside a brand*," so brand #2 is a dropdown entry, not an IA redesign. Today it's one static entry — the seam is what matters.
- **Token-health pill is global chrome:** the biggest operational failure mode is the LinkedIn day-60 token death (refresh tokens are structurally unavailable — see `CONTEXT.md` / memory). That risk follows the operator everywhere. Amber ≤10d, red ≤3d — promote the existing `tokenExpiry()` logic to global chrome.
- **Badges = "what needs me":** Inbox badge = unconsumed trends; Drafts badge = posts in `draft`/`failed` awaiting action. Navigation becomes a worklist.

---

## 3. Visual Design Language & Branding

The rendered cards have a locked identity (minimal dark — black bg, serif headline, sans body, accent line above brand strap). **The app inherits it.** Replace the boilerplate `frontend/app/globals.css` (still default Next.js light/dark + Arial fallback) with intentional tokens.

### Tokens

```
Surface
  --bg          #0A0A0B   near-black (the card background, echoed)
  --surface-1   #0F0F11   raised panels
  --surface-2   #16161A   inputs, hover
  --border      #232328   hairline, low-contrast (calm density)

Ink
  --ink-hi      #F4F4F5   primary text
  --ink-mid     #A1A1AA   secondary
  --ink-lo      #52525B   metadata

Accent (the card's "accent line above brand strap" → system accent)
  --accent      #E8E1D3   warm off-white / parchment, paper-ink editorial tone
  (NOT SaaS electric-blue. The single strongest signal this isn't a generic dashboard.)

Status (semantic, sparing — the pipeline states)
  draft   neutral · approved parchment-accent · scheduled indigo
  publishing pulsing · published emerald · failed red
```

### Type
- **Display / headlines: a serif** (same family the cards use). Screen titles, the post hook in previews, empty states. The editorial signature.
- **Body / UI: Geist Sans** (already loaded). Keep.
- **Mono: Geist Mono** for URNs, tokens, error bodies, char counts.

The serif-for-display / sans-for-UI split *is* the brand — it mirrors the card construction, so the operator edits in the same visual language the output ships in.

### Texture
Flat, hairline-bordered, generous negative space. No drop shadows, no gradients (except the existing avatar-initials gradient). The restraint matches a brand whose voice rule is "strip the AI tells."

---

## 4. Design System & Component Patterns

A small, strict kit (consistency beats variety for a solo tool):

- **`StatusPill`** — pipeline state, one component, semantic color map. Single source of truth for status color (today the status/category color maps are duplicated across drafts/scheduled/published pages — consolidate).
- **`PlatformTab` / `PlatformBadge`** — per-platform identity chip with platform accent. Reused in the preview tab strip and on list rows to show fan-out targets at a glance.
- **`CharBudgetMeter`** — thin bar, chars-used vs the platform `char_limit`, amber when over. Makes the per-platform reality (Bluesky 300 vs LinkedIn 3000) visible instead of failing at publish. Drives the existing `PLATFORM_LIMITS`.
- **`VoiceQualityChip`** — surfaces `strip_ai_tells` violation count + whether the polish pass escalated. Green = clean, amber = N tells stripped. **The differentiator made visible.**
- **`CommandBar` (⌘K)** — generate draft, jump to a post, switch brand, refresh trends. Keyboard-first for a daily expert tool.
- **`ActionBar`** — the persistent draft action row (Edit / Render / Approve / Schedule / Publish now) with status-aware disable + tooltips. Exists implicitly in `drafts/[id]` today — formalize it.
- **`InlineToast` / `BannerStack`** — replace the ~8 ad-hoc result banners hand-rolled in `page.tsx`.

---

## 5. Per-screen blueprints

Each: **Goal · Layout · Key components · Rationale.**

### A. Today (command center) — replaces the home card wall
- **Goal:** In one glance answer "what needs me, and is the machine healthy?" then act in one click.
- **Layout:** three bands — (1) token-health banner only if amber/red; (2) three worklist counters (Needs review / Scheduled next / Published 7d); (3) the **pipeline funnel** strip (`Inbox → Draft → Approved → Scheduled → Live`), a peek at freshest trends, one primary "Generate a draft" CTA.
- **Components:** worklist counters (deep-links), pipeline funnel visualization, fresh-trends peek, primary CTA.
- **Rationale:** the current home makes you read 5 connection cards before working. A repeated loop should open on *the work*. The funnel is honest to the architecture and orients instantly. Connections move to Settings (touched ~once per 60 days).

### B. Inbox (Trends) — evolves `/trends`
- **Goal:** Triage fresh retrieval fast — judge, discard, or hand a trend straight into generation.
- **Layout:** dense scannable list (email-triage), not cards. Source + status filters in a left strip; rows keyboard-navigable (`j/k`, `e` consume, `g` generate-from-this).
- **Components:** source-coded badge, HN score, age, per-row **Generate →** (deep-links to the cockpit with this trend pre-selected), optimistic consume toggle.
- **Rationale:** trends are high-volume and disposable — "skim, judge, act" is a list, not a gallery. Per-row Generate collapses "read → remember → go to drafts → pick category → find trend again" into one click. Keeps the current filters + optimistic toggle.

### C. Draft Review Cockpit — the crown jewel, evolves `/drafts/[id]`
- **Goal:** Review one generated idea, verify the founder voice, see how it lands on every target platform, fix it, approve/schedule — without leaving the screen. ~80% of operator time lives here.
- **Layout — three panes (desktop):**
  - **Editor (left):** hook in serif (edit in the voice you ship), auto-resizing body, tag-chip input (the existing `DraftEditor`, restyled). A live **VoiceQualityChip** re-runs `strip_ai_tells` client-side as you type, flagging banned phrases inline (red underline on "delve", em-dash-as-separator, etc.).
  - **Platform Preview (center, the visual center of gravity):** the existing `PlatformPreview` tab strip promoted to center. Each tab shows the real per-platform commentary (`target.commentary ?? canonical`) with a **CharBudgetMeter**. Over-cap amber points at per-platform generation, as the code already intends.
  - **Rail (right):** status, category, target platforms, Visual render slot + template picker + carousel strip (the Phase-4 Chunk-G batch logic), failed-panel/retry/attempt-history when relevant.
  - **ActionBar (bottom, sticky):** status-aware Edit/Render/Approve/Schedule/Publish with existing tooltips + `confirm()` gate on publish-now.
- **Rationale:** today these are stacked vertical sections — you scroll between editing and previewing and lose the cause→effect link. Reviewing voice needs the edit and the platform result **simultaneously** — side-by-side, not scroll. Centering the preview (not the editor) reflects the real decision: "does this idea land on each surface?" The inline voice check operationalizes the project's entire reason for existing.

### D. Drafts — pipeline board, evolves `/drafts`
- **Goal:** See the whole editorial funnel; pull the next item that needs you.
- **Layout:** status-column board (columns = `PostStatus`: Draft / Approved / Scheduled / Published). Each card: hook (serif, truncated), category pill, target platform badges, voice chip. Click → cockpit. Failed posts surface red with a retry affordance.
- **Rationale:** a board is the honest representation of a status machine, and here the columns map 1:1 to the actual lifecycle enum — the data model rendered directly, not "kanban because trendy." Replaces 4 disconnected list pages with one funnel read left-to-right.

### E. Calendar — new, replaces the flat `/scheduled` list
- **Goal:** Manage publishing *cadence* — see gaps, avoid clustering, reschedule by dragging.
- **Layout:** week/month grid; each scheduled post is a block at its slot, color = platform, hook on hover. Right rail lists "next up" chronologically (preserves current `/scheduled` sort).
- **Components:** calendar grid, drag-to-reschedule (writes through the idempotent `/schedule` endpoint with `replace_existing`), per-platform color blocks, empty-slot affordance that opens generate.
- **Rationale:** scheduling is the backbone (APScheduler, jobstore-persisted) yet has no time view. A flat list can't show "nothing goes out Thu–Sun" or "three stacked Monday morning." Brand consistency is a *cadence* problem; cadence is spatial-temporal. Mobile collapses to an agenda list.

### F. Published — evolves `/published`, future-proof for analytics
- **Goal:** Confirm what went live, jump to the real post, (later) read performance.
- **Layout:** reverse-chron list; each row links out via the existing `linkedinUrlFromUrn()` helper, shows all platform targets it fanned out to and each outcome. A reserved-but-empty "Performance" column header signals the deferred Phase-7 slot without faking data.
- **Rationale:** analytics is *deferred* (`r_member_social` closed in 2026 — see memory). Don't draw fake charts. Design the row so a metrics column drops in when Member Data Portability lands; show only real data now.

### G. Settings — new home for the 5 connection cards + prompts/templates/voice
- **Goal:** Manage the plumbing: platform connections, prompt versions, visual templates, voice rules.
- **Layout:** sub-nav (Connections · Prompts · Templates · Voice). Connections = the existing 5 account sections (with connect/disconnect + Meta-gated `enabled` hiding) moved verbatim out of home.
- **Rationale:** touched ~once per 60 days; burying them reclaims the daily surface. Adding **Prompts** (the versioned `prompts` table) and **Templates** as read/activate surfaces makes "voice tuning = DB write, not deploy" usable from the UI (today it's Alembic-only). A real workflow unlock.

---

## 6. Responsive strategy (fully responsive)

The forcing function is the three-pane cockpit — it can't survive on a phone.

| Breakpoint | Behavior |
|---|---|
| **Desktop ≥1280px** | Left rail + full multi-pane cockpit; calendar grid; board columns side by side. Rail **defaults expanded**. |
| **Tablet 768–1279** | Rail **defaults collapsed** to icons; cockpit drops to two panes (editor **or** preview, toggled). |
| **Mobile <768** | Rail → **bottom tab bar** (primary nav) + a slim **top app bar** (brand switch, Settings, token-health dot, account/sign-out) so no rail affordance is lost. Cockpit **stacks**: preview first (what you judge on the go), then editor, sticky ActionBar at bottom. Calendar → agenda list. |

**Rail collapse is user-controlled, not just a breakpoint.** The default expanded/collapsed state follows the 1280px line, but the user pins either state via a toggle in the rail footer (or the `[` shortcut), persisted to `localStorage` (`autopost:rail-collapsed`). When collapsed, hovering the icon rail **peeks** the full labelled rail as an opaque overlay so navigation clarity is never lost. Mobile keeps the bottom tab bar regardless (no collapse concept there).

**Mobile's real job is approve-on-the-go:** review the per-platform preview, tweak a word, approve or publish. Full multi-pane authoring stays a desktop act — drafts at the desk, approvals from the couch.

---

## 7. The four differentiating moments

1. **The studio is the artifact** — serif-display + minimal-dark chrome means the tool *is* visibly Nestwhirr. Not mistakable for a Tailwind dashboard template.
2. **Voice quality you can see and edit** — inline AI-tell flagging turns the founding philosophy into a live editing surface.
3. **Side-by-side multi-platform reality** — the cockpit shows one idea in 5 platform shapes with live char budgets. The fan-out *is* the product, so it's the visual center.
4. **The pipeline rendered literally** — funnel on Today, board on Drafts, calendar on Schedule: the status enum made spatial, not hidden behind list pages.

---

## Build order (when implementation starts)

Highest-leverage vertical first — it proves the whole language:
1. **App shell** (left rail + brand switcher + global token-health pill) + **design tokens** (`globals.css` rewrite).
2. **Component kit** primitives (`StatusPill`, `PlatformBadge`, `CharBudgetMeter`, `VoiceQualityChip`).
3. **Draft Review Cockpit** (§5C) — the three-pane vertical slice.
Then: Today → Drafts board → Calendar → Inbox → Published → Settings.
