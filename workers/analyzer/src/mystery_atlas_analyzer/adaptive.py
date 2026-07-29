from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from .model_adapters import ModelContentIdleError, ModelOutputTruncatedError

logger = logging.getLogger(__name__)

WorkT = TypeVar("WorkT")
ResultT = TypeVar("ResultT")


def run_adaptive_synthesis(
    work: WorkT,
    *,
    task: str,
    generate: Callable[[WorkT], ResultT],
    can_split: Callable[[WorkT], bool],
    split: Callable[[WorkT], list[WorkT]],
    combine: Callable[[list[ResultT]], ResultT],
    describe: Callable[[WorkT], dict[str, object]] | None = None,
    cache_key: Callable[[WorkT], str] | None = None,
    cached: dict[str, ResultT] | None = None,
    on_completed: Callable[[str, ResultT], None] | None = None,
    on_split: Callable[[WorkT, Exception, list[WorkT]], None] | None = None,
    cache_combined: bool = True,
) -> ResultT:
    """Run a bounded model task and recursively split only recoverable failures.

    Transport retries stay inside the model adapter. This controller owns the
    semantic recovery boundary: one content-idle retry at the smallest unit,
    recursive splitting when the task policy allows it, and deterministic
    combination of successful children.
    """

    key = cache_key(work) if cache_key else ""
    if key and cached is not None and key in cached:
        return cached[key]

    def complete(result: ResultT, *, combined: bool = False) -> ResultT:
        if combined and not cache_combined:
            return result
        if key and cached is not None:
            cached[key] = result
        if key and on_completed:
            on_completed(key, result)
        return result

    try:
        return complete(generate(work))
    except (ModelOutputTruncatedError, ModelContentIdleError) as exc:
        metadata = describe(work) if describe else {}
        if can_split(work):
            children = split(work)
            if len(children) < 2:
                raise RuntimeError(
                    f"adaptive split policy for {task} returned fewer than two children"
                ) from exc
            logger.warning(
                "adaptive synthesis split task=%s error=%s metadata=%s children=%s",
                task,
                type(exc).__name__,
                metadata,
                len(children),
            )
            if on_split:
                on_split(work, exc, children)
            return complete(combine(
                [
                    run_adaptive_synthesis(
                        child,
                        task=task,
                        generate=generate,
                        can_split=can_split,
                        split=split,
                        combine=combine,
                        describe=describe,
                        cache_key=cache_key,
                        cached=cached,
                        on_completed=on_completed,
                        on_split=on_split,
                        cache_combined=cache_combined,
                    )
                    for child in children
                ]
            ), combined=True)
        if isinstance(exc, ModelContentIdleError):
            logger.warning(
                "adaptive synthesis retry task=%s error=%s metadata=%s",
                task,
                type(exc).__name__,
                metadata,
            )
            return complete(generate(work))
        raise
