interface LoadMoreButtonProps {
  hasMore: boolean;
  loading: boolean;
  onClick: () => void;
}

export function LoadMoreButton({ hasMore, loading, onClick }: LoadMoreButtonProps) {
  if (!hasMore) {
    return null;
  }

  return (
    <button type="button" className="secondary load-more" disabled={loading} onClick={onClick}>
      {loading ? "Loading..." : "Load more"}
    </button>
  );
}
