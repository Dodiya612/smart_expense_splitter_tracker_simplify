import React, { Suspense, lazy } from 'react';
import { RouteErrorBoundary } from '@/components/navigation/RouteErrorBoundary';
import { AuthSkeleton } from '@/features/auth/components/AuthSkeleton';

const SignupScreen = lazy(() =>
  import('@/features/auth/screens/SignupScreen').then((module) => ({
    default: module.SignupScreen,
  }))
);

export default function SignupRoute() {
  return (
    <RouteErrorBoundary routeName="Sign Up">
      <Suspense fallback={<AuthSkeleton />}>
        <SignupScreen />
      </Suspense>
    </RouteErrorBoundary>
  );
}
