/**
 * Shared API contract types.
 *
 * Aligned with the FastAPI backend authentication engine and error envelopes.
 */

/** Authenticated user profile. */
export interface AuthUser {
  id: string;
  name: string;
  email: string;
}

/** Credentials submitted for user login. */
export interface LoginCredentials {
  email: string;
  password: string;
}

/** Payload submitted for user registration. */
export interface SignupPayload {
  name: string;
  email: string;
  password: string;
}

/** JWT and refresh token bundle returned on authentication. */
export interface TokenBundle {
  accessToken: string;
  refreshToken: string;
  tokenType?: string;
  expiresIn?: number;
}

/** Payload submitted for refresh token rotation. */
export interface RefreshTokenPayload {
  refreshToken: string;
}

/** Payload submitted for logout. */
export interface LogoutPayload {
  refreshToken?: string;
}

/**
 * Authentication response from login or signup.
 * Includes user profile and token bundle.
 */
export interface AuthResponse {
  user: AuthUser;
  tokens?: TokenBundle;
}

/** Standard validation error detail item. */
export interface ApiErrorDetail {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
}

/** Standard client error representation for API failures. */
export class ApiError extends Error {
  readonly code: string;
  readonly isRetryable: boolean;
  readonly detail?: ApiErrorDetail[] | null;

  constructor(
    code: string,
    message: string,
    isRetryable = false,
    detail: ApiErrorDetail[] | null = null
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.isRetryable = isRetryable;
    this.detail = detail;
  }
}

/**
 * The single client interface satisfied by both the mock implementation and
 * the FastAPI client. Screens and auth providers interact with this abstraction.
 */
export interface ApiClient {
  login(credentials: LoginCredentials): Promise<AuthResponse>;
  signup(payload: SignupPayload): Promise<AuthResponse>;
  refresh(payload: RefreshTokenPayload): Promise<TokenBundle>;
  logout(payload?: LogoutPayload, accessToken?: string | null): Promise<void>;
  me(accessToken?: string | null): Promise<AuthUser>;
}
