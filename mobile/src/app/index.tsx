import React from 'react';
import { View, ActivityIndicator, StyleSheet } from 'react-native';
import { Href, Redirect } from 'expo-router';
import { useAuth } from '@/features/auth/context/AuthContext';
import { useTheme } from '@/theme';

export default function IndexRoute() {
  const { isAuthenticated, isLoading } = useAuth();
  const theme = useTheme();

  if (isLoading) {
    return (
      <View style={[styles.loadingContainer, { backgroundColor: theme.colors.background }]}>
        <ActivityIndicator size="large" color={theme.colors.primary} />
      </View>
    );
  }

  if (isAuthenticated) {
    return <Redirect href={'/(tabs)/home' as Href} />;
  }

  return <Redirect href={'/login' as Href} />;
}

const styles = StyleSheet.create({
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
});

