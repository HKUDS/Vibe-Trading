# Vibe-Trading Web Design System

## 1. Atmosphere & Identity

The Web UI is a quiet dark trading workbench: information-dense but calm,
with orange reserved for actions and active states. Settings should feel like a
safe control room, not a generic onboarding wizard. The custom-provider flow's
signature is an explicit three-state progression: draft, tested, then active.

## 2. Color

Use the existing semantic Tailwind tokens only.

| Role | Token | Usage |
|---|---|---|
| Surface | `bg-background` | Page background |
| Panel | `bg-card` | Settings cards |
| Secondary surface | `bg-muted/20`, `bg-muted/30` | Field groups and status panels |
| Primary text | `text-foreground` | Headings and values |
| Secondary text | `text-muted-foreground` | Help text and metadata |
| Action | `bg-primary`, `text-primary-foreground` | Primary buttons and active state |
| Success | `text-success`, `bg-success/10` | Verified/tested state |
| Warning | `text-warning`, `bg-warning/10` | Unactivated or caution state |
| Error | `text-danger`, `bg-danger/5` | Validation and request failures |
| Border | `border`, `border-border` | Cards, fields, dividers |

Rules: no raw hex values in components; color must not be the only status
indicator; pair status colors with text and/or icons.

## 3. Typography

- Primary: the existing application sans stack.
- Data and URLs: existing `font-mono` treatment.
- Page title: existing `text-2xl font-semibold`.
- Section title: existing `text-base font-semibold` or `text-lg font-semibold`.
- Body: existing `text-sm`; helper text: `text-xs`.
- Body line-height remains the existing `leading-relaxed` convention.
- Provider/model/URL values must wrap instead of overflow.

## 4. Spacing & Layout

- Base rhythm: Tailwind spacing tokens on the existing 4px/8px rhythm.
- Settings page: existing `mx-auto max-w-5xl space-y-6 p-6` shell.
- Cards: existing `rounded-lg border bg-card p-5 shadow-sm` treatment.
- Form groups: `grid gap-4` or `gap-5`; controls use the existing field class.
- Provider manager uses a responsive single-column flow on small screens and a
  compact two-column form/status layout from `md` upward.
- Long URLs and provider errors use `break-all` or `break-words`; no horizontal
  page overflow.

## 5. Components

### Custom Provider Manager

- **Structure:** section card → header/status summary → profile list → editor
  form → test result → explicit activation action.
- **Variants:** empty, draft, testing, tested, active, error.
- **Spacing:** existing card padding, `space-y-4`, `gap-3`, and field rhythm.
- **States:** loading skeleton, empty guidance, inline validation, testing
  spinner, success result, error with retry, active badge, disabled activation.
- **Accessibility:** visible labels, `aria-describedby` for help/error text,
  `role="alert"` for failures, `aria-live="polite"` for test status, keyboard
  reachable controls, minimum 44px action targets.
- **Motion:** only existing short opacity/transition states; no decorative
  animation and no layout animation.
- **Layout:** stack inside Settings; the profile list owns its own content flow.

### Status Badge

- **Structure:** text badge with optional status icon.
- **Variants:** draft, tested, active, failed.
- **Accessibility:** status is written as text, not color alone.

## 6. Motion & Interaction

- Use existing Tailwind transitions, approximately 150–300ms.
- Test action gives immediate loading feedback and disables duplicate submits.
- Activation is disabled until the current draft has a successful test token.
- Activation requires an explicit confirmation control/dialog.
- Respect `prefers-reduced-motion`; no essential information depends on motion.

## 7. Depth & Surface

Use the existing mixed strategy: one-pixel borders plus restrained card shadows.
Do not introduce glassmorphism, gradients, or new decorative surfaces into the
operational Settings page.

## 8. Accessibility Constraints & Accepted Debt

### Constraints

- WCAG 2.2 AA target.
- Every input has a visible label and stable error/help text.
- API keys use password inputs and are never rendered back after submission.
- API key values never enter localStorage, URL query strings, React error text,
  or client-side logs.
- Test and activation outcomes are announced to assistive technology.
- Keyboard users can complete the full draft → test → confirm → activate flow.
- RTL content follows the existing `dir="auto"` behavior.

### Accepted Debt

| Item | Location | Why accepted | Owner / Exit |
|---|---|---|---|
| UI copy remains localized through existing i18n keys | `Settings.tsx` | Matches current locale architecture | Add Persian locale when project locale policy supports it |
