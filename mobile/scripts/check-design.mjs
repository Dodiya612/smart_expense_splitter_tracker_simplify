// Fails if UI code drifts from the design system. Run: npm run check:design
// Add "// design-check-ignore" at the end of a line to allow a one-off exception (explain why).
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

const ROOT = process.cwd();
const DIRS = ['src']; // routes live in src/app (template convention)
const SKIP_DIR = join('src', 'theme');
const FILE_RE = /\.(ts|tsx)$/;

const rules = [
  { name: 'hardcoded hex color (use useTheme())', re: /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/ },
  { name: 'hardcoded rgb()/rgba() color (use useTheme())', re: /\brgba?\(/ },
  { name: 'rejected style: blur/glass or gradient', re: /expo-blur|expo-linear-gradient|react-native-linear-gradient|\bBlurView\b|\bLinearGradient\b/ },
];

function* walk(dir) {
  let entries;
  try { entries = readdirSync(dir); } catch { return; }
  for (const name of entries) {
    if (name === 'node_modules') continue;
    const full = join(dir, name);
    if (relative(ROOT, full) === SKIP_DIR) continue;
    if (statSync(full).isDirectory()) yield* walk(full);
    else if (FILE_RE.test(name)) yield full;
  }
}

const problems = [];
for (const d of DIRS) {
  for (const file of walk(join(ROOT, d))) {
    readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
      if (line.includes('design-check-ignore')) return;
      for (const r of rules) {
        if (r.re.test(line)) problems.push(`${relative(ROOT, file).split(sep).join('/')}:${i + 1}  ${r.name}\n    ${line.trim()}`);
      }
    });
  }
}

if (problems.length) {
  console.error(`Design check failed (${problems.length}):\n\n` + problems.join('\n\n'));
  process.exit(1);
}
console.log('Design check passed.');
