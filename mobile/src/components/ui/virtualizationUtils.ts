/**
 * Pure mathematical algorithms and types for Windowed List Virtualization.
 *
 * Implements strict O(1) memory windowing calculation for US-32 / T-62.
 */

export interface VirtualWindowParams {
  dataLength: number;
  itemHeight: number;
  scrollTop: number;
  viewportHeight: number;
  overscan?: number;
}

export interface VirtualWindowResult {
  startIndex: number;
  endIndex: number;
  renderedCount: number;
  topSpacerHeight: number;
  bottomSpacerHeight: number;
  totalContentHeight: number;
}

/**
 * Pure mathematical windowing calculation.
 * Exported for rigorous unit testing across 100, 500, and 1000 rows.
 */
export function computeVirtualWindow({
  dataLength,
  itemHeight,
  scrollTop,
  viewportHeight,
  overscan = 5,
}: VirtualWindowParams): VirtualWindowResult {
  if (dataLength <= 0 || itemHeight <= 0) {
    return {
      startIndex: 0,
      endIndex: 0,
      renderedCount: 0,
      topSpacerHeight: 0,
      bottomSpacerHeight: 0,
      totalContentHeight: 0,
    };
  }

  const safeScrollTop = Math.max(0, scrollTop);
  const safeViewportHeight = Math.max(itemHeight, viewportHeight);

  const rawStartIndex = Math.floor(safeScrollTop / itemHeight);
  const rawEndIndex = Math.ceil((safeScrollTop + safeViewportHeight) / itemHeight);

  const startIndex = Math.max(0, rawStartIndex - overscan);
  const endIndex = Math.min(dataLength, rawEndIndex + overscan);
  const renderedCount = Math.max(0, endIndex - startIndex);

  const topSpacerHeight = startIndex * itemHeight;
  const bottomSpacerHeight = Math.max(0, (dataLength - endIndex) * itemHeight);
  const totalContentHeight = dataLength * itemHeight;

  return {
    startIndex,
    endIndex,
    renderedCount,
    topSpacerHeight,
    bottomSpacerHeight,
    totalContentHeight,
  };
}
