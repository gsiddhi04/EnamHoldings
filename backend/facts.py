"""No-LLM research sections: every number is computed from screener.in tables; observations are rule-based.

compute(sc) -> {snapshot, trajectory, balance_sheet, cash_quality, observations, fact_index, ...}
`fact_index` is a flat {key: {label, value, unit}} map. The bull/bear step may only cite those keys,
which is what keeps its numbers honest.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .screener import period_end

Series = List[Tuple[str, Optional[float]]]


def _pct(new: Optional[float], old: Optional[float]) -> Optional[float]:
    if new is None or old is None or old <= 0:   # a % change off a zero/negative base is meaningless
        return None
    return round((new / old - 1) * 100, 1)


def _cagr(series: Series, years: int) -> Optional[float]:
    if len(series) <= years:
        return None
    new, old = series[-1][1], series[-1 - years][1]
    if new is None or old is None or old <= 0 or new <= 0:
        return None
    return round(((new / old) ** (1 / years) - 1) * 100, 1)


def _ratio(a: Optional[float], b: Optional[float], nd: int = 2) -> Optional[float]:
    return round(a / b, nd) if a is not None and b else None


def _series(table: Optional[dict], key: str, drop_ttm: bool = True) -> Series:
    if not table or key not in table["rows"]:
        return []
    out = list(zip(table["periods"], table["rows"][key]))
    return [(p, v) for p, v in out if not (drop_ttm and p.upper() == "TTM")]


def _at(series: Series, label: str) -> Optional[float]:
    return next((v for p, v in series if p == label), None)


def _fmt(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    return f"{x:.0f}" if abs(x) >= 10 else f"{x:.1f}"


def _margin(table: Optional[dict], num: str = "op_profit", den: str = "revenue") -> Series:
    """screener prints margins as whole numbers; recompute from the rows for a usable decimal."""
    if not table or num not in table["rows"] or den not in table["rows"]:
        return []
    return [(p, _ratio(a * 100, b, 1) if a is not None else None)
            for p, a, b in zip(table["periods"], table["rows"][num], table["rows"][den]) if p.upper() != "TTM"]


def compute(sc: dict) -> dict:
    T = sc["tables"]
    q, pl, bs, cf, ra = (T.get(k) for k in ("quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios"))
    lender = bool(sc.get("lender"))
    facts: Dict[str, dict] = {}

    def add(key: str, label: str, value: Optional[float], unit: str) -> Optional[float]:
        if value is not None:
            facts[key] = {"label": label, "value": value, "unit": unit}
        return value

    # ---------------------------------------------------------------- latest quarter
    snapshot: dict = {"units": "₹ crore", "quarter": None}
    if q and q["periods"]:
        n = len(q["periods"])
        last = q["periods"][-1]
        ly = None
        end = period_end(last)
        if end:   # same quarter a year earlier, matched by date so a missing column can't misalign it
            ly = next((i for i, p in enumerate(q["periods"])
                       if (period_end(p) or end).replace(day=1) == end.replace(year=end.year - 1, day=1)), None)

        def row(k, idx=-1):
            r = q["rows"].get(k)
            if not r:
                return None
            try:
                return r[idx]
            except IndexError:
                return None

        def line(key, unit="₹ cr"):
            cur, prev = row(key), (row(key, -2) if n > 1 else None)
            yago = q["rows"][key][ly] if ly is not None and key in q["rows"] else None
            return {
                "value": cur, "qoq_pct": _pct(cur, prev), "yoy_pct": _pct(cur, yago),
                "prev_quarter": prev, "year_ago": yago, "unit": unit,
            }

        snapshot["quarter"] = last
        snapshot["year_ago_quarter"] = q["periods"][ly] if ly is not None else None
        snapshot["revenue"] = line("revenue")
        snapshot["operating_profit"] = line("op_profit")
        snapshot["pbt"] = line("pbt")
        snapshot["pat"] = line("pat")
        snapshot["eps"] = line("eps", "₹")
        qm = [v for _, v in _margin(q)]
        opm = qm[-1] if qm else None
        opm_yago = qm[ly] if ly is not None and qm else None
        snapshot["op_margin_pct"] = {
            "value": opm, "year_ago": opm_yago,
            "yoy_change_pp": round(opm - opm_yago, 1) if opm is not None and opm_yago is not None else None,
        }
        snapshot["net_margin_pct"] = _ratio(row("pat") * 100 if row("pat") is not None else None, row("revenue"), 1)
        if lender:
            snapshot["gross_npa_pct"] = row("gnpa")
            snapshot["net_npa_pct"] = row("nnpa")
        add("q_rev_yoy", f"Revenue growth YoY ({last})", snapshot["revenue"]["yoy_pct"], "%")
        add("q_rev_qoq", f"Revenue growth QoQ ({last})", snapshot["revenue"]["qoq_pct"], "%")
        add("q_pat_yoy", f"PAT growth YoY ({last})", snapshot["pat"]["yoy_pct"], "%")
        if lender:   # a lender's "operating profit / revenue" mixes interest income and expense: not a margin
            snapshot["op_margin_pct"] = None
        else:
            add("q_opm", f"Operating margin ({last})", opm, "%")
            add("q_opm_yoy_pp", f"Operating margin change YoY ({last})", snapshot["op_margin_pct"]["yoy_change_pp"], "pp")
        add("q_pat", f"PAT ({last})", snapshot["pat"]["value"], "₹ cr")
        if lender:
            add("gnpa", f"Gross NPA ({last})", snapshot.get("gross_npa_pct"), "%")
    snapshot["ttm_pe"] = sc.get("top_ratios", {}).get("Stock P/E")
    snapshot["market_cap_cr"] = sc.get("top_ratios", {}).get("Market Cap")
    add("pe", "Stock P/E", snapshot["ttm_pe"], "x")

    # ---------------------------------------------------------------- trajectory (annual)
    rev, pat, opm_s = _series(pl, "revenue"), _series(pl, "pat"), _margin(pl)
    traj: dict = {"last_fy": rev[-1][0] if rev else None}
    traj["revenue_cagr_pct"] = {"3y": _cagr(rev, 3), "5y": _cagr(rev, 5)}
    traj["profit_cagr_pct"] = {"3y": _cagr(pat, 3), "5y": _cagr(pat, 5)}
    traj["margin_trend"] = {
        "operating_margin_pct": [{"period": p, "value": v} for p, v in opm_s[-6:]],
        "net_margin_pct": [{"period": p, "value": _ratio(pv * 100 if pv is not None else None, rv, 1)}
                           for (p, pv), (_, rv) in zip(pat[-6:], rev[-6:])],
    }
    if len(opm_s) >= 4 and opm_s[-1][1] is not None and opm_s[-4][1] is not None:
        traj["margin_trend"]["op_margin_change_3y_pp"] = round(opm_s[-1][1] - opm_s[-4][1], 1)
    if q:
        traj["margin_trend"]["quarterly_op_margin_pct"] = [
            {"period": p, "value": v} for p, v in _margin(q)[-5:]]
    add("rev_cagr_3y", "Revenue CAGR 3y", traj["revenue_cagr_pct"]["3y"], "%")
    add("rev_cagr_5y", "Revenue CAGR 5y", traj["revenue_cagr_pct"]["5y"], "%")
    add("pat_cagr_3y", "Profit CAGR 3y", traj["profit_cagr_pct"]["3y"], "%")
    add("pat_cagr_5y", "Profit CAGR 5y", traj["profit_cagr_pct"]["5y"], "%")
    if lender:
        for k in ("operating_margin_pct", "op_margin_change_3y_pp", "quarterly_op_margin_pct"):
            traj["margin_trend"].pop(k, None)
    else:
        add("opm_change_3y_pp", "Operating margin change over 3y", traj["margin_trend"].get("op_margin_change_3y_pp"), "pp")
        if opm_s:
            add("opm_fy", f"Operating margin ({opm_s[-1][0]})", opm_s[-1][1], "%")

    # ---------------------------------------------------------------- balance sheet
    bal: dict = {"lender": lender}
    if bs:
        eq = {p: (a or 0) + (b or 0) for (p, a), (_, b) in zip(_series(bs, "equity_capital", False),
                                                                 _series(bs, "reserves", False))}
        debt = dict(_series(bs, "borrowings", False))
        de = [(p, _ratio(debt.get(p), eq.get(p))) for p in eq if p in debt]
        bal["debt_to_equity"] = [{"period": p, "value": v} for p, v in de[-4:]]
        bal["latest_period"] = de[-1][0] if de else None
        bal["borrowings_cr"] = debt.get(bal["latest_period"]) if de else None
        bal["net_worth_cr"] = round(eq[bal["latest_period"]]) if de else None
        if lender:
            bal["note"] = "Lender: borrowings/deposits fund the loan book, so leverage is structural, not a warning by itself."
        else:
            add("de_now", "Debt/equity (latest)", de[-1][1] if de else None, "x")
            if len(de) >= 4:
                add("de_3y_ago", "Debt/equity 3 periods earlier", de[-4][1], "x")
    wc = {}
    for k, label in (("wc_days", "Working-capital days"), ("debtor_days", "Debtor days"),
                     ("inventory_days", "Inventory days"), ("payable_days", "Payable days"),
                     ("ccc", "Cash-conversion cycle (days)")):
        s = [(p, v) for p, v in _series(ra, k) if v is not None]
        if s:
            wc[k] = {"label": label, "latest": s[-1][1], "period": s[-1][0],
                     "three_years_ago": s[-4][1] if len(s) >= 4 else None}
    bal["working_capital"] = wc or None
    if "wc_days" in wc:
        add("wc_days", "Working-capital days (latest FY)", wc["wc_days"]["latest"], "days")
        add("wc_days_3y", "Working-capital days 3y earlier", wc["wc_days"]["three_years_ago"], "days")
    roce = [(p, v) for p, v in _series(ra, "roce") if v is not None]
    roe = [(p, v) for p, v in _series(ra, "roe") if v is not None]
    for nm, s in (("roce", roce), ("roe", roe)):
        if s:
            bal[nm + "_pct"] = {"latest": s[-1][1], "period": s[-1][0], "three_years_ago": s[-4][1] if len(s) >= 4 else None}
            add(nm, f"{nm.upper()} ({s[-1][0]})", s[-1][1], "%")

    # ---------------------------------------------------------------- cash quality
    cash: dict = {"lender": lender}
    cfo, fcf = _series(cf, "cfo"), dict(_series(cf, "fcf"))
    pat_d = dict(pat)
    pairs = [(p, v, pat_d.get(p)) for p, v in cfo if v is not None and pat_d.get(p)][-5:]
    cash["years"] = [{"period": p, "cfo_cr": c, "pat_cr": n, "cfo_to_pat": _ratio(c, n), "fcf_cr": fcf.get(p)}
                     for p, c, n in pairs]
    if lender:
        cash["note"] = "Not meaningful for lenders: loan growth and deposits run through operating cash flow."
    elif pairs:
        cash["latest_cfo_to_pat"] = _ratio(pairs[-1][1], pairs[-1][2])
        if len(pairs) >= 3:
            cash["cfo_to_pat_3y"] = _ratio(sum(c for _, c, _ in pairs[-3:]), sum(n for _, _, n in pairs[-3:]))
        add("cfo_pat", f"Operating cash flow ÷ net profit ({pairs[-1][0]})", cash["latest_cfo_to_pat"], "x")
        add("cfo_pat_3y", "Operating cash flow ÷ net profit (3y cumulative)", cash.get("cfo_to_pat_3y"), "x")
        add("fcf", f"Free cash flow ({pairs[-1][0]})", fcf.get(pairs[-1][0]), "₹ cr")

    other_inc, pbt = _series(pl, "other_income"), _series(pl, "pbt")
    if other_inc and pbt and pbt[-1][1] and not lender:
        add("oi_share_pbt", f"Other income as % of PBT ({pbt[-1][0]})", _ratio((other_inc[-1][1] or 0) * 100, pbt[-1][1], 1), "%")

    def last(series: Series, n: int) -> List[dict]:
        return [{"period": p, "value": v} for p, v in series[-n:]]

    charts = {"annual_revenue": last(rev, 8), "annual_pat": last(pat, 8),
              "quarterly_revenue": last(_series(q, "revenue"), 8), "quarterly_pat": last(_series(q, "pat"), 8)}
    if not lender:
        charts["annual_op_margin"] = last(opm_s, 8)

    return {
        "charts": charts,
        "name": sc.get("name"), "basis": sc.get("basis"), "lender": lender,
        "snapshot": snapshot, "trajectory": traj, "balance_sheet": bal, "cash_quality": cash,
        "observations": observations(facts, lender),
        "fact_index": facts,
    }


def observations(f: Dict[str, dict], lender: bool) -> List[dict]:
    """Plain-English readings of the numbers. Rules only; each carries the fact keys it rests on."""
    v = {k: x["value"] for k, x in f.items()}
    out: List[dict] = []

    def say(tone: str, text: str, *keys: str) -> None:
        out.append({"tone": tone, "text": text, "facts": list(keys)})

    r3, r5 = v.get("rev_cagr_3y"), v.get("rev_cagr_5y")
    if r3 is not None and r5 is not None:
        if r3 <= r5 - 2:
            say("watch", f"Revenue growth slowing: {_fmt(r3)}% 3y vs {_fmt(r5)}% 5y CAGR.", "rev_cagr_3y", "rev_cagr_5y")
        elif r3 >= r5 + 2:
            say("good", f"Revenue growth accelerating: {_fmt(r3)}% 3y vs {_fmt(r5)}% 5y CAGR.", "rev_cagr_3y", "rev_cagr_5y")
        else:
            say("neutral", f"Revenue growth steady: {_fmt(r3)}% 3y vs {_fmt(r5)}% 5y CAGR.", "rev_cagr_3y", "rev_cagr_5y")
    p3, p5 = v.get("pat_cagr_3y"), v.get("pat_cagr_5y")
    if p3 is not None and r3 is not None and abs(p3 - r3) >= 4 and not lender:
        if p3 > r3:
            say("good", f"Profit is outgrowing sales ({_fmt(p3)}% vs {_fmt(r3)}% over 3y): margins are widening.", "pat_cagr_3y", "rev_cagr_3y")
        else:
            say("watch", f"Profit is lagging sales ({_fmt(p3)}% vs {_fmt(r3)}% over 3y): margins are being squeezed.", "pat_cagr_3y", "rev_cagr_3y")
    elif p3 is not None and p5 is not None and p3 <= p5 - 4:
        say("watch", f"Profit growth slowing: {_fmt(p3)}% 3y vs {_fmt(p5)}% 5y CAGR.", "pat_cagr_3y", "pat_cagr_5y")

    ry, py = v.get("q_rev_yoy"), v.get("q_pat_yoy")
    if ry is not None and py is not None:
        if ry > 0 and py < 0:
            say("watch", f"Latest quarter: revenue up {_fmt(ry)}% YoY but profit down {_fmt(abs(py))}%.", "q_rev_yoy", "q_pat_yoy")
        elif py >= ry + 5 and py > 0:
            say("good", f"Latest quarter: profit up {_fmt(py)}% YoY on {_fmt(ry)}% revenue growth.", "q_pat_yoy", "q_rev_yoy")
        elif ry < 0:
            say("watch", f"Latest quarter: revenue fell {_fmt(abs(ry))}% YoY.", "q_rev_yoy")

    d = v.get("opm_change_3y_pp")
    if d is not None and abs(d) >= 2 and not lender:
        say("good" if d > 0 else "watch",
            f"Operating margin {'expanded' if d > 0 else 'compressed'} {_fmt(abs(d))} pts over 3 years (now {_fmt(v.get('opm_fy'))}%).",
            "opm_change_3y_pp", "opm_fy")
    qd = v.get("q_opm_yoy_pp")
    if qd is not None and abs(qd) >= 1.5 and not lender:
        say("good" if qd > 0 else "watch", f"Latest-quarter margin is {_fmt(abs(qd))} pts {'above' if qd > 0 else 'below'} a year ago.", "q_opm_yoy_pp")

    if lender and v.get("gnpa") is not None:
        say("neutral", f"Gross NPAs are {_fmt(v['gnpa'])}% of loans in the latest quarter.", "gnpa")

    de, de3 = v.get("de_now"), v.get("de_3y_ago")
    if de is not None and not lender:
        if de < 0.1:
            say("good", f"Virtually debt-free (debt/equity {de:.2f}).", "de_now")
        elif de > 1:
            say("watch", f"Leveraged: debt/equity {de:.2f}.", "de_now")
        if de3 is not None and de - de3 >= 0.3:
            say("watch", f"Debt/equity up from {de3:.2f} to {de:.2f} in three periods.", "de_now", "de_3y_ago")
        elif de3 is not None and de3 - de >= 0.3:
            say("good", f"Deleveraging: debt/equity down from {de3:.2f} to {de:.2f}.", "de_now", "de_3y_ago")

    w, w3 = v.get("wc_days"), v.get("wc_days_3y")
    if w is not None and w3 is not None and not lender:
        if w - w3 >= 10:
            say("watch", f"Working-capital cycle lengthening: {_fmt(w)} days vs {_fmt(w3)} three years ago.", "wc_days", "wc_days_3y")
        elif w3 - w >= 10:
            say("good", f"Working-capital cycle shortening: {_fmt(w)} days vs {_fmt(w3)} three years ago.", "wc_days", "wc_days_3y")

    c, c3 = v.get("cfo_pat"), v.get("cfo_pat_3y")
    if c is not None and not lender:
        base = c3 if c3 is not None else c
        if base < 0.7:
            say("watch", f"Profits are not turning into cash: operating cash flow is {base:.2f}x net profit"
                         f"{' over 3 years' if c3 is not None else ''}.", "cfo_pat_3y" if c3 is not None else "cfo_pat")
        elif base >= 1:
            say("good", f"Strong cash conversion: operating cash flow is {base:.2f}x net profit"
                        f"{' over 3 years' if c3 is not None else ''}.", "cfo_pat_3y" if c3 is not None else "cfo_pat")

    oi = v.get("oi_share_pbt")
    if oi is not None and oi >= 15 and not lender:
        say("watch", f"Other income is {_fmt(oi)}% of pre-tax profit: part of earnings isn't from the core business.", "oi_share_pbt")

    return out
