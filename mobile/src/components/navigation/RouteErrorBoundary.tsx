import React, { Component, ErrorInfo, ReactNode } from 'react';
import { View, StyleSheet } from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { theme } from '@/theme';

export interface RouteErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode | ((error: Error, reset: () => void) => ReactNode);
  routeName?: string;
  onCatch?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Catches runtime and chunk lazy-loading errors during route transitions.
 * Displays a graceful fallback screen with a retry action and error details.
 */
export class RouteErrorBoundary extends Component<RouteErrorBoundaryProps, State> {
  public override state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public override componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    if (this.props.onCatch) {
      this.props.onCatch(error, errorInfo);
    }
  }

  private handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  public override render() {
    if (this.state.hasError) {
      const error = this.state.error ?? new Error('Unknown error');

      if (typeof this.props.fallback === 'function') {
        return this.props.fallback(error, this.handleRetry);
      }

      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <View style={styles.container} testID="route-error-boundary">
          <View style={styles.card}>
            <AppText variant="heading" style={styles.title}>
              Failed to load screen
            </AppText>
            <AppText variant="body" style={styles.message}>
              {this.props.routeName
                ? `There was a problem loading the ${this.props.routeName} screen.`
                : 'There was a problem loading this screen. Please check your connection and try again.'}
            </AppText>
            {Boolean(error.message) && (
              <AppText variant="caption" style={styles.detail}>
                {error.message}
              </AppText>
            )}
            <View style={styles.actions}>
              <Button
                label="Try Again"
                variant="primary"
                onPress={this.handleRetry}
                testID="route-error-retry-button"
              />
            </View>
          </View>
        </View>
      );
    }

    return this.props.children;
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: theme.spacing.lg,
    backgroundColor: theme.colors.background,
  },
  card: {
    width: '100%',
    maxWidth: 420,
    padding: theme.spacing.xl,
    borderRadius: theme.radii.lg,
    backgroundColor: theme.colors.surface,
    alignItems: 'center',
  },
  title: {
    color: theme.colors.textPrimary,
    marginBottom: theme.spacing.sm,
    textAlign: 'center',
  },
  message: {
    color: theme.colors.textSecondary,
    marginBottom: theme.spacing.md,
    textAlign: 'center',
  },
  detail: {
    color: theme.colors.negative.text,
    marginBottom: theme.spacing.lg,
    textAlign: 'center',
  },
  actions: {
    width: '100%',
    marginTop: theme.spacing.sm,
  },
});
