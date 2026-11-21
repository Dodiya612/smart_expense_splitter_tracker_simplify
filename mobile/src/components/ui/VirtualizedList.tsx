/**
 * VirtualizedList – High-Performance Windowed List Virtualization Component
 *
 * Implements strict windowed list virtualization for US-32 / T-62:
 * - Renders ONLY the visible window items plus a configurable buffer (overscan).
 * - Drastically reduces DOM nodes and memory footprints for lists over 100, 500, and 1,000 rows.
 * - Maintains 100% accurate scroll heights and scrollbar proportions using top and bottom spacer blocks.
 * - Supports ListHeaderComponent, ListFooterComponent, ListEmptyComponent, Pull-to-refresh,
 *   and infinite scroll pagination (onEndReached).
 * - Seamlessly preserves editing, deleting, selecting, searching, and filtering.
 */

import React, { useCallback, useMemo, useState } from 'react';
import {
  NativeScrollEvent,
  NativeSyntheticEvent,
  Platform,
  RefreshControlProps,
  ScrollView,
  StyleProp,
  StyleSheet,
  View,
  ViewStyle,
} from 'react-native';
import { theme } from '@/theme';
import {
  computeVirtualWindow,
  type VirtualWindowParams,
  type VirtualWindowResult,
} from './virtualizationUtils';

export { computeVirtualWindow, type VirtualWindowParams, type VirtualWindowResult };

export interface VirtualizedListProps<T> {
  data: T[];
  renderItem: (info: { item: T; index: number }) => React.ReactElement | null;
  keyExtractor: (item: T, index: number) => string;
  itemHeight?: number;
  overscan?: number;
  ListHeaderComponent?: React.ReactElement | (() => React.ReactElement | null) | null;
  ListFooterComponent?: React.ReactElement | (() => React.ReactElement | null) | null;
  ListEmptyComponent?: React.ReactElement | (() => React.ReactElement | null) | null;
  onEndReached?: () => void;
  onEndReachedThreshold?: number;
  refreshControl?: React.ReactElement<RefreshControlProps>;
  contentContainerStyle?: StyleProp<ViewStyle>;
  showsVerticalScrollIndicator?: boolean;
  accessibilityRole?: string;
  accessibilityLabel?: string;
  testID?: string;
}

export function VirtualizedList<T>({
  data,
  renderItem,
  keyExtractor,
  itemHeight = 156,
  overscan = 5,
  ListHeaderComponent,
  ListFooterComponent,
  ListEmptyComponent,
  onEndReached,
  onEndReachedThreshold = 0.4,
  refreshControl,
  contentContainerStyle,
  showsVerticalScrollIndicator = false,
  accessibilityRole = 'list',
  accessibilityLabel = 'Virtualized item list',
  testID,
}: VirtualizedListProps<T>) {
  const [scrollTop, setScrollTop] = useState<number>(0);
  const [viewportHeight, setViewportHeight] = useState<number>(800);
  const [hasTriggeredEnd, setHasTriggeredEnd] = useState<boolean>(false);

  const handleLayout = useCallback((e: any) => {
    const height = e.nativeEvent.layout.height;
    if (height > 0) {
      setViewportHeight(height);
    }
  }, []);

  const handleScroll = useCallback(
    (e: NativeSyntheticEvent<NativeScrollEvent>) => {
      const { contentOffset, layoutMeasurement, contentSize } = e.nativeEvent;
      const currentScrollTop = contentOffset.y;
      setScrollTop(currentScrollTop);

      // End-reached detection with threshold buffer
      const distanceFromEnd = contentSize.height - (currentScrollTop + layoutMeasurement.height);
      const thresholdPx = layoutMeasurement.height * onEndReachedThreshold;

      if (distanceFromEnd <= thresholdPx && distanceFromEnd >= 0) {
        if (!hasTriggeredEnd) {
          setHasTriggeredEnd(true);
          onEndReached?.();
        }
      } else {
        if (hasTriggeredEnd && distanceFromEnd > thresholdPx * 1.5) {
          setHasTriggeredEnd(false);
        }
      }
    },
    [hasTriggeredEnd, onEndReached, onEndReachedThreshold]
  );

  // Compute virtualization window
  const windowResult = useMemo(() => {
    return computeVirtualWindow({
      dataLength: data.length,
      itemHeight,
      scrollTop,
      viewportHeight,
      overscan,
    });
  }, [data.length, itemHeight, scrollTop, viewportHeight, overscan]);

  // Slice only the visible and buffer rows
  const visibleItems = useMemo(() => {
    if (data.length === 0) return [];
    return data.slice(windowResult.startIndex, windowResult.endIndex).map((item, idx) => {
      const originalIndex = windowResult.startIndex + idx;
      return {
        item,
        index: originalIndex,
        key: keyExtractor(item, originalIndex),
      };
    });
  }, [data, windowResult.startIndex, windowResult.endIndex, keyExtractor]);

  const renderedHeader = useMemo(() => {
    if (!ListHeaderComponent) return null;
    return typeof ListHeaderComponent === 'function' ? ListHeaderComponent() : ListHeaderComponent;
  }, [ListHeaderComponent]);

  const renderedFooter = useMemo(() => {
    if (!ListFooterComponent) return null;
    return typeof ListFooterComponent === 'function' ? ListFooterComponent() : ListFooterComponent;
  }, [ListFooterComponent]);

  const renderedEmpty = useMemo(() => {
    if (!ListEmptyComponent) return null;
    return typeof ListEmptyComponent === 'function' ? ListEmptyComponent() : ListEmptyComponent;
  }, [ListEmptyComponent]);

  return (
    <ScrollView
      testID={testID}
      style={styles.container}
      contentContainerStyle={contentContainerStyle}
      onLayout={handleLayout}
      onScroll={handleScroll}
      scrollEventThrottle={16}
      showsVerticalScrollIndicator={showsVerticalScrollIndicator}
      refreshControl={refreshControl}
      accessibilityRole={accessibilityRole as any}
      accessibilityLabel={accessibilityLabel}
    >
      {/* 1. Header Component */}
      {renderedHeader}

      {/* 2. Empty State (when 0 rows) */}
      {data.length === 0 && renderedEmpty}

      {/* 3. Virtualized List Body with Exact Spacers */}
      {data.length > 0 && (
        <View style={styles.listBody}>
          {/* Top Virtual Spacer */}
          {windowResult.topSpacerHeight > 0 && (
            <View
              accessibilityElementsHidden={true}
              importantForAccessibility="no-hide-descendants"
              style={{ height: windowResult.topSpacerHeight, width: '100%' }}
            />
          )}

          {/* Rendered Visible & Buffer Items */}
          {visibleItems.map(({ item, index, key }) => (
            <View key={key} style={styles.itemWrapper}>
              {renderItem({ item, index })}
            </View>
          ))}

          {/* Bottom Virtual Spacer */}
          {windowResult.bottomSpacerHeight > 0 && (
            <View
              accessibilityElementsHidden={true}
              importantForAccessibility="no-hide-descendants"
              style={{ height: windowResult.bottomSpacerHeight, width: '100%' }}
            />
          )}
        </View>
      )}

      {/* 4. Footer Component */}
      {renderedFooter}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  listBody: {
    width: '100%',
  },
  itemWrapper: {
    width: '100%',
    marginBottom: theme.spacing.md,
  },
});
