import React, { Suspense, lazy } from 'react';
import { RouteErrorBoundary } from '@/components/navigation/RouteErrorBoundary';
import { AuthSkeleton } from '@/features/auth/components/AuthSkeleton';

const LoginScreen = lazy(() =>
  import('@/features/auth/screens/LoginScreen').then((module) => ({
    default: module.LoginScreen,
  }))
);

export default function LoginRoute() {
  return (
    <RouteErrorBoundary routeName="Login">
      <Suspense fallback={<AuthSkeleton />}>
        <LoginScreen />
      </Suspense>
    </RouteErrorBoundary>
  );
}
