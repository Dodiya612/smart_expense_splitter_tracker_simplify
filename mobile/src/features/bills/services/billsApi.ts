/**
 * Bill scan API (T-54 / US-16).
 *
 * - scanBill(): POST /api/v1/receipts/scan (multipart field `file`). The server
 *   stores the photo, reads it (OCR + checked line items) and returns a draft.
 *   Nothing is saved as an expense here.
 * - receiptImageSource(): the stored photo for <Image>, with the bearer token
 *   (GET /api/v1/receipts/{id}/image is owner-only; strangers get 404).
 */

import { Platform } from 'react-native';
import { resolveApiBaseUrl } from '@/constants/apiConfig';
import { tokenStorage } from '@/services/auth/tokenStorage';
import { fastApiClient } from '@/services/api/fastApiClient';
import { ApiError } from '@/services/api/types';
import type { BillDraft, PickedBillImage } from '../types';
import { mapScanResponse, scanErrorMessage } from '../utils/billDraft';

/** OCR plus the line-item step can take a while on a slow network (server AI timeout is 4 s). */
export const SCAN_TIMEOUT_MS = 45_000;

async function formFile(image: PickedBillImage): Promise<Blob> {
  if (Platform.OS === 'web') {
    // On web the picker returns a blob:/data: uri; upload the real bytes.
    const res = await fetch(image.uri);
    return await res.blob();
  }
  // React Native's FormData reads the file from this { uri, name, type } object.
  return { uri: image.uri, name: image.fileName, type: image.mimeType } as unknown as Blob;
}

export async function scanBill(image: PickedBillImage): Promise<BillDraft> {
  const form = new FormData();
  form.append('file', await formFile(image), image.fileName);
  try {
    const raw = await fastApiClient.postForm<unknown>('/api/v1/receipts/scan', form, SCAN_TIMEOUT_MS);
    const draft = mapScanResponse(raw);
    if (!draft.receiptId) {
      throw new ApiError('INVALID_RESPONSE', "The bill couldn't be read. Please try again.", true);
    }
    return draft;
  } catch (err) {
    if (err instanceof ApiError) {
      throw new ApiError(err.code, scanErrorMessage(err.code, err.message), err.isRetryable, err.detail);
    }
    throw new ApiError('SCAN_FAILED', "The bill couldn't be read. Please try again.", true);
  }
}

export interface ReceiptImageSource {
  uri: string;
  headers: Record<string, string>;
}

export async function receiptImageSource(receiptId: string): Promise<ReceiptImageSource> {
  const token = await tokenStorage.getAccessToken();
  return {
    uri: `${resolveApiBaseUrl().replace(/\/+$/, '')}/api/v1/receipts/${encodeURIComponent(receiptId)}/image`,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  };
}
