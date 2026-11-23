import React, { Suspense, lazy } from 'react';
import { RouteErrorBoundary } from '@/components/navigation/RouteErrorBoundary';
import { DashboardSkeleton } from '@/features/home/components/DashboardSkeleton';

const HomeScreen = lazy(() =>
  import('@/features/home/screens/HomeScreen').then((module) => ({
    default: module.HomeScreen,
  }))
);

export default function HomeRoute() {
  return (
    <RouteErrorBoundary routeName="Home">
      <Suspense fallback={<DashboardSkeleton />}>
        <HomeScreen />
      </Suspense>
    </RouteErrorBoundary>
  );
}
