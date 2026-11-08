"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Display numbered initialization activities and their outcomes.
"""

from contextlib import contextmanager
import time


@contextmanager
def initialization_step(number: int, activity: str):
    """Display an activity immediately and append its outcome and duration.

    Args:
        number: Activity number in the initialization sequence.
        activity: English description without secrets or credential values.

    Yields:
        Control to the initialization activity.
    """
    print(f"[{number}] {activity} ... ", end="", flush=True)
    started = time.perf_counter()
    try:
        yield
    except BaseException:
        print("FAILED", flush=True)
        raise
    else:
        print(f"OK ({time.perf_counter() - started:.2f}s)", flush=True)
