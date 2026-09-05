/** The API surface: types, the client interface, and the real implementation (P1-8). */

export { ApiError, NetworkError, createApiClient } from './client';
export type {
  AnchorPatch,
  AnchorRange,
  ApiClient,
  EntryFilter,
  EntryFromRangeInput,
  EntryInput,
  EntryPatch,
  LinkInput,
  LinkPatch,
} from './client';
export * from './types';

// D32's stream vocabulary. Not part of the REST surface - it travels over the one WebSocket
// (P4-10) - but it is a wire shape mirrored from the server, so it lives beside the others.
export * from './stream';
