"""Tests for src/aura/check/runner.py; the checks themselves need Docker."""

import pytest

from aura.check.runner import STATUS, report


def broken() -> bool:
    raise RuntimeError("gateway down")


@pytest.mark.parametrize(
    ("fn", "passed", "suffix"),
    [
        (lambda: True, True, STATUS[True]),
        (lambda: False, False, STATUS[False]),
        (broken, False, f"{STATUS[False]}  gateway down"),
    ],
)
def test_report_prints_result(capsys, fn, passed, suffix):
    assert report("Thing safe", fn, width=12) is passed
    assert capsys.readouterr().out.strip() == f"Thing safe ..... {suffix}"
