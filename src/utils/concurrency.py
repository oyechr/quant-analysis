"""
Concurrency helpers

Data fetching is network-bound (Yahoo Finance), so a small thread pool gives a
near-linear speedup for multi-ticker commands. Keep worker counts modest:
Yahoo rate-limits aggressive clients.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Iterator, Optional, Tuple, TypeVar

T = TypeVar("T")
R = TypeVar("R")

DEFAULT_WORKERS = 4


def run_concurrently(
    fn: Callable[[T], R],
    items: Iterable[T],
    workers: int = DEFAULT_WORKERS,
) -> Iterator[Tuple[T, Optional[R], Optional[Exception]]]:
    """
    Apply fn to each item on a thread pool, yielding results as they complete.

    Exceptions are captured per item rather than raised, so one bad ticker
    doesn't abort a batch.

    Yields:
        (item, result, None) on success or (item, None, exception) on failure,
        in completion order (not input order).
    """
    items = list(items)
    if workers <= 1 or len(items) <= 1:
        for item in items:
            try:
                yield item, fn(item), None
            except Exception as e:
                yield item, None, e
        return

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, item): item for item in items}
        for future in as_completed(futures):
            item = futures[future]
            try:
                yield item, future.result(), None
            except Exception as e:
                yield item, None, e
