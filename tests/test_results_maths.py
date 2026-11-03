"""The model only transcribes a table; Python does the maths and decides whether to trust it."""
from backend.enrich import compute_results, pct_change

ITC = {"basis": "consolidated", "unit": "crore", "period_type": "quarter", "periods": ["a", "b", "c"], "is_bank_or_nbfc": False,
       "revenue": [30578.40, 29523.30, 21255.86], "other_income": [507.36, 655.71, 584.40], "finance_costs": [38.27, 39.78, 20.05],
       "depreciation": [490.60, 427.73, 434.80], "pbt": [5694.62, 5860.85, 6978.68], "tax": [1465.29, 1352.06, 1792.13],
       "pat": [4229.33, 4508.79, 5186.55], "operating_profit": None}


def test_ebitda_is_pbt_plus_finance_plus_depreciation_minus_other_income():
    r = compute_results(dict(ITC))
    assert r["metrics"]["ebitda"]["values"][0] == round(5694.62 + 38.27 + 490.60 - 507.36, 2)
    assert r["check_ok"] is True


def test_growth_rates_and_margins():
    r = compute_results(dict(ITC))
    assert r["metrics"]["pat"]["yoy_pct"] == round((4229.33 / 5186.55 - 1) * 100, 1)
    assert r["metrics"]["revenue"]["qoq_pct"] == round((30578.40 / 29523.30 - 1) * 100, 1)
    assert r["metrics"]["pat"]["margin_pct"][0] == round(4229.33 / 30578.40 * 100, 1)


def test_self_check_fails_when_pat_is_misread():
    bad = dict(ITC, pat=[4129.33, 4508.79, 5186.55])        # 100 crore off: more than rounding
    r = compute_results(bad)
    assert r["check_ok"] is False


def test_unit_conversion_to_crore():
    millions = {k: ([x * 10 for x in v] if isinstance(v, list) and k not in ("periods",) else v) for k, v in ITC.items()}
    millions["unit"] = "million"
    r = compute_results(millions)
    assert abs(r["metrics"]["revenue"]["values"][0] - 30578.40) < 0.01


def test_three_decimals_flag_ocr_thousands_separator_misread():
    scanned = dict(ITC, revenue=[533.402, 524.551, 423.323], pbt=[31.658, 43.413, 42.909], tax=[7.509, 9.892, 9.881],
                   pat=[24.149, 33.521, 33.028], other_income=[4.294, 18.731, 9.661], finance_costs=[0.677, 0.635, 0.572],
                   depreciation=[19.596, 17.8, 17.028])
    assert compute_results(scanned)["check_ok"] is False


def test_bank_uses_operating_profit_before_provisions():
    bank = dict(ITC, is_bank_or_nbfc=True, operating_profit=[1000.0, 900.0, 800.0])
    assert compute_results(bank)["metrics"]["ebitda"]["values"][0] == 1000.0


def test_pct_change_guards_zero_and_negative_base():
    assert pct_change(10, 0) is None and pct_change(10, -5) is None and pct_change(None, 5) is None


def _rating(monkeypatch, conn, reply):
    import json
    from backend import enrich
    monkeypatch.setattr(enrich.pdfs, "get_pages", lambda *a, **k: ["CRISIL rating letter"])
    monkeypatch.setattr(enrich.llm, "complete", lambda *a, **k: json.dumps(reply))
    return enrich.enrich_rating(conn, {"id": "1", "symbol": "ACME", "attachment": "x"})


def test_downgrade_lands_above_the_fold_and_reaffirmation_does_not(conn, monkeypatch):
    down, line = _rating(monkeypatch, conn, {"agency": "CRISIL", "action": "downgraded", "rating_from": "AA", "rating_to": "A+", "outlook": "negative"})
    assert down["priority"] == 75 and "downgrades" in line and "from AA" in line
    same, _ = _rating(monkeypatch, conn, {"agency": "ICRA", "action": "reaffirmed", "rating_to": "AA", "outlook": "stable"})
    assert same["priority"] == 20
    warn, _ = _rating(monkeypatch, conn, {"agency": "ICRA", "action": "reaffirmed", "rating_to": "AA", "outlook": "negative"})
    assert warn["priority"] == 55            # a negative outlook is still a warning
