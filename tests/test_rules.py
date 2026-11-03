"""The classification ladder: the examples in the brief, plus regressions found on real filings."""
import pytest

from backend.rules import classify


@pytest.mark.parametrize("desc,text,cat,lo,hi", [
    ("Outcome of Board Meeting", "Board approved the financial results for the quarter ended 30 September 2026", "results", 85, 100),
    ("Intimation of Board Meeting", "Board meeting to consider the financial results for the quarter", "results", 20, 40),
    ("Change in Directorate", "Appointment of Mr X as Chief Financial Officer", "management_change", 80, 100),
    ("Change in Directorate", "Appointment of Ms Y as Non-Executive Independent Director", "management_change", 30, 50),
    ("Acquisition", "Acquisition of 100% stake in ABC Ltd", "M&A", 75, 100),
    ("Trading Window", "Closure of trading window", "unclassified", 0, 10),
    ("Employee Stock Option Plan", "Allotment of shares under ESOP", "unclassified", 0, 10),
    ("Earnings Call", "Transcript of the earnings call", "earnings_call", 35, 45),
    ("Newspaper Publication", "Copy of newspaper advertisement of financial results", "results", 0, 10),
])
def test_ladder(desc, text, cat, lo, hi):
    got = classify(desc, text)
    assert got is not None
    category, priority, why, _rule = got
    assert category == cat and lo <= priority <= hi, (category, priority, why)


def test_non_executive_director_is_not_top_level():
    _, pri, _, _ = classify("Change in Directorate", "Appointment of Mr Z as Non-Executive Director")
    assert pri < 60            # regression: used to read as a top-level appointment and flood the brief


def test_downgrade_nudges_rating_up():
    _, base, _, _ = classify("Credit Rating", "Rating reaffirmed by CRISIL")
    _, down, _, _ = classify("Credit Rating", "CRISIL downgraded the rating of the company")
    assert down > base + 30


def test_unmatched_returns_none():
    assert classify("Zzz", "completely unrelated words qqq") is None
