/**
 * Take or choose a bill photo and send it for scanning (T-54 / US-16).
 *
 * States: idle → picking → scanning → (onScanned) | error. On an error the
 * picked photo is kept so "Try again" re-sends it without picking again.
 */

import { useCallback, useRef, useState } from 'react';
import * as ImagePicker from 'expo-image-picker';
import { ApiError } from '@/services/api/types';
import { scanBill } from '../services/billsApi';
import type { BillDraft, PickedBillImage } from '../types';
import { pickedImageProblem } from '../utils/billDraft';

export type ScanStatus = 'idle' | 'picking' | 'scanning' | 'error';

/** Smaller photos upload faster; the server shrinks them again below 1 MB. */
const PICKER_OPTIONS: ImagePicker.ImagePickerOptions = {
  mediaTypes: ['images'],
  quality: 0.6,
  exif: false,
  allowsEditing: false,
};

function toPicked(asset: ImagePicker.ImagePickerAsset): PickedBillImage {
  const mimeType = asset.mimeType ?? 'image/jpeg';
  const ext = mimeType === 'image/png' ? 'png' : 'jpg';
  return {
    uri: asset.uri,
    mimeType,
    fileName: asset.fileName ?? `bill.${ext}`,
    fileSize: typeof asset.fileSize === 'number' ? asset.fileSize : null,
  };
}

export interface UseScanBillReturn {
  status: ScanStatus;
  error: string | null;
  /** True when the last photo can be sent again. */
  canRetry: boolean;
  previewUri: string | null;
  takePhoto: () => Promise<void>;
  choosePhoto: () => Promise<void>;
  retry: () => Promise<void>;
}

export function useScanBill(onScanned: (draft: BillDraft) => void): UseScanBillReturn {
  const [status, setStatus] = useState<ScanStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [canRetry, setCanRetry] = useState(false);
  const [previewUri, setPreviewUri] = useState<string | null>(null);
  const lastImage = useRef<PickedBillImage | null>(null);

  const fail = useCallback((message: string, retryable: boolean) => {
    setError(message);
    setCanRetry(retryable && lastImage.current !== null);
    setStatus('error');
  }, []);

  const send = useCallback(
    async (image: PickedBillImage) => {
      const problem = pickedImageProblem(image);
      if (problem) {
        lastImage.current = null;
        fail(problem, false);
        return;
      }
      lastImage.current = image;
      setPreviewUri(image.uri);
      setError(null);
      setStatus('scanning');
      try {
        const draft = await scanBill(image);
        setStatus('idle');
        onScanned(draft);
      } catch (err) {
        const apiErr = err instanceof ApiError ? err : null;
        fail(apiErr?.message ?? "The bill couldn't be read. Please try again.", apiErr?.isRetryable ?? true);
      }
    },
    [fail, onScanned]
  );

  const pick = useCallback(
    async (source: 'camera' | 'library') => {
      setStatus('picking');
      setError(null);
      try {
        if (source === 'camera') {
          const permission = await ImagePicker.requestCameraPermissionsAsync();
          if (!permission.granted) {
            fail(
              permission.canAskAgain
                ? 'Camera access is needed to take a photo of the bill.'
                : 'Camera access is off. Turn it on in Settings, or choose a photo instead.',
              false
            );
            return;
          }
        }
        const result =
          source === 'camera'
            ? await ImagePicker.launchCameraAsync(PICKER_OPTIONS)
            : await ImagePicker.launchImageLibraryAsync(PICKER_OPTIONS);
        const asset = result.canceled ? undefined : result.assets[0];
        if (!asset) {
          setStatus('idle');
          return;
        }
        await send(toPicked(asset));
      } catch {
        fail(
          source === 'camera'
            ? "The camera couldn't be opened. Try choosing a photo instead."
            : "Your photos couldn't be opened. Please try again.",
          false
        );
      }
    },
    [fail, send]
  );

  const takePhoto = useCallback(() => pick('camera'), [pick]);
  const choosePhoto = useCallback(() => pick('library'), [pick]);
  const retry = useCallback(async () => {
    if (lastImage.current) await send(lastImage.current);
  }, [send]);

  return { status, error, canRetry, previewUri, takePhoto, choosePhoto, retry };
}
