# Curai design system

The working rules for every screen. Tokens are in `web/css/tokens.css`; the workspace is
`web/css/care.css`, the patient pages `web/css/tools.css`, sign-in `web/css/auth.css`.

## Scene and direction

A doctor at a shared desktop in a bright OPD between two-minute consultations; a patient on a low-cost
phone under waiting-room lights. **Light by default**; staff can choose dark or "same as device" from the
header (`web/js/theme.js` applies it before paint). Patient pages are light only.

Restrained colour: tinted neutrals, one **teal** accent (`--accent` #0b6b63) for actions, links and the
current place, and a deep-teal sidebar (`--nav`) that carries the brand. No gradients, no glass, no
decorative motion.

## Rules

- **Status is never colour alone.** Every state has words; urgent ones add an icon. Status pills
  (`.status`, `.bad`, `.warn`, `.good`) also differ in shape (diamond, dot, tick).
- **Unreviewed AI output wears the highlighter** (`mark`, `.unreviewed`).
- **No side-stripe borders, no uppercase tracked eyebrows, no nested cards.** Numbers only where order is
  real (the patient journey, prescription steps, slot login).
- **One font family**, the system stack in `--font`, which renders Devanagari natively (Noto on
  Android, Kohinoor on Apple, Nirmala on Windows). Hindi text gets more line height (`:lang(hi)`).
- **One control shape**: 10px radius, 40px tall (44px on touch screens, 52px on patient pages). Pills
  only for status and answer chips.
- **Contrast**: text 4.5:1 on its surface; control borders (`--border-strong`) 3:1. Check both themes.
- **Motion**: 120–180ms ease-out for state changes only; everything stops under reduced motion.
- **Strict CSP**: no inline scripts or handlers; events go through `h()` or `addEventListener`.

## Layout

Workspace: sidebar (248px) + content; one sticky header with the open patient, allergies, theme, inbox
and account; urgent alerts below it until someone marks them seen. Under 860px the sidebar becomes a
drawer with a scrim (Escape closes it). Patient pages: one centred column up to 720px, the interview
side by side above 760px.
