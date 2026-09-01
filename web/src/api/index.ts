/** The API surface: types, the client interface, and the real implementation (P1-8). */

export { ApiError, NetworkError, createApiClient } from './client';
export type { AnchorPatch, AnchorRange, ApiClient } from './client';
export * from './types';
