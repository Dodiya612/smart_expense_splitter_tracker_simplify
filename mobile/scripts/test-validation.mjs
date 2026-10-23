import test from 'node:test';
import assert from 'node:assert';
import { readFile } from 'node:fs/promises';
import typescript from 'typescript';

const validationSourcePath = new URL('../src/features/auth/utils/validation.ts', import.meta.url);
const validationSourceCode = await readFile(validationSourcePath, 'utf8');
const validationCompiled = typescript.transpileModule(validationSourceCode, {
  compilerOptions: {
    module: typescript.ModuleKind.ESNext,
    target: typescript.ScriptTarget.ES2022,
  },
  fileName: validationSourcePath.pathname,
});
const validationModule = await import(
  `data:text/javascript;base64,${Buffer.from(validationCompiled.outputText).toString('base64')}`,
);
const { isValidEmail, validateLogin, validateSignup } = validationModule;

test('isValidEmail', async (t) => {
  await t.test('accepts valid email addresses', () => {
    assert.strictEqual(isValidEmail('aarav.sharma@example.in'), true);
    assert.strictEqual(isValidEmail('test.user@sub.domain.com'), true);
  });

  await t.test('rejects invalid email addresses', () => {
    assert.strictEqual(isValidEmail(''), false);
    assert.strictEqual(isValidEmail('plainaddress'), false);
    assert.strictEqual(isValidEmail('@missingusername.com'), false);
    assert.strictEqual(isValidEmail('user@missingdomain'), false);
    assert.strictEqual(isValidEmail('user with spaces@example.com'), false);
  });
});

test('validateLogin', async (t) => {
  await t.test('flags empty email and password', () => {
    const errors = validateLogin({ email: '', password: '' });
    assert.strictEqual(errors.email, 'Email address is required.');
    assert.strictEqual(errors.password, 'Password is required.');
  });

  await t.test('flags malformed email', () => {
    const errors = validateLogin({ email: 'notanemail', password: 'password123' });
    assert.strictEqual(errors.email, 'Enter a valid email address.');
    assert.strictEqual(errors.password, undefined);
  });

  await t.test('passes with valid credentials shape', () => {
    const errors = validateLogin({ email: 'aarav@example.in', password: 'password123' });
    assert.deepStrictEqual(errors, {});
  });
});

test('validateSignup', async (t) => {
  await t.test('flags empty fields', () => {
    const errors = validateSignup({
      name: '',
      email: '',
      password: '',
      confirmPassword: '',
    });
    assert.strictEqual(errors.name, 'Full name is required.');
    assert.strictEqual(errors.email, 'Email address is required.');
    assert.strictEqual(errors.password, 'Password is required.');
    assert.strictEqual(errors.confirmPassword, 'Confirm your password.');
  });

  await t.test('flags passwords shorter than 8 characters', () => {
    const errors = validateSignup({
      name: 'Priya Patel',
      email: 'priya@example.in',
      password: 'short',
      confirmPassword: 'short',
    });
    assert.strictEqual(errors.password, 'Password must be at least 8 characters.');
  });

  await t.test('flags mismatched passwords', () => {
    const errors = validateSignup({
      name: 'Priya Patel',
      email: 'priya@example.in',
      password: 'password123',
      confirmPassword: 'differentpassword',
    });
    assert.strictEqual(errors.confirmPassword, 'Passwords do not match.');
  });

  await t.test('passes with valid signup values', () => {
    const errors = validateSignup({
      name: 'Priya Patel',
      email: 'priya@example.in',
      password: 'securePassword123',
      confirmPassword: 'securePassword123',
    });
    assert.deepStrictEqual(errors, {});
  });
});
