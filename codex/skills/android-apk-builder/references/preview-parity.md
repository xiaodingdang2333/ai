# Preview Parity

Use this reference when the user says the installed APK must match the browser preview.

## One Source Of Truth

Create or infer a design spec before coding both surfaces:

```text
Colors:
  primary: #0B63CE
  primary2: #1684ED
  background: #F4F7FB
  card: #FFFFFF
  text: #182230
  muted: #667085
  line: #D8E2EF

Dimensions:
  screen reference: 390 x 820
  topbar height: 58dp
  content padding: 14dp
  action card height: 76dp
  action card radius: 14dp
  list card radius: 14dp
  tab height: 38dp
  small button height: 34dp

Typography:
  title: 21sp bold
  action title: 15sp bold
  body: 12sp-13sp
  pdf title: 16sp bold
```

Use the exact same values in:

- CSS variables in `preview.html`
- Android constants, XML resources, or Compose theme

## Avoid These Mismatches

- Web uses rounded cards, Android uses default square `Button`.
- Web shows 2x2 actions, Android uses one horizontal row.
- Web has PDF thumbnails, Android only text.
- Web preview uses custom spacing, Android uses platform default padding.
- Android title is hidden by status bar or display cutout.
- Android text labels are shortened too aggressively compared with preview.
- Java source contains mojibake Chinese strings.

## Android Parity Patterns

For View-based Java/Kotlin apps:

- Prefer `TextView` or `LinearLayout` with `GradientDrawable` for custom buttons/cards.
- Use `setPadding(dp(...))`, fixed dp heights, and matching margins.
- Use `Window#setStatusBarColor(primary)` and either target SDK 34 or handle insets for SDK 35.
- Use `setSingleLine(true)` only where the preview also truncates.
- Use two rows of actions if the preview has two rows.
- Split dense operations into two rows if needed to match mobile card density.

For Jetpack Compose apps:

- Define a single `AppTheme` object with colors, shapes, spacing, and typography.
- Use Compose Preview for developer review, but still provide `preview.html` when the user wants Codex/browser preview.

## Parity Checklist

Before packaging:

- Browser preview topbar matches Android topbar.
- Status bar does not cover the title.
- Number of action cards and row layout match.
- Tab style and active state match.
- Empty state matches.
- PDF card structure matches: thumbnail, title, metadata, operation buttons.
- Font sizes look equivalent on a common 390dp-wide phone.
- Primary color and background color match by hex/RGB.
- Rounded corners are visually equivalent.

If any item fails, update Android code before building the APK.
