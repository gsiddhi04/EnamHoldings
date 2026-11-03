"""Research helpers: facts from tables, promise plumbing, business guards. No network, no model."""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import business, facts, limits, research


def table(periods, **rows):
    return {"periods": periods, "rows": rows}


def screener_stub(lender=False):
    years = [f"Mar {y}" for y in range(2019, 2027)]
    q = ["Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"]
    return {"name": "Acme Ltd", "basis": "consolidated", "lender": lender, "top_ratios": {"Stock P/E": 20.0, "Market Cap": 1000.0},
            "concalls": [], "annual_reports": [],
            "tables": {
                "quarters": table(q, revenue=[100, 105, 110, 112, 120], op_profit=[20, 21, 22, 22, 24], pbt=[18, 19, 20, 20, 22],
                                  pat=[14, 15, 16, 16, 17], eps=[1, 1, 1, 1, 1], opm=[20] * 5),
                "profit-loss": table(years, revenue=[100, 110, 120, 140, 160, 190, 230, 280], op_profit=[20, 22, 24, 28, 32, 38, 46, 56],
                                     pat=[10, 11, 12, 14, 16, 19, 23, 28], pbt=[13, 14, 16, 18, 21, 25, 30, 36],
                                     other_income=[1] * 8, opm=[20] * 8),
                "balance-sheet": table(years, equity_capital=[10] * 8, reserves=[90, 100, 110, 120, 130, 140, 150, 160], borrowings=[5, 5, 6, 8, 10, 12, 14, 16]),
                "cash-flow": table(years, cfo=[8, 9, 10, 12, 13, 15, 18, 22], fcf=[5] * 8),
                "ratios": table(years, wc_days=[30, 31, 32, 33, 35, 38, 40, 45], roce=[15] * 8),
            }}


def test_cagr_matches_hand_calculation():
    f = facts.compute(screener_stub())
    assert f["trajectory"]["revenue_cagr_pct"]["3y"] == round(((280 / 160) ** (1 / 3) - 1) * 100, 1)
    assert f["snapshot"]["revenue"]["yoy_pct"] == 20.0 and f["snapshot"]["revenue"]["qoq_pct"] == round((120 / 112 - 1) * 100, 1)


def test_observations_cite_their_numbers_and_flag_working_capital():
    f = facts.compute(screener_stub())
    text = " ".join(o["text"] for o in f["observations"])
    assert "Working-capital cycle lengthening" in text        # 45 days vs 33 three years ago
    assert all(set(o["facts"]) <= set(f["fact_index"]) for o in f["observations"])


def test_lender_suppresses_margin_leverage_and_cash_conversion_facts():
    f = facts.compute(screener_stub(lender=True))
    for banned in ("q_opm", "opm_fy", "opm_change_3y_pp", "de_now", "cfo_pat", "oi_share_pbt"):
        assert banned not in f["fact_index"]
    assert f["snapshot"]["op_margin_pct"] is None and f["cash_quality"]["lender"] is True


def test_credibility_is_arithmetic_on_verdicts():
    assert research.credibility(["delivered", "delivered", "partly", "missed"]) == {"credibility": "mixed", "score": 62, "scored": 4}
    assert research.credibility(["delivered"] * 3)["credibility"] == "high"
    assert research.credibility(["too early", "unverifiable"]) == {"credibility": None, "score": None, "scored": 0}


def test_guidance_filter_keeps_forward_looking_numeric_paragraphs_only():
    pages = ["Rahul Shah: We expect operating margin to be in the range of 26% to 28% over the next two years as we invest. "
             "This is our target going forward and we are confident.\n"
             "Analyst One: Do you expect margins to recover to 28% next year?\n"
             "Rahul Shah: The weather was pleasant last quarter and the team enjoyed the offsite in Goa with many colleagues present."]
    chunks = research.guidance_chunks(pages)
    assert len(chunks) == 1 and "26% to 28%" in chunks[0]


def test_quote_normalisation_survives_ligatures_and_spacing():
    assert research._norm("the ﬁrst  quarter’s growth") in research._norm("In the first quarter's growth we saw")


def test_reported_quarter_is_latest_quarter_ended_before_call_month():
    qs = ["Mar 2026", "Jun 2026", "Sep 2026"]
    assert research._reported_quarter("Jul 2026", qs) == "Jun 2026"
    assert research._reported_quarter("Oct 2026", qs) == "Sep 2026"


def test_ask_word_cap_and_indian_grouping():
    long = ". ".join(f"Sentence number {i} says something" for i in range(60)) + "."
    assert len(research.cap_words(long).split()) <= research.ASK_MAX_WORDS
    assert research._indian(73188) == "73,188" and research._indian(1234567) == "12,34,567" and research._indian(-5200) == "-5,200"


def test_business_numbers_must_appear_in_source_text():
    assert business._appears(103363.0, "BFSI 1,03,363 and 103,363") is True
    assert business._appears(999.0, "BFSI 103,363") is False


def test_business_mix_dropped_when_segments_do_not_reconcile(conn, monkeypatch, tmp_path):
    sc = screener_stub()
    sc["annual_reports"] = [{"label": "Annual Report 2026", "url": "https://x/y.pdf"}]
    monkeypatch.setattr(business, "download", lambda *a, **k: str(tmp_path / "x.pdf"))
    pages = ["Our business overview we are a company operating in many segments. " * 40] * 3 + \
            ["Segment information segment revenue segment results operating segments segment A 100 segment B 120 revenue 220 " + " ".join(f"{n},000" for n in range(20)) + " " * 900]
    monkeypatch.setattr(business, "read_pages", lambda p: pages)
    reply = {"what_it_does": "Makes things.", "segments": [{"name": "A", "description": "a", "revenue": 100}, {"name": "B", "description": "b", "revenue": 120}],
             "segment_unit": "crore", "segment_basis": "consolidated"}
    monkeypatch.setattr(business.llm, "complete", lambda *a, **k: json.dumps(reply))
    out = business.build(conn, "ACME", sc)
    assert out["available"] and out["segments"][0]["share_pct"] is None   # total 220 vs reported FY26 revenue 280: 21% off, so no mix
    assert out["total_vs_reported_pct"] == round((220 / 280 - 1) * 100, 1)


def test_rate_limiter_blocks_the_21st_ask_and_isolates_clients():
    req = lambda ip: SimpleNamespace(headers={"x-forwarded-for": ip}, client=None)
    for _ in range(20):
        limits.check(req("198.51.100.1"), "t-ask", 20, 3600, "questions")
    with pytest.raises(HTTPException) as e:
        limits.check(req("198.51.100.1"), "t-ask", 20, 3600, "questions")
    assert e.value.status_code == 429
    limits.check(req("198.51.100.2"), "t-ask", 20, 3600, "questions")    # another client is unaffected
