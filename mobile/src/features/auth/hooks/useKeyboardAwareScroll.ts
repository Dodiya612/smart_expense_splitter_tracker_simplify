import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Keyboard,
  LayoutChangeEvent,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Platform,
  ScrollView,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '@/theme';

interface FieldLayout {
  y: number;
  height: number;
}

export function useKeyboardAwareScroll() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const scrollViewRef = useRef<ScrollView>(null);
  const fieldLayouts = useRef<Record<string, FieldLayout>>({});
  const formYOffset = useRef(0);
  const scrollY = useRef(0);
  const viewportHeight = useRef(0);
  // Tracks the last field passed to ensureFieldVisible so we can re-check
  // after the keyboard has resized the viewport (see effect below).
  const lastFocusedField = useRef<string | null>(null);

  const [innerContentHeight, setInnerContentHeight] = useState(0);
  const [liveViewportHeight, setLiveViewportHeight] = useState(0);
  const [isKeyboardOpen, setIsKeyboardOpen] = useState(false);

  useEffect(() => {
    const showEvent = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvent = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';

    const showSub = Keyboard.addListener(showEvent, () => {
      setIsKeyboardOpen(true);
    });
    const hideSub = Keyboard.addListener(hideEvent, () => {
      setIsKeyboardOpen(false);
      scrollViewRef.current?.scrollTo({ y: 0, animated: true });
    });

    return () => {
      showSub.remove();
      hideSub.remove();
    };
  }, []);

  const topPadding = useMemo(() => {
    const minPadding = insets.top + theme.spacing.lg;
    if (isKeyboardOpen || liveViewportHeight <= 0 || innerContentHeight <= 0) {
      return minPadding;
    }
    const usableHeight = liveViewportHeight - insets.top - insets.bottom - theme.spacing.xl;
    const remainingSpace = usableHeight - innerContentHeight;
    if (remainingSpace <= 0) {
      return minPadding;
    }
    return insets.top + Math.max(theme.spacing.lg, Math.floor(remainingSpace * 0.38));
  }, [insets.top, insets.bottom, isKeyboardOpen, liveViewportHeight, innerContentHeight, theme]);

  const onScroll = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    scrollY.current = e.nativeEvent.contentOffset.y;
  }, []);

  const onScrollViewLayout = useCallback((e: LayoutChangeEvent) => {
    const h = e.nativeEvent.layout.height;
    viewportHeight.current = h;
    setLiveViewportHeight(h);
  }, []);

  const onFormContentLayout = useCallback((e: LayoutChangeEvent) => {
    setInnerContentHeight(e.nativeEvent.layout.height);
  }, []);

  const onFormLayout = useCallback((e: LayoutChangeEvent) => {
    formYOffset.current = e.nativeEvent.layout.y;
  }, []);

  const onContainerLayout = useCallback(
    (field: string) => (e: LayoutChangeEvent) => {
      fieldLayouts.current[field] = {
        y: e.nativeEvent.layout.y,
        height: e.nativeEvent.layout.height,
      };
    },
    []
  );

  const ensureFieldVisible = useCallback(
    (field: string, topMargin = 16, bottomMargin = 20) => {
      // Always track so the keyboard-open effect can re-check after resize.
      lastFocusedField.current = field;

      const layout = fieldLayouts.current[field];
      if (!layout) {
        return;
      }

      const currentScrollY = scrollY.current;
      const currentViewportHeight = viewportHeight.current;
      if (currentViewportHeight <= 0) return;

      // Absolute coordinates inside the scroll container
      const fieldTop = topPadding + formYOffset.current + layout.y;
      const fieldBottom = fieldTop + layout.height;
      const visibleTop = currentScrollY;
      const visibleBottom = currentScrollY + currentViewportHeight;

      const isFullyVisible =
        fieldTop >= visibleTop + topMargin &&
        fieldBottom <= visibleBottom - bottomMargin;

      if (isFullyVisible) return;

      if (fieldTop < visibleTop + topMargin) {
        const targetY = Math.max(0, fieldTop - topMargin);
        scrollViewRef.current?.scrollTo({ y: targetY, animated: true });
        return;
      }

      if (fieldBottom > visibleBottom - bottomMargin) {
        const targetY = fieldBottom - currentViewportHeight + bottomMargin;
        const safeTargetY = layout.height > currentViewportHeight
          ? Math.max(0, fieldTop - topMargin)
          : Math.max(0, targetY);
        scrollViewRef.current?.scrollTo({ y: safeTargetY, animated: true });
      }
    },
    [topPadding]
  );

  // When the keyboard opens, onFocus has already called ensureFieldVisible with
  // the full pre-keyboard viewport, so the field appeared visible and no scroll
  // happened. This effect re-checks after isKeyboardOpen becomes true AND
  // liveViewportHeight has settled to the resized value, at which point the
  // shrunken viewport and updated topPadding produce correct coordinates.
  useEffect(() => {
    if (!isKeyboardOpen || !lastFocusedField.current) return;
    const field = lastFocusedField.current;
    const id = requestAnimationFrame(() => {
      ensureFieldVisible(field);
    });
    return () => cancelAnimationFrame(id);
  }, [isKeyboardOpen, liveViewportHeight, ensureFieldVisible]);

  return {
    scrollViewRef,
    topPadding,
    onScroll,
    onScrollViewLayout,
    onFormContentLayout,
    onFormLayout,
    onContainerLayout,
    ensureFieldVisible,
  };
}
