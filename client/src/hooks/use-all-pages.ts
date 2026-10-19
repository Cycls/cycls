import { useEffect } from "react";

// Clerk hands its lists over a page at a time (10 unless asked) and fetches the next only when told. Pass `ALL` as the
// list's params and this hook to the list, and it keeps asking until there is no next page.
export const ALL = { infinite: true, pageSize: 100, keepPreviousData: true } as const;

type Pages = { hasNextPage?: boolean; isFetching?: boolean; isLoading?: boolean; fetchNext?: () => void } | null | undefined;

export function useAllPages(...lists: Pages[]) {
  const due = lists.map((l) => !!(l?.hasNextPage && !l.isFetching));
  useEffect(() => {
    lists.forEach((l, i) => { if (due[i]) l?.fetchNext?.(); });
  }, [due.join()]);   // eslint-disable-line react-hooks/exhaustive-deps
}

// Whether a list has every page: until then, a name missing from it may just not have arrived yet.
export const complete = (list: Pages) => !!list && !list.isLoading && !list.hasNextPage;
