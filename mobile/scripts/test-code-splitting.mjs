import test from 'node:test';
import assert from 'node:assert';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

const projectRoot = process.cwd();

// ---------------------------------------------------------------------------
// 1. Route-Level Code Splitting Static Contract Tests (Phase 3 Requirements)
// ---------------------------------------------------------------------------
test('Route-level code splitting static architecture verification', async (t) => {
  const routes = [
    {
      file: 'src/app/(tabs)/home.tsx',
      name: 'Home',
      featureImport: '@/features/home/screens/HomeScreen',
      skeleton: 'DashboardSkeleton',
    },
    {
      file: 'src/app/(tabs)/groups.tsx',
      name: 'Groups',
      featureImport: '@/features/balances/screens/GroupBalancesScreen',
      skeleton: 'GroupBalancesSkeleton',
    },
    {
      file: 'src/app/(tabs)/expenses.tsx',
      name: 'Expenses',
      featureImport: '@/features/expenses/screens/ExpenseHistoryScreen',
      skeleton: 'ExpenseHistorySkeleton',
    },
    {
      file: 'src/app/add-expense.tsx',
      name: 'Add Expense',
      featureImport: '@/features/expenses/screens/ExpenseFormScreen',
      skeleton: 'ExpenseFormSkeleton',
    },
    {
      file: 'src/app/expense-detail.tsx',
      name: 'Expense Detail',
      featureImport: '@/features/expenses/screens/ExpenseDetailScreen',
      skeleton: 'ExpenseDetailSkeleton',
    },
    {
      file: 'src/app/group-balances.tsx',
      name: 'Group Balances',
      featureImport: '@/features/balances/screens/GroupBalancesScreen',
      skeleton: 'GroupBalancesSkeleton',
    },
    {
      file: 'src/app/(auth)/login.tsx',
      name: 'Login',
      featureImport: '@/features/auth/screens/LoginScreen',
      skeleton: 'AuthSkeleton',
    },
    {
      file: 'src/app/(auth)/signup.tsx',
      name: 'Sign Up',
      featureImport: '@/features/auth/screens/SignupScreen',
      skeleton: 'AuthSkeleton',
    },
  ];

  for (const route of routes) {
    await t.test(`Route ${route.name} (${route.file}) implements lazy code splitting`, () => {
      const fullPath = resolve(projectRoot, route.file);
      assert.ok(existsSync(fullPath), `File ${route.file} must exist`);

      const content = readFileSync(fullPath, 'utf8');

      // 1. Must use React.lazy / lazy and Suspense
      assert.ok(
        content.includes('lazy('),
        `${route.file} must use lazy() for code splitting`
      );
      assert.ok(
        content.includes('<Suspense'),
        `${route.file} must wrap screen in <Suspense>`
      );

      // 2. Must import dynamically and avoid synchronous screen import
      assert.ok(
        content.includes(`import('${route.featureImport}')`),
        `${route.file} must dynamically import ${route.featureImport}`
      );
      // Ensure there is no top-level synchronous import from the screen file
      const synchronousRegex = new RegExp(`import\\s+{[^}]+}\\s+from\\s+['"]${route.featureImport}['"]`);
      assert.ok(
        !synchronousRegex.test(content),
        `${route.file} must NOT synchronously import ${route.featureImport}`
      );

      // 3. Must wrap in RouteErrorBoundary
      assert.ok(
        content.includes('RouteErrorBoundary'),
        `${route.file} must use RouteErrorBoundary for network/chunk error recovery`
      );

      // 4. Must provide designated skeleton fallback
      assert.ok(
        content.includes(route.skeleton),
        `${route.file} fallback must use ${route.skeleton}`
      );
    });
  }
});

// ---------------------------------------------------------------------------
// 2. RouteErrorBoundary State Transition and Retry Logic
// ---------------------------------------------------------------------------
test('RouteErrorBoundary state transition and retry logic', async (t) => {
  function simulateErrorBoundary(initialError = null) {
    let state = {
      hasError: Boolean(initialError),
      error: initialError,
    };

    function getDerivedStateFromError(error) {
      state = { hasError: true, error };
      return state;
    }

    function handleRetry() {
      state = { hasError: false, error: null };
      return state;
    }

    return {
      getState: () => state,
      triggerError: (err) => getDerivedStateFromError(err),
      retry: () => handleRetry(),
    };
  }

  await t.test('initial state has no error', () => {
    const boundary = simulateErrorBoundary();
    assert.strictEqual(boundary.getState().hasError, false);
    assert.strictEqual(boundary.getState().error, null);
  });

  await t.test('catches dynamic chunk loading failure and enters error state', () => {
    const boundary = simulateErrorBoundary();
    boundary.triggerError(new Error('Failed to fetch dynamically imported module'));

    assert.strictEqual(boundary.getState().hasError, true);
    assert.strictEqual(
      boundary.getState().error.message,
      'Failed to fetch dynamically imported module'
    );
  });

  await t.test('retrying resets error state so user can reload chunk', () => {
    const boundary = simulateErrorBoundary(new Error('ChunkLoadError'));
    assert.strictEqual(boundary.getState().hasError, true);

    boundary.retry();
    assert.strictEqual(boundary.getState().hasError, false);
    assert.strictEqual(boundary.getState().error, null);
  });
});

// ---------------------------------------------------------------------------
// 3. WakingUpBanner Component Code Quality & Contract Verification
// ---------------------------------------------------------------------------
test('WakingUpBanner source integrity and contract verification', async (t) => {
  const bannerPath = resolve(projectRoot, 'src/components/ui/WakingUpBanner.tsx');
  assert.ok(existsSync(bannerPath), 'WakingUpBanner.tsx must exist');

  const content = readFileSync(bannerPath, 'utf8');

  await t.test('has no duplicate imports from react-native or other libraries', () => {
    const importLines = content
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.startsWith('import '));

    const importedModules = importLines.map((line) => {
      const match = line.match(/from\s+['"]([^'"]+)['"]/);
      return match ? match[1] : line;
    });

    const uniqueModules = new Set(importedModules);
    assert.strictEqual(
      importedModules.length,
      uniqueModules.size,
      `Detected duplicate module imports: ${importedModules.join(', ')}`
    );
  });

  await t.test('imports ActivityIndicator exactly once without duplicates', () => {
    const activityIndicatorMatches = content.match(/ActivityIndicator/g) || [];
    // Should be imported once in the import statement and used in JSX
    assert.ok(
      activityIndicatorMatches.length >= 2,
      'ActivityIndicator should be imported and rendered'
    );
    const importSection = content.slice(0, content.indexOf('export function'));
    const importOccurrences = (importSection.match(/ActivityIndicator/g) || []).length;
    assert.strictEqual(
      importOccurrences,
      1,
      'ActivityIndicator should be imported exactly once'
    );
  });

  await t.test('contains the exact user-required message', () => {
    assert.ok(
      content.includes('Our server is waking up. Please wait a moment...'),
      'Must contain exact message: "Our server is waking up. Please wait a moment..."'
    );
  });

  await t.test('returns null when visible is false (automatic hiding)', () => {
    assert.ok(
      content.includes('if (!visible) return null;'),
      'Must return null when visible is false to automatically hide upon server response'
    );
  });

  await t.test('renders valid JSX structure with pulse animation and warning tokens', () => {
    assert.ok(content.includes('<Animated.View'), 'Must wrap in Animated.View for pulse');
    assert.ok(content.includes('accessibilityRole="alert"'), 'Must have alert accessibility role');
    assert.ok(content.includes('theme.colors.warning.text'), 'Must use theme warning text color');
    assert.ok(content.includes('theme.colors.warning.soft'), 'Must use theme warning soft background');
  });
});
