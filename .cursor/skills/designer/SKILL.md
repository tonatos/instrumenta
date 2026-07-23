---
name: designer
description: >-
  Designer mode for Instrumenta/bond-monitor UI: brand style, visual polish,
  UX journeys, mobile-first layout, honest marketing copy, UI-kit reuse
  (Radix/shadcn-style). Use when the user asks for designer mode, дизайн,
  landing, лендинг, hero, UI/UX polish, copywriting, or visual redesign.
disable-model-invocation: true
---

# Designer mode — bond-monitor / Instrumenta

Use for frontend UI/marketing work. Goals: on-brand, visually strong, mobile-friendly,
honest selling copy, reuse existing widgets.

Product context: [`AGENTS.md`](../../../AGENTS.md). Mobile rules:
[`.cursor/rules/mobile.mdc`](../../rules/mobile.mdc). Tokens & kit:
[`reference.md`](reference.md).

## When

- New/reworked screen, section, dialog, landing
- “Make it prettier”, UX polish, copy, “designer mode”
- Marketing surfaces (landing, offer, paywall, onboarding)

Skip for backend/domain-only work with no UI.

## Workflow (required order)

```
Task Progress:
- [ ] 1. Surface & audience
- [ ] 2. Style lock
- [ ] 3. User journey
- [ ] 4. Component inventory
- [ ] 5. Visual + copy
- [ ] 6. Mobile check
- [ ] 7. Honesty / a11y pass
```

### 1. Surface & audience

| Surface | Style | Source |
|---------|-------|--------|
| **App** (screener, portfolio, radar, account) | Tailwind + semantic tokens, `@/components/ui/*` | `frontend/src/index.css`, `AppShell` |
| **Landing / promo** | Scoped vars on `.landing-root` | `features/landing/landing.css`, `LandingPage.tsx` |

Do not mix landing tokens with AppShell (landing CSS is scoped).

### 2. Style lock

Read current tokens for the surface ([`reference.md`](reference.md)) before pixels.

**Do:**
- Project colors, radii, type, gradients, spacing
- Existing composition patterns (nav, sections, CTA, tables, sheets)
- Frontend design user rules (one first-viewport composition, brand-first on branded pages, avoid generic AI looks) — **if** the surface already has a language (Instrumenta dark landing / app tokens), **keep that language**

**Don’t:**
- New palettes / random hex outside tokens
- Cards/pills/stat strips without a job
- Glow / purple defaults over the brand

### 3. User journey (UX)

Before layout, state briefly:

1. **Who** + **one primary job** on this screen
2. **Happy path** — 3–7 steps to outcome
3. **Friction** — errors, empty, paywall, missing keys/subscription (AGENTS: “Перевести в торговлю” → paywall / `/account` / wizard)
4. **Primary / secondary CTA** — one main accent per section
5. **Feedback** — Skeleton, empty, error, success (toast/dialog)

Ergonomics:
- One section = one job + one headline + usually one short support line
- Hierarchy: brand/product → action → detail
- Don’t bury critical actions; secondary = collapsible
- Forms: vertical stack; heavy filters collapsible on mobile
- Touch targets ≥ 40px when practical
- Keep Radix focus/keyboard a11y patterns

### 4. Component inventory (UI-kit first)

1. In `@/components/ui/` → **use it** (Button, Dialog, Sheet, Select, Tabs, Card, Badge, Input, Checkbox, Combobox, MultiSelect, DatePicker, Tooltip, Skeleton, Separator, Popover, Calendar…)
2. Same job exists in `features/*` → **reuse**, don’t fork
3. Missing → research **Radix + same wrapper style**, or a light React 19 / Tailwind 4 widget
4. Heavy/awkward dependency → **minimal recreate** in `components/ui/` (cva + `cn` + Radix)

Icons: `lucide-react`. Charts: `recharts`. Tables: `@tanstack/react-table` where already used.

Do not add MUI/Ant/Chakra on top of the kit.

### 5. Visual + copy

**Visual**
- Anchor = product / real UI / brand atmosphere — not decorative gradient alone
- Motion: 2–3 purposeful moves, not noise
- Landing hero: full-bleed / one composition; no floating badges on media
- App: data density over marketing whitespace; contrast still required

**Copy (RU if UI is Russian)**

Marketing: short, clear, literate, selling — **no lies**.

| Do | Don’t |
|----|-------|
| Concrete benefit (“action queue for your portfolio”) | Yield guarantees, “risk-free” |
| Honest limits (subscription / broker key needed) | Hide paid features or risks |
| Short CTA (“Sign in with Telegram”) | Bureaucracy / filler |
| Product terms from `labels.ts` / AGENTS | Synonym salad for one entity |

Tone: calm, expert; informal “ты” only if neighbors already use it. Check spelling/grammar.

Facts from AGENTS.md (free vs paid, Pro prices, YooKassa, complimentary) — no invented numbers/features.

Labels: `frontend/src/features/portfolio/labels.ts` — no duplicates.

### 6. Mobile check

- Viewport ≥ 320px; target **375×667**
- No page-level horizontal overflow; wide content scrolls inside (`overflow-x-auto`)
- Fixed/sticky `AppShell` chrome not tied to content width
- Tables `<md`: hide secondary cols or card layout
- Before done: check 375px or e2e `mobile` project

### 7. Honesty / a11y pass

- [ ] Copy doesn’t promise what the product doesn’t do
- [ ] CTAs hit real routes (`/login`, `/account/plan`, …)
- [ ] Contrast OK on light/dark (app)
- [ ] Controls have clear names (text / aria)
- [ ] No new business logic on frontend — presentation + API only

## TDD

New UI feature → e2e business scenario in `e2e/playwright/tests/mocked/` (not “button exists”). Fix broken tests.

## Anti-patterns

- Second UI kit beside Radix/shadcn-style
- Polish without a journey (where does the user go next?)
- Landing section pasted in AppShell style or vice versa
- Long paragraphs for one idea
- Fake social proof, invented yield %, “AI trades for you”
- Cards/badges/chips without interaction or info need
