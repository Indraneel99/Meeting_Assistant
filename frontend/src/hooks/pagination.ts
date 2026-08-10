interface PaginatedState<T> {
  items: T[];
  nextCursor: string | null;
  hasMore: boolean;
  loadingMore: boolean;
}

export function emptyPaginatedState<T>(): PaginatedState<T> {
  return { items: [], nextCursor: null, hasMore: false, loadingMore: false };
}

export type { PaginatedState };
