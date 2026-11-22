/**
 * Money helpers (T-31 / US-19). Integer paise only; no floating-point maths.
 * Parsing works on the typed string, so "0.1" + "0.2" style drift cannot happen.
 */

/** ₹1 crore, matching the personal expense form's limit. */
export const MAX_AMOUNT_PAISE = 1_000_000_000;

/**
 * Parses a rupee amount typed by the user ("250", "250.5", "1,250.75") into paise.
 * Returns null when the text is not a valid amount with at most 2 decimals.
 */
export function parseRupeesToPaise(raw: string): number | null {
  const cleaned = raw.trim().replace(/,/g, '');
  const match = cleaned.match(/^(\d{1,8})(?:\.(\d{0,2}))?$/);
  if (!match) return null;
  const rupees = Number(match[1]);
  const fraction = (match[2] ?? '').padEnd(2, '0');
  return rupees * 100 + Number(fraction);
}

/** Formats paise as ₹ with Indian digit grouping, e.g. 123456 -> "₹1,234.56". */
export function formatPaise(paise: number): string {
  const sign = paise < 0 ? '-' : '';
  const abs = Math.abs(Math.trunc(paise));
  const rupees = Math.floor(abs / 100);
  const rest = String(abs % 100).padStart(2, '0');
  return `${sign}₹${rupees.toLocaleString('en-IN')}.${rest}`;
}

/** Paise as a plain rupee string for an input field, e.g. 123450 -> "1234.50". */
export function paiseToInputText(paise: number): string {
  const abs = Math.abs(Math.trunc(paise));
  return `${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, '0')}`;
}
