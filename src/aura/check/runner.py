"""Run the sandbox checks and print their results."""

from collections.abc import Callable

from aura.check.checks import CHECKS, RUN_CHECKS

STATUS = {True: "\033[32mPASS\033[0m", False: "\033[31mFAIL\033[0m"}  # green, red


def report(description: str, check: Callable[[], bool], width: int) -> bool:
    """
    Run one check and print its description, dotted out to a green PASS or red FAIL.

    An error counts as a failure and is printed after FAIL, so the remaining checks
    still run.

    Args:
        description: What the check confirms.
        check: Function returning whether the check passed.
        width: Length of the longest description, so every PASS/FAIL lines up.

    Returns:
        Whether the check passed.
    """
    try:
        passed, error = check(), ""
    except Exception as e:
        passed, error = False, f"  {e}"
    leader = f"{description} ".ljust(width + 4, ".")
    print(f"{leader} {STATUS[passed]}{error}", flush=True)
    return passed


def check(runs: bool) -> bool:
    """
    Run every sandbox check, printing each result.

    Args:
        runs: Whether to also run `RUN_CHECKS`, which do real (paid) runs.

    Returns:
        Whether every check passed.
    """
    checks = {**CHECKS, **RUN_CHECKS} if runs else CHECKS
    width = max(map(len, checks))
    results = [report(description, fn, width) for description, fn in checks.items()]
    return all(results)  # after running every check, not stopping at a failure
