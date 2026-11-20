/**
 * Password strength estimate on a 0-4 scale (T-50, change password).
 *
 * Mirrors backend/app/core/password_strength.py rule for rule, so the meter shown here
 * matches the check the server enforces. Both are tested against the shared fixture
 * backend/tests/fixtures/password_strength_cases.json. Change both files together.
 *
 * The server is the authority: this only gives real-time feedback and stops obviously
 * failing submissions.
 */

export const MIN_NEW_PASSWORD_LENGTH = 10;
export const MAX_NEW_PASSWORD_LENGTH = 128;
export const MIN_PASSWORD_SCORE = 3;

export type PasswordScore = 0 | 1 | 2 | 3 | 4;

export interface PasswordStrengthResult {
  score: PasswordScore;
  label: 'Very weak' | 'Weak' | 'Fair' | 'Strong' | 'Very strong';
  effectiveLength: number;
  isCommon: boolean;
  feedback: string[];
}

const KEYBOARD_ROWS = ['1234567890', 'qwertyuiop', 'asdfghjkl', 'zxcvbnm'];

const COMMON_WORDS = [
  'password', 'passwd', 'passw', 'qwerty', 'qwertyuiop', 'asdfgh', 'zxcvbn', 'letmein',
  'welcome', 'admin', 'administrator', 'login', 'dragon', 'monkey', 'football', 'cricket',
  'baseball', 'iloveyou', 'sunshine', 'princess', 'shadow', 'master', 'superman', 'batman',
  'trustno', 'abc', 'abcdef', 'secret', 'freedom', 'whatever', 'charlie', 'michael',
  'jennifer', 'hello', 'summer', 'winter', 'spring', 'autumn', 'flower', 'computer',
  'internet', 'starwars', 'pokemon', 'google', 'india', 'mumbai', 'delhi', 'krishna',
  'ganesh', 'sairam', 'omsairam', 'jaishreeram', 'coinscious', 'splittr', 'expense',
  'changeme', 'default', 'access', 'mustang', 'killer', 'pepper', 'ginger', 'hunter',
  'ranger', 'soccer', 'hockey', 'tigger', 'jordan', 'harley', 'robert', 'thomas',
  'daniel', 'matrix', 'biscuit', 'cookie', 'chocolate', 'butterfly', 'lovely', 'angel',
];
const COMMON_SET = new Set(COMMON_WORDS);

const LEET: Record<string, string> = {
  '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '@': 'a', $: 's', '!': 'i',
};

const SCORE_THRESHOLDS = [28, 40, 56, 76];
const LABELS: PasswordStrengthResult['label'][] = ['Very weak', 'Weak', 'Fair', 'Strong', 'Very strong'];

type CharClass = 'lower' | 'upper' | 'digit' | 'symbol' | 'other';
const POOL: Record<CharClass, number> = { lower: 26, upper: 26, digit: 10, symbol: 33, other: 100 };

/** Python iterates code points, not UTF-16 units; Array.from matches that. */
const toChars = (text: string): string[] => Array.from(text);

function charClass(ch: string): CharClass {
  if (ch >= 'a' && ch <= 'z') return 'lower';
  if (ch >= 'A' && ch <= 'Z') return 'upper';
  if (ch >= '0' && ch <= '9') return 'digit';
  if (ch.length === 1 && ch >= ' ' && ch <= '~') return 'symbol';
  return 'other';
}

const codePoint = (ch: string): number => ch.codePointAt(0) ?? 0;

/** Index of `needle` in `hay` (both char arrays) at or after `from`, or -1. */
function indexOfChars(hay: string[], needle: string[], from: number): number {
  for (let i = from; i + needle.length <= hay.length; i++) {
    let ok = true;
    for (let j = 0; j < needle.length; j++) {
      if (hay[i + j] !== needle[j]) {
        ok = false;
        break;
      }
    }
    if (ok) return i;
  }
  return -1;
}

function markSubstrings(hay: string[], needles: string[], patterned: boolean[]): boolean {
  let found = false;
  for (const needle of needles) {
    const n = toChars(needle);
    if (n.length < 3) continue;
    let start = indexOfChars(hay, n, 0);
    while (start !== -1) {
      found = true;
      for (let i = start + 1; i < start + n.length; i++) patterned[i] = true;
      start = indexOfChars(hay, n, start + 1);
    }
  }
  return found;
}

function userTokens(userInputs: readonly string[]): string[] {
  const tokens: string[] = [];
  for (const value of userInputs) {
    if (!value) continue;
    const lowered = value.trim().toLowerCase();
    const local = lowered.split('@')[0] ?? '';
    const parts = [
      local,
      ...local.replace(/\./g, ' ').replace(/_/g, ' ').replace(/-/g, ' ').split(/\s+/),
      ...lowered.split(/\s+/),
    ];
    for (const part of parts) {
      if (toChars(part).length >= 3 && !tokens.includes(part)) tokens.push(part);
    }
  }
  return tokens;
}

/** Scores a password 0-4 and explains what would improve it. */
export function estimatePasswordStrength(
  password: string,
  userInputs: readonly string[] = []
): PasswordStrengthResult {
  if (!password) {
    return { score: 0, label: LABELS[0], effectiveLength: 0, isCommon: false, feedback: ['Enter a password.'] };
  }

  const chars = toChars(password);
  // Lowercase per character, keeping any character whose lowercase form is longer (e.g. "İ"),
  // so every index still lines up with the original password (same rule as the backend).
  const lower = chars.map((ch) => {
    const low = ch.toLowerCase();
    return toChars(low).length === 1 ? low : ch;
  });
  const leet = lower.map((ch) => LEET[ch] ?? ch);
  const n = chars.length;
  const patterned: boolean[] = new Array(n).fill(false);
  let hasRepeatOrSequence = false;

  for (let i = 1; i < n; i++) {
    if (chars[i] === chars[i - 1]) {
      patterned[i] = true;
      hasRepeatOrSequence = true;
    } else if (i >= 2) {
      const d1 = codePoint(chars[i - 1]) - codePoint(chars[i - 2]);
      const d2 = codePoint(chars[i]) - codePoint(chars[i - 1]);
      if (d1 === d2 && Math.abs(d1) === 1) {
        patterned[i] = true;
        hasRepeatOrSequence = true;
      }
    }
  }

  for (const row of KEYBOARD_ROWS) {
    for (const line of [row, Array.from(row).reverse().join('')]) {
      for (let j = 0; j < n - 3; j++) {
        if (line.includes(lower.slice(j, j + 4).join(''))) {
          hasRepeatOrSequence = true;
          for (let k = j + 1; k < j + 4; k++) patterned[k] = true;
        }
      }
    }
  }

  const hasCommonWord = markSubstrings(leet, COMMON_WORDS, patterned);
  const hasUserInfo = markSubstrings(lower, userTokens(userInputs), patterned);

  const effectiveLength = patterned.filter((p) => !p).length;
  const classes = new Set(chars.map(charClass));
  let pool = 0;
  classes.forEach((c) => {
    pool += POOL[c];
  });
  const bits = pool > 1 ? effectiveLength * Math.log2(pool) : 0;

  let score = 4;
  for (let i = 0; i < SCORE_THRESHOLDS.length; i++) {
    if (bits < SCORE_THRESHOLDS[i]) {
      score = i;
      break;
    }
  }

  const isLetter = (ch: string) => ch >= 'a' && ch <= 'z';
  const plainLetters = lower.filter(isLetter).join('');
  const leetLetters = leet.filter(isLetter).join('');
  const isCommon = [lower.join(''), plainLetters, leetLetters].some((form) => COMMON_SET.has(form));
  if (isCommon) score = Math.min(score, 1);

  const feedback: string[] = [];
  if (n < MIN_NEW_PASSWORD_LENGTH) feedback.push(`Use at least ${MIN_NEW_PASSWORD_LENGTH} characters.`);
  if (isCommon) {
    feedback.push('This is a commonly used password. Choose something less predictable.');
  } else if (hasCommonWord) {
    feedback.push('Avoid common words like "password" or "welcome".');
  }
  if (hasUserInfo) feedback.push('Do not include your name or email address.');
  if (hasRepeatOrSequence) {
    feedback.push('Avoid repeated characters and sequences like "abc", "1234" or "qwerty".');
  }
  if (score < MIN_PASSWORD_SCORE && classes.size < 3) {
    feedback.push('Mix uppercase and lowercase letters, numbers and symbols.');
  }
  if (score < MIN_PASSWORD_SCORE) feedback.push('Add more characters or another unrelated word.');

  const finalScore = score as PasswordScore;
  return { score: finalScore, label: LABELS[finalScore], effectiveLength, isCommon, feedback };
}
