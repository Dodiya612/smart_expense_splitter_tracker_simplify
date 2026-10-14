---
name: screen-review
description: Review a finished or edited screen or component in the Smart Expense Splitter mobile app against the project's design-system, architecture and mobile-quality rules. Use after building or changing any screen, before reporting a phase as done.
---

# Screen review

Run this on every screen or component you built or changed, before saying it is done. Open the actual files and check each item. Do not answer from memory of what you wrote.

## Checklist

**Architecture**
- No fetch calls, mock JSON imports or hardcoded data in the screen. Data comes through hooks that call `services/api`.
- Business logic (splits, balances, formatting) lives in `utils/`, not in the component.
- Money is integer paise in code; no float math. Display uses the shared INR formatter.
- Anything that depends on the backend is marked `PROVISIONAL`. No endpoint or schema is presented as confirmed.

**Design system**
- No hex values, raw font sizes or magic spacing numbers; everything comes from `useTheme()`.
- Bright `fill` colors are not used for small text. No white text on bright fills.
- Status is never shown by color alone (sign, label or icon present).
- No gradients, glass effects, extra shadows or decorative animation.
- Same card radius, spacing and heading style as the other screens.

**States and mobile quality**
- Loading, empty, error (with retry) and success states all exist and were exercised with mock data.
- Lists use FlatList. Touch targets are at least 44pt. Safe areas handled. Forms avoid the keyboard.
- Accessibility labels on icon-only buttons and inputs. Text is readable on a small screen (for example 360 x 640).
- Component files are under about 150 lines; no unused imports, dead code or console.log.

**Scope**
- Nothing from the NOT-in-MVP list (receipt scanning, voice, multi-currency, guests) was added.
- No new dependency was added without being asked about.

## Report format

Reply with:
1. **Passed:** checks verified, each with the file it was verified in.
2. **Problems:** each with file and line, and a proposed fix. Fix only what is within the current task and say what you changed.
3. **Not verified:** anything you could not check (for example on a real device or iOS), stated plainly.
