# Designer reference — Instrumenta / instrumenta

Read after `SKILL.md` when you need tokens or the widget list. Code is source of
truth — re-check files below before a large visual change; don’t invent hex from memory.

## Brand palette

From `frontend/src/index.css` (brand sheet):

| Token | Hex | Role |
|-------|-----|------|
| orange | `#FEB933` / `#feb933` | accent, info chips, amber |
| coral | `#FE5C7A` / `#fe5c7a` | warnings, destructive accent |
| blue | `#6A8CFE` / `#6a8cfe` | primary / ring (app) |
| lime | `#A8FE5B` / `#a8fe5b` | positive / success |
| dark base | `#080C12` / `#080c12` | dark background |

Landing gradient: orange → coral (`landing.css` `--grad`).

## App surface

**Files:** `frontend/src/index.css`, `frontend/src/components/layout/AppShell.tsx`,
`frontend/src/components/ui/*`

**Stack:** React 19, Tailwind 4 (`@theme`), Radix, CVA, `cn`, `lucide-react`, light + `.dark`.

Semantic tokens: `--color-background`, `--color-foreground`, `--color-card`,
`--color-primary`, `--color-muted-foreground`, `--color-destructive`,
`--color-border`, `--color-ring`, radii `--radius-sm|md|lg`.

Prefer token utilities (`bg-background`, `text-muted-foreground`, `border-border`,
`bg-primary`…) over raw hex.

## Landing / promo surface

**Files:** `frontend/src/features/landing/landing.css`, `LandingPage.tsx`,
`OfferPage.tsx`, `features/landing/components/*`

All under `.landing-root` — CSS vars (`--bg`, `--surface`, `--accent`,
`--font-display` Space Grotesk, `--font-body` IBM Plex Sans, `--max`, `--pad`).

Don’t import `landing.css` into AppShell pages. Don’t force `@/components/ui` into
a pure-CSS landing hero — keep one visual language. Landing modals may match
landing style (e.g. `ScreencastModal`) or carefully bridge without palette switch.

## UI kit (`frontend/src/components/ui/`)

| Component | File | Use |
|-----------|------|-----|
| Button | `button.tsx` | CTA, secondary, ghost, destructive |
| Card | `card.tsx` | interactive/content blocks in app |
| Dialog | `dialog.tsx` | confirms, paywall-related |
| Sheet | `sheet.tsx` | mobile panels, detail |
| Tabs | `tabs.tsx` | page sections |
| Input | `input.tsx` | forms |
| Select | `select.tsx` | single select |
| Combobox | `combobox.tsx` | search + select |
| MultiSelect | `multi-select.tsx` | multi filters |
| Checkbox | `checkbox.tsx` | flags |
| Popover | `popover.tsx` | light overlays |
| Tooltip | `tooltip.tsx` | icon/metric hints |
| Badge | `badge.tsx` | status, labels |
| Skeleton | `skeleton.tsx` | loading |
| Separator | `separator.tsx` | divider |
| Calendar / DatePicker | `calendar.tsx`, `date-picker.tsx` | dates |

Theme: `components/theme-provider.tsx`.

New widget → same pattern: Radix + `cva` + `cn` + export from `components/ui/`.

## Copy facts (don’t invent)

From AGENTS.md:

- Free after Telegram login: screener, simulation, radar, favorites, calculator
- Paid entitlements: broker keys write, portfolio attach, trading_portfolio.access
- Pro: 795 ₽/mo or 5940 ₽/yr (billing versions; UI may read catalog API)
- YooKassa; without env → `payment_unavailable`
- Trade CTA: no sub → paywall; no keys → `/account`; else wizard

Marketing may simplify wording; must not distort facts.

## Product touchpoints

| Scenario | Route |
|----------|-------|
| Guest on landing | Telegram login / `/login` |
| Plan | `/account/plan` |
| Broker keys | `/account` |
| Bot notifications | `/account/notifications` |
| Simulation / trading | portfolios + trading queue / deploy session |
| Market | `/radar` |
| Screener | `/` or screener route |

Empty/error states are design work: message + next CTA.

## Mobile checklist

- 375×667, no page horizontal scroll
- Tables: `hidden md:table-cell` or cards
- Filters collapsible on narrow viewports
- Sticky header / bottom nav must not break layout
- Primary CTA reachable without horizontal scroll
