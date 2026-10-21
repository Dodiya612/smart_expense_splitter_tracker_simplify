import React, { useEffect, useState } from 'react';
import {
  Keyboard,
  KeyboardAvoidingView,
  LayoutChangeEvent,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Platform,
  ScrollView,
  StyleProp,
  StyleSheet,
  View,
  ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '@/theme';

export type SafeEdge = 'top' | 'bottom' | 'left' | 'right';

export interface ScreenContainerProps {
  children: React.ReactNode;
  scrollable?: boolean;
  edges?: SafeEdge[];
  style?: StyleProp<ViewStyle>;
  contentContainerStyle?: StyleProp<ViewStyle>;
  scrollViewRef?: React.Ref<ScrollView>;
  onScroll?: (event: NativeSyntheticEvent<NativeScrollEvent>) => void;
  onScrollViewLayout?: (event: LayoutChangeEvent) => void;
  onContentSizeChange?: (width: number, height: number) => void;
  keyboardBehavior?: 'height' | 'position' | 'padding';
}

export function ScreenContainer({
  children,
  scrollable = false,
  edges = ['top', 'bottom', 'left', 'right'],
  style,
  contentContainerStyle,
  scrollViewRef,
  onScroll,
  onScrollViewLayout,
  onContentSizeChange,
  keyboardBehavior,
}: ScreenContainerProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const [isKeyboardOpen, setIsKeyboardOpen] = useState(false);

  useEffect(() => {
    const showEvent = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvent = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';
    const showSub = Keyboard.addListener(showEvent, () => setIsKeyboardOpen(true));
    const hideSub = Keyboard.addListener(hideEvent, () => setIsKeyboardOpen(false));
    return () => {
      showSub.remove();
      hideSub.remove();
    };
  }, []);

  const topInset = edges.includes('top') ? insets.top : 0;
  const bottomInset = edges.includes('bottom') ? insets.bottom : 0;
  const leftInset = edges.includes('left') ? insets.left : 0;
  const rightInset = edges.includes('right') ? insets.right : 0;

  // Modest bottom clearance when closed; additional clearance when keyboard is open
  const bottomClearance = scrollable
    ? isKeyboardOpen
      ? theme.spacing.xxxl * 2
      : theme.spacing.xl
    : 0;

  const contentPaddingStyle: ViewStyle = {
    paddingTop: topInset,
    paddingBottom: bottomInset + bottomClearance,
    paddingLeft: leftInset + theme.spacing.lg,
    paddingRight: rightInset + theme.spacing.lg,
  };

  const activeKeyboardBehavior =
    keyboardBehavior ?? (Platform.OS === 'ios' ? 'padding' : undefined);

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.background }, style]}>
      <KeyboardAvoidingView
        behavior={activeKeyboardBehavior}
        style={styles.keyboardView}>
        {scrollable ? (
          <ScrollView
            ref={scrollViewRef}
            style={styles.scrollView}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="on-drag"
            showsVerticalScrollIndicator={false}
            scrollEventThrottle={16}
            onScroll={onScroll}
            onLayout={onScrollViewLayout}
            onContentSizeChange={onContentSizeChange}
            contentContainerStyle={[
              styles.scrollContent,
              contentPaddingStyle,
              contentContainerStyle,
            ]}>
            {children}
          </ScrollView>
        ) : (
          <View style={[styles.staticContent, contentPaddingStyle]}>
            {children}
          </View>
        )}
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  keyboardView: {
    flex: 1,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
  },
  staticContent: {
    flex: 1,
  },
});
