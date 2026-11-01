# Performance Budget and Lighthouse Audit Guide

This document establishes the frontend performance budget and outlines manual verification procedures for Coinscious.

---

## 1. Scope and Platform Applicability

- **Lighthouse Applies to Web Only:** Google Lighthouse audits browser DOM, network lifecycles, and web assets. It applies exclusively to the **Expo Web export (`mobile/dist/`)** or local Metro web server.
- **Native Mobile Apps (iOS / Android):** Native binaries compiled with React Native 0.86 and Expo SDK 57 execute on native UI threads (via Hermes/fabric) and cannot be evaluated with Lighthouse. Native performance is instead governed by frame rate (60 fps), cold start time (< 2s), and memory usage.

---

## 2. Proposed Performance Budget Thresholds

The following performance budgets apply to the web bundle of Coinscious:

### Core Web Vitals & Timings
| Metric | Budget Threshold | Description |
|---|---|---|
| **Lighthouse Performance Score** | `≥ 80` | Minimum score on mobile device emulation |
| **First Contentful Paint (FCP)** | `≤ 2.0s` | Time until the first DOM content is painted |
| **Largest Contentful Paint (LCP)** | `≤ 2.5s` | Time until the main hero/card content is rendered |
| **Total Blocking Time (TBT)** | `≤ 200ms` | Time between FCP and Time to Interactive (responsiveness) |
| **Cumulative Layout Shift (CLS)** | `≤ 0.1` | Visual layout stability during render |
| **Speed Index (SI)** | `≤ 3.0s` | Visual progression speed of page load |

### Asset & Bundle Size Budget
| Resource Type | Maximum Budget | Target |
|---|---|---|
| **Initial JavaScript Bundle (Compressed)** | `≤ 350 KB` | `< 250 KB` |
| **Initial Total Page Weight (Compressed)** | `≤ 600 KB` | `< 450 KB` |
| **Custom Web Fonts** | `≤ 100 KB` | Preloaded WOFF2 only |

---

## 3. How to Run a Manual Web Audit

Developers can execute manual audits locally without CI/CD infrastructure using either Chrome DevTools or the Lighthouse CLI.

### Option A: Using Chrome DevTools (Recommended for Quick Checks)

1. Start the Expo Web development server:
   ```bash
   cd mobile
   npx expo start --web
   ```
2. Open the application in Google Chrome: `http://localhost:8081`.
3. Open **Chrome DevTools** (`F12` or `Ctrl+Shift+I` / `Cmd+Option+I`).
4. Navigate to the **Lighthouse** tab.
5. Select:
   - **Mode:** Navigation
   - **Device:** Mobile
   - **Categories:** Performance, Accessibility, Best Practices, SEO
6. Click **Analyze page load**.
7. Compare the generated score and metrics against the budget table above.

### Option B: Using Lighthouse CLI on Production Static Export

To audit production-minified assets without Metro development overhead:

1. Build the static web bundle:
   ```bash
   cd mobile
   npx expo export --platform web
   ```
2. Serve the static export locally:
   ```bash
   npx serve dist -l 8081
   ```
3. Run Lighthouse CLI against the served export:
   ```bash
   npx @lhci/cli collect --url=http://localhost:8081
   ```
   Or via Chrome's standalone Lighthouse CLI:
   ```bash
   npx lighthouse http://localhost:8081 --view --preset=desktop
   ```

---

## 4. Deferred Automation Items

In accordance with strict project constraints, **no new CI/CD workflows or GitHub Actions have been introduced** for T-25. The following capabilities are explicitly deferred until CI/CD pipelines are formally scheduled and approved:

1. **Automated Pull Request Budget Checks:** Automated Lighthouse CI runs against Vercel preview URLs or ephemeral test servers.
2. **Commit Status Check Enforcements:** Blocking merges if bundle size or Lighthouse scores drop below thresholds.
3. **Historical Performance Tracking:** Storing and graphing performance telemetry in Lighthouse CI Server.
