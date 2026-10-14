# Smart Expense Splitter Tracker: Mobile Frontend

This file lives at the root of `mobile/`, which is the Antigravity workspace. All paths are relative to `mobile/`.

## Scope and ownership
- I own the FRONTEND ONLY: Expo + React Native + TypeScript (strict). Never create or edit backend, database or server code, and never touch files outside `mobile/`.
- A Python FastAPI backend is built in parallel by teammates. No endpoint, schema, auth flow or error format is confirmed unless I say so. Mark every proposed route, payload and schema `PROVISIONAL`.
- Do not overwrite teammate work or make architectural changes I did not ask for.
- Security is enforced by the backend. Never rely on frontend checks for authorization.

## Product decisions (final; do not reopen without a concrete technical conflict)
- INR only. No multi-currency or currency picker.
- Group members and shared-expense participants are registered users only. No guests.
- Tabs: Home, Groups, Analytics, Budgets, Profile, plus a central Add action. Add opens a modal or dedicated route; it is NOT a tab screen.
- Analytics (category charts, donut) and Budgets (progress bars, remaining amounts) are separate. Never use a category donut as budget progress.
- This is not a bank or payment processor. Never write "Total Balance". Never imply a settlement is a completed transfer. Home shows: spent this month, you're owed, you owe, budget highlights, recent activity.
- NOT in the MVP: receipt scanning, voice entry, multi-currency, guest members. Do not build them, not even as fake working features.

## Design decisions log (source of truth)
A decision is made only when it is written here. If something I say in chat conflicts with this log, point out the conflict and ask which wins; do not silently follow either. When I make a new decision, propose the exact line to add here.
- REJECTED for the MVP: glass UI / glassmorphism, blur, gradients, glossy wallet-style cards, decorative animation. Do not add them, and do not add `expo-blur` or gradient packages.
- Chosen: white cards on a cool-grey background, deep navy text and primary actions, one soft shadow (`shadows.card`), Inter, outline icons, light mode first.
- Visual polish (richer motion, illustration, delight) is a LATER dedicated phase, planned with me. Until then, use only the tokens and primitives; do not improvise effects.
- Build order: theme, shared primitives, auth screens, tab shell, then one feature screen at a time. Auth screens are UI only against the mock API; the real auth flow is PROVISIONAL.

## Stay grounded (no guessing)
- Before using a library API, check the installed version (node_modules types or official docs). If unsure that an API, prop or option exists, say so instead of guessing.
- Before referencing a file, component or export, open it and confirm it exists. Do not invent file paths, props, hooks or package names.
- Never say a command ran, a test passed or a screen works unless you ran it and saw the result. Say plainly what you could not run (for example on a real device or iOS).
- Do not fix a problem by adding a dependency, changing config, or loosening TypeScript or lint rules without asking me first.
- If a request conflicts with this file, say so. Do not comply silently and do not refuse silently.

## Stack
- Expo SDK (latest stable), Expo Router, TypeScript strict. No `any` without a written reason. No web-only code (no div, span, CSS files, localStorage, window).
- Secrets and tokens: `expo-secure-store` only.
- Pre-approved dependency: Inter via `@expo-google-fonts/inter` (install with `npx expo install`). Any other dependency: tell me what it is for and why a built-in will not do, then wait.
- Use the import alias configured in `tsconfig.json` (`@/*` maps to `src/*`). Check it exists before using it; do not invent one.

## Expo rules (from the project template; keep)
- Expo ships breaking changes every SDK release. Do not trust your training data for any Expo, EAS or React Native API. Before writing code that touches one: (1) read the major version of `expo` in `package.json`; (2) read the matching docs, `https://docs.expo.dev/versions/v<major>.0.0/`; (3) for anything else use the index at `https://docs.expo.dev/llms.txt` and follow its links. If you cannot fetch docs, say so and ask me; do not answer from memory.
- Install packages ONLY with `npx expo install <package>` (never `npm install` or `npm add`), so versions match the SDK.
- Commands: `npx expo start` (dev server), `npx expo lint`, `npx tsc --noEmit`, `npx expo-doctor` (after any dependency or config change), `npx expo install --fix`.
- Routes live in `src/app/`. Every file there is a screen and `_layout.tsx` files define navigators. Keep all non-route code (components, hooks, utils) outside `src/app/`. Import `Link`, `router` and `useLocalSearchParams` from `expo-router`.
- If `ios/` and `android/` do not exist, they are generated. Never create or edit them by hand; configure native behavior in `app.json` and config plugins.
- Expo Go only includes its bundled native modules. A library with native code needs a development build. Tell me before adding one.
- Prefer Expo modules over third-party libraries. Do not run `eas build`, `eas submit`, `eas update` or `expo run:*` without asking me.

## Folder structure
```
mobile/
  src/
    app/                      Expo Router routes ONLY (template convention). Thin: compose screens, no logic.
      (auth)/                 login, signup
      (tabs)/                 home, groups, analytics, budgets, profile
      add-expense.tsx         modal route for the central Add action
    components/
      ui/                     shared primitives (AppText, Button, AppInput, AppCard, ...)
      navigation/             custom tab bar and central Add button
    features/
      <feature>/              auth, expenses, groups, analytics, budgets, profile
        components/           components used only by this feature
        hooks/                hooks used only by this feature
        screens/              screen components that route files render
        types.ts              types used only by this feature
    services/
      api/                    ApiClient interface, shared API types (PROVISIONAL), client selection
      mock/                   mock ApiClient implementation and deterministic fixtures
    theme/                    colors, spacing, typography, radii, shadows, index (useTheme)
    hooks/                    shared hooks only
    utils/                    pure, unit-tested functions: money, splits, dates, formatting
    constants/                non-theme config (app-wide constants, mock/real switch)
  scripts/                    check-design.mjs
  docs/                       api-contract.md (see below)
  .agent/skills/              screen-review
```
Rules for this structure:
- Create folders and files when they are needed. Never create empty placeholder files or folders.
- Naming: components and screens `PascalCase.tsx`, hooks `useThing.ts`, utilities `camelCase.ts`, route files lowercase as Expo Router requires. One component per file. Named exports.
- Import files directly. No barrel files except `src/theme/index.ts`.
- Shared primitives are built when first needed, then reused. Before writing any UI, check `components/ui/` for an existing one. A second near-duplicate component is a bug.
- Keep a component under ~150 lines. Extract subcomponents or hooks instead of growing files.
- Types: shared API contract types in `services/api/types.ts`; feature-only types in the feature. Do not duplicate a type.

## Data, mock API and the backend contract
- Screens never fetch, never import fixtures, never contain hardcoded data. They call feature hooks, which call the `ApiClient` from `services/api`.
- `ApiClient` is ONE interface. The mock implementation and the future FastAPI implementation both satisfy it. One config switch selects which is used; screens do not know.
- The mock is realistic (Indian names, INR, plausible categories) and deterministic. It can simulate loading delay, empty results and errors on demand, so every state can be seen and tested.
- Maintain `docs/api-contract.md`: every `ApiClient` operation with request and response types, each marked PROVISIONAL, plus open questions for the backend team. Update it whenever the interface changes. Once the backend shares an OpenAPI spec, align types and client with it. The spec wins over the mock.
- Money: integer paise in code. No floating-point money math. Split logic is pure, unit-tested and lives in `utils/`. Shares must always sum exactly to the total. The rounding-remainder rule and the balance sign (positive = owed to me) are PROVISIONAL until the team agrees.

## Design system
- Read tokens only through `useTheme()` from `src/theme`. No hex or rgba values, raw font sizes or magic spacing numbers in screens or components (`npm run check:design` enforces this).
- Bright `fill` colors are for chart segments, icons and bars only. Text uses the `text` variants. Never put white text on a bright fill.
- Never communicate status by color alone: add a sign (+/-), label or icon.
- Outline icons from one icon set; heavier emphasis for the selected tab and primary actions. No emoji as icons.
- Touch targets at least 44pt. Respect safe areas. Forms: KeyboardAvoidingView and inline validation.
- Copy: sentence case, plain words, buttons say what happens ("Add expense", "Record settlement"). Errors say what went wrong and what to do.
- Every data-driven screen has loading, empty, error (with retry) and success states. Lists use FlatList.

## Process
1. Inspect the repo first and report its structure. Do not assume files or dependencies.
2. Propose a small plan and WAIT for my approval before changing files.
3. One phase at a time: theme, then primitives, then one screen per phase. Do not scaffold the whole app.
4. If a requirement is ambiguous, ask me and recommend a default; do not silently assume.
5. Before calling a phase done: run `npx tsc --noEmit`, `npx expo lint`, unit tests and `npm run check:design`; run the `screen-review` skill on each new screen. Then report what changed, what was tested, what was NOT tested, what remains, and any backend assumptions.
6. After a meaningful verified phase, remind me to review and commit. Never claim a commit was made unless I made or authorized it.
