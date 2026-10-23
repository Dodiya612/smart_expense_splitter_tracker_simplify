export interface AuthUser {
  id: string;
  name: string;
  email: string;
}

export class ApiError extends Error {
  code: string;
  isRetryable: boolean;

  constructor(code: string, message: string, isRetryable = false) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.isRetryable = isRetryable;
  }
}
