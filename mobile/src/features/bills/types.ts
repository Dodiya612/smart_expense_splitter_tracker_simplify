/**
 * Bill scan types (T-54 / US-16), mirroring ReceiptScanResponseData in
 * backend/openapi.json. Everything here is a draft until the user confirms.
 */

export type ReviewField = 'amount' | 'date' | 'merchant' | 'items';

export interface BillLineItem {
  name: string;
  /** Integer paise, printed on the bill (the server checked every number). */
  amountPaise: number;
  quantity: string | null;
  unitPricePaise: number | null;
}

export interface BillWarning {
  code: string;
  message: string;
  field: ReviewField | null;
}

export interface BillDraft {
  receiptId: string;
  merchant: string | null;
  amountPaise: number | null;
  /** YYYY-MM-DD or null when the bill date was not found. */
  date: string | null;
  /** Form category id ('food', …) guessed from the bill, or null. */
  categoryId: string | null;
  items: BillLineItem[];
  itemsSource: 'llm' | 'rules' | 'none';
  warnings: BillWarning[];
  lowConfidenceFields: ReviewField[];
}

/** The photo picked or taken, ready to upload. */
export interface PickedBillImage {
  uri: string;
  mimeType: string;
  fileName: string;
  fileSize: number | null;
}
