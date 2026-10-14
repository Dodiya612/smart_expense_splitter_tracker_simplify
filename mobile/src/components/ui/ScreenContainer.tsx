import React from 'react';
import {
  KeyboardAvoidingView,
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
}

export function ScreenContainer({
  children,
  scrollable = false,
  edges = ['top', 'bottom', 'left', 'right'],
  style,
  contentContainerStyle,
}: ScreenContainerProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  const topInset = edges.includes('top') ? insets.top : 0;
  const bottomInset = edges.includes('bottom') ? insets.bottom : 0;
  const leftInset = edges.includes('left') ? insets.left : 0;
  const rightInset = edges.includes('right') ? insets.right : 0;

  const contentPaddingStyle: ViewStyle = {
    paddingTop: topInset,
    paddingBottom: bottomInset,
    paddingLeft: leftInset + theme.spacing.lg,
    paddingRight: rightInset + theme.spacing.lg,
  };

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.background }, style]}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.keyboardView}>
        {scrollable ? (
          <ScrollView
            style={styles.scrollView}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
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
