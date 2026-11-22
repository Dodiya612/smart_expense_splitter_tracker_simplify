// T-54 / US-16: bill scan review helpers, the expense body with a receipt, and the
// multipart upload in fastApiClient. Run: npm test
import test from 'node:test';
import assert from 'node:assert';
import {
  MAX_UPLOAD_BYTES,
  categoryFromBill,
  decodeDraft,
  draftToFormValues,
  encodeDraft,
  fieldWarning,
  generalWarnings,
  itemDetail,
  mapScanResponse,
  pickedImageProblem,
  scanErrorMessage,
} from '../src/features/bills/utils/billDraft.ts';
import { buildCreateExpenseBody } from '../src/features/expenses/utils/expensePayload.ts';
import { mapBackendExpenseToDomain } from '../src/features/expenses/services/expenseApi.ts';
import { CATEGORIES } from '../src/features/expenses/types.ts';
import { formatPaise } from '../src/utils/money.ts';
import { fastApiClient } from '../src/services/api/fastApiClient.ts';

const RECEIPT_ID = '6f1c2b8e-7d4a-4c3b-9a1e-2f5d8c7b6a90';

function scanReply(over = {}) {
  return {
    data: {
      receiptId: RECEIPT_ID,
      merchant: 'Sharma Kirana Store',
      amountMinor: 45050,
      amountPaise: 45050,
      expenseDate: '2026-11-20',
      category: 'Groceries',
      notes: null,
      fileSize: 81234,
      items: [
        { name: 'Basmati rice 1kg', amountPaise: 24000, quantity: '2', unitPricePaise: 12000 },
        { name: 'Toor dal', amountPaise: 21050, quantity: null, unitPricePaise: null },
      ],
      itemsSource: 'llm',
      warnings: [],
      lowConfidenceFields: [],
      confidence: { amount: 0.92 },
      isDraft: true,
      ocrEngine: 'tesseract',
      ...over,
    },
    message: 'Receipt processed successfully.',
  };
}

test('mapScanResponse keeps integer paise and the checked items', () => {
  const d = mapScanResponse(scanReply());
  assert.strictEqual(d.receiptId, RECEIPT_ID);
  assert.strictEqual(d.amountPaise, 45050);
  assert.strictEqual(d.date, '2026-11-20');
  assert.strictEqual(d.categoryId, 'groceries');
  assert.strictEqual(d.items.length, 2);
  assert.deepStrictEqual(d.items[0], {
    name: 'Basmati rice 1kg',
    amountPaise: 24000,
    quantity: '2',
    unitPricePaise: 12000,
  });
  assert.strictEqual(d.itemsSource, 'llm');
});

test('mapScanResponse drops bad values instead of guessing', () => {
  const d = mapScanResponse(
    scanReply({
      amountPaise: 450.5,
      amountMinor: null,
      expenseDate: 'yesterday',
      category: 'Space travel',
      merchant: '   ',
      items: [
        { name: 'Float', amountPaise: 12.5 },
        { name: '', amountPaise: 100 },
        null,
        { name: 'Ok', amountPaise: 100 },
      ],
      itemsSource: 'magic',
      warnings: [
        { code: 'X', message: '' },
        { code: 'LOW_CONFIDENCE', message: 'Check the total', field: 'nope' },
      ],
      lowConfidenceFields: ['amount', 'colour'],
    })
  );
  assert.strictEqual(d.amountPaise, null);
  assert.strictEqual(d.date, null);
  assert.strictEqual(d.categoryId, null);
  assert.strictEqual(d.merchant, null);
  assert.deepStrictEqual(d.items.map((i) => i.name), ['Ok']);
  assert.strictEqual(d.itemsSource, 'none');
  assert.deepStrictEqual(d.warnings, [{ code: 'LOW_CONFIDENCE', message: 'Check the total', field: null }]);
  assert.deepStrictEqual(d.lowConfidenceFields, ['amount']);
  assert.deepStrictEqual(mapScanResponse(null).items, []);
});

test('every server category name maps to a form category', () => {
  const names = [
    'Groceries',
    'Entertainment',
    'Gifts & Donations',
    'Personal Care',
    'Rent & Housing',
    'Health',
    'Bills & Utilities',
    'Education',
    'Travel & Transport',
    'Shopping',
    'Food & Dining',
    'Other',
  ];
  const formIds = new Set(CATEGORIES.map((c) => c.id));
  for (const name of names) {
    const id = categoryFromBill(name);
    assert.ok(id && formIds.has(id), `${name} -> ${id}`);
  }
  assert.strictEqual(categoryFromBill(' food & dining '), 'food');
  assert.strictEqual(categoryFromBill(null), null);
});

test('the draft survives the route param, and a broken param opens an empty form', () => {
  const d = mapScanResponse(scanReply({ lowConfidenceFields: ['date'] }));
  assert.deepStrictEqual(decodeDraft(encodeDraft(d)), d);
  assert.strictEqual(decodeDraft(undefined), undefined);
  assert.strictEqual(decodeDraft('{not json'), undefined);
  assert.strictEqual(decodeDraft(JSON.stringify({ amountPaise: 100 })), undefined);
  const tampered = decodeDraft(JSON.stringify({ ...d, categoryId: 'not-a-category' }));
  assert.strictEqual(tampered?.categoryId, null);
});

test('draftToFormValues pre-fills the form; missing values stay for the user', () => {
  const full = draftToFormValues(mapScanResponse(scanReply()), '2026-11-22');
  assert.strictEqual(full.amountRaw, '450.50');
  assert.strictEqual(full.date, '2026-11-20');
  assert.strictEqual(full.categoryId, 'groceries');
  assert.strictEqual(full.notes, 'Sharma Kirana Store');
  assert.strictEqual(full.isRecurring, false);

  const empty = draftToFormValues(
    mapScanResponse(
      scanReply({ amountPaise: null, amountMinor: null, expenseDate: null, category: null, merchant: null })
    ),
    '2026-11-22'
  );
  assert.strictEqual(empty.amountRaw, '');
  assert.strictEqual(empty.date, '2026-11-22');
  assert.strictEqual(empty.categoryId, '');
  assert.strictEqual(empty.notes, '');
});

test('low-confidence fields get their warning; other warnings go to the top', () => {
  const d = mapScanResponse(
    scanReply({
      warnings: [
        { code: 'LOW_CONFIDENCE', message: 'The total was hard to read.', field: 'amount' },
        { code: 'DATE_NOT_FOUND', message: 'No date found; today is used.', field: 'date' },
        { code: 'ITEMS_DONT_ADD_UP', message: 'Items add up to a different total.', field: 'items' },
        { code: 'NO_TEXT', message: 'Hardly any text was found.', field: null },
      ],
      lowConfidenceFields: ['amount'],
    })
  );
  assert.strictEqual(fieldWarning(d, 'amount'), 'The total was hard to read.');
  assert.strictEqual(fieldWarning(d, 'date'), null, 'only listed fields are highlighted');
  assert.strictEqual(fieldWarning(undefined, 'amount'), null);
  assert.deepStrictEqual(
    generalWarnings(d).map((w) => w.code),
    ['ITEMS_DONT_ADD_UP', 'NO_TEXT']
  );

  const noMessage = mapScanResponse(scanReply({ lowConfidenceFields: ['merchant'] }));
  assert.strictEqual(fieldWarning(noMessage, 'merchant'), 'Please check this value.');
});

test('picked photos: JPEG/PNG up to 5 MB only', () => {
  const ok = { uri: 'file:///bill.jpg', mimeType: 'image/jpeg', fileName: 'bill.jpg', fileSize: 1_000_000 };
  assert.strictEqual(pickedImageProblem(ok), null);
  assert.strictEqual(pickedImageProblem({ ...ok, mimeType: 'image/png' }), null);
  assert.strictEqual(pickedImageProblem({ ...ok, fileSize: null }), null);
  assert.strictEqual(pickedImageProblem({ ...ok, fileSize: MAX_UPLOAD_BYTES }), null);
  assert.match(pickedImageProblem({ ...ok, fileSize: MAX_UPLOAD_BYTES + 1 }), /5 MB/);
  assert.match(pickedImageProblem({ ...ok, mimeType: 'image/heic' }), /JPEG or PNG/);
});

test('scan errors read plainly', () => {
  assert.match(scanErrorMessage('AI_QUOTA_EXCEEDED', 'x'), /by hand/);
  assert.match(scanErrorMessage('IMAGE_TOO_LARGE', 'x'), /5 MB/);
  assert.match(scanErrorMessage('REQUEST_TIMEOUT', 'x'), /too long/);
  assert.strictEqual(scanErrorMessage('SOMETHING_NEW', 'Server text'), 'Server text');
});

test('itemDetail', () => {
  const d = mapScanResponse(scanReply());
  assert.strictEqual(itemDetail(d.items[0], formatPaise), `2 × ${formatPaise(12000)}`);
  assert.strictEqual(itemDetail(d.items[1], formatPaise), null);
  assert.strictEqual(itemDetail({ ...d.items[1], quantity: '3' }, formatPaise), 'Qty 3');
});

test('confirming links the bill and merchant in the create body', () => {
  const base = {
    amountPaise: 45050,
    categoryId: 'groceries',
    date: '2026-11-20',
    paymentMode: 'upi',
    notes: 'Sharma Kirana Store',
    isRecurring: false,
    idempotencyKey: 'k1',
  };
  const body = buildCreateExpenseBody({ ...base, receiptId: RECEIPT_ID, merchant: '  Sharma Kirana Store ' });
  assert.strictEqual(body.receiptId, RECEIPT_ID);
  assert.strictEqual(body.merchant, 'Sharma Kirana Store');
  assert.strictEqual(body.amountPaise, 45050);
  assert.ok(Number.isInteger(body.amountPaise));

  const plain = buildCreateExpenseBody(base);
  assert.ok(!('receiptId' in plain) && !('merchant' in plain), 'a typed expense sends no receipt fields');
  assert.strictEqual(buildCreateExpenseBody({ ...base, merchant: 'x'.repeat(300) }).merchant.length, 255);
});

test('saved expenses keep their receipt id (camelCase and snake_case)', () => {
  assert.strictEqual(
    mapBackendExpenseToDomain({ id: 'e1', receiptId: RECEIPT_ID, amountPaise: 100 }).receiptId,
    RECEIPT_ID
  );
  assert.strictEqual(
    mapBackendExpenseToDomain({ id: 'e1', receipt_id: RECEIPT_ID, amount_minor: 100 }).receiptId,
    RECEIPT_ID
  );
  assert.strictEqual(mapBackendExpenseToDomain({ id: 'e1', amountPaise: 100 }).receiptId, undefined);
});

test('postForm sends multipart without a JSON Content-Type and uses the longer timeout', async () => {
  const originalFetch = globalThis.fetch;
  const originalSetTimeout = globalThis.setTimeout;
  const seen = {};
  globalThis.setTimeout = (fn, ms) => {
    seen.timeout = ms;
    return originalSetTimeout(() => {}, 0);
  };
  globalThis.fetch = async (url, init) => {
    seen.url = url;
    seen.init = init;
    return new Response(JSON.stringify(scanReply()), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  try {
    const form = new FormData();
    form.append('file', new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: 'image/jpeg' }), 'bill.jpg');
    const raw = await fastApiClient.postForm('/api/v1/receipts/scan', form, 45000);
    assert.strictEqual(mapScanResponse(raw).receiptId, RECEIPT_ID);
    assert.ok(seen.url.endsWith('/api/v1/receipts/scan'));
    assert.strictEqual(seen.init.method, 'POST');
    assert.strictEqual(seen.init.body, form);
    assert.ok(!('Content-Type' in seen.init.headers), 'fetch must set the multipart boundary itself');
    assert.strictEqual(seen.timeout, 45000);

    await fastApiClient.post('/api/v1/expenses', { a: 1 });
    assert.strictEqual(seen.init.headers['Content-Type'], 'application/json', 'JSON calls are unchanged');
    assert.strictEqual(seen.timeout, 15000);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.setTimeout = originalSetTimeout;
  }
});
