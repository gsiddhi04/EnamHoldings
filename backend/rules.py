"""Ordered regex rules: first match wins. Each rule = (id, category, pattern, base priority 0-100, why).

Matched against "<NSE subject> | <filing text>". Order encodes precedence: routine noise first (so an
ESOP allotment never reads as a fund raise), then specific-before-generic (a concall *transcript* about
results is an earnings_call, not a results filing). Keyword nudges then adjust the base score.
"""
from __future__ import annotations

import re

_F = re.I | re.S


def _all(*parts: str) -> str:
    """AND of several patterns (order-free) via lookaheads."""
    return "".join(f"(?=.*(?:{p}))" for p in parts)


_ACTION = r"appoint|resign|retire|cessation|cease|demise|succession|change in (the )?(management|director|managing|chief|key)"
_TOP_ROLE = (r"\bceo\b|\bcfo\b|\bcoo\b|\bcto\b|chief (executive|financial|operating|technology|information) officer"
             r"|managing director|\bmd\b|whole[- ]?time director|(?<!non-)(?<!non- )(?<!non )executive director|key managerial|senior management"
             r"|chair(man|person)(?! of (the )?\w* ?committee)")
_RESULTS_WORDS = r"financial results|results|quarter|half[- ]year|year ended"

# (id, category, pattern, base, why)
RULES = [
    # ---- routine noise first -------------------------------------------------------------
    ("trading_window", "unclassified", r"trading window|closure of trading", 5, "Trading window notice - routine"),
    ("compliance_cert", "unclassified",
     r"certificate under sebi|compliance certificate|regulation 74\(5\)|regulation 40\(9\)|regulation 13\(3\)|regulation 24a"
     r"|secretarial compliance|investor complaints|shareholding pattern|reconciliation of share capital|statement of deviation"
     r"|depositories and participants", 5, "Compliance certificate - routine"),
    ("esop", "unclassified", r"\besop|\besos\b|\besps\b|employee stock|stock options?", 5, "ESOP allotment - routine"),
    ("esg", "unclassified", r"\besg\b|sustainability report|\bbrsr\b|business responsibility", 6, "ESG / sustainability report"),
    ("newspaper_results_ad", "results", _all("newspaper", r"results?"), 5, "Newspaper ad of results - already filed"),
    ("newspaper_ad", "unclassified", r"newspaper", 5, "Newspaper advertisement - routine"),

    # ---- earnings calls / investor meetings (before results: transcripts quote the results) ----
    ("call_transcript", "earnings_call", r"transcript", 40, "Concall transcript - guidance and tone"),
    ("call_audio", "earnings_call", r"audio (recording|link)|recording of|audio of", 22, "Concall recording"),
    ("call_notice", "earnings_call", r"earnings call|conference call|concall|earnings conference", 30, "Earnings call scheduled"),

    # ---- results ---------------------------------------------------------------------------
    ("results_meeting_date", "results",
     _all(r"board meeting|meeting of the board", r"intimation|scheduled|will be held|to be held|to consider|prior intimation",
          r"financial results|results") + r"(?!.*(outcome|approved|submitted|considered and approved|has considered))",
     30, "Results board-meeting date"),
    ("results_press", "results",
     _all(r"press release|media release|earnings release|shareholders?.? letter|letter to shareholders|investor release",
          _RESULTS_WORDS), 55, "Results press release / shareholder letter"),
    ("results_deck", "results",
     _all(r"presentation|\bdeck\b|fact ?sheet|data ?sheet", r"result|quarter|\bq[1-4]\b|\bh[12]\b|fy ?\d\d|half[- ]year"),
     50, "Results presentation"),
    ("annual_report", "agm_egm", r"annual report|integrated report", 30, "Annual report published"),
    ("results_filing", "results",
     r"financial results|unaudited|audited (standalone|consolidated)|results for the (quarter|period|half|year)"
     r"|quarter (and (half|nine)[ -]?(year|months?) )?ended|half[- ]year ended|year ended", 92, "Financial results filed"),

    # ---- auditors (after results: results text cites the statutory auditors) -------------------
    ("auditor", "unclassified", r"(statutory|secretarial|internal|cost) auditors?|auditor rotation", 8, "Auditor change - routine"),

    # ---- management --------------------------------------------------------------------------
    ("cs_officer", "management_change", _all(_ACTION, r"company secretary|compliance officer"), 25, "Company secretary / compliance officer"),
    ("mgmt_top", "management_change", _all(_ACTION, _TOP_ROLE), 86, "Top-level management change (CEO/CFO/MD)"),
    ("mgmt_indep", "management_change", _all(_ACTION, r"independent director"), 40, "Independent director change"),
    ("mgmt_generic", "management_change",
     r"^(change in management|change in director|appointment|re-?appointment|resignation|retirement|cessation)",
     55, "Director / KMP change"),

    # ---- pledging & insider (before M&A: SAST disclosures say "acquisition") -------------------
    ("pledge_invoked", "pledging", _all(r"pledge|encumbrance", r"invok|enforce"), 85, "Pledge invoked by lender"),
    ("pledge_released", "pledging",
     r"(releas|revok|cancell?ation|vacat).{0,60}(pledge|encumbrance)|(pledge|encumbrance).{0,60}(releas|revok|vacat)",
     25, "Pledge released"),
    ("pledge_created", "pledging", r"pledge|encumbrance|encumber", 70, "Promoter pledge created / changed"),
    ("insider_trade", "insider_trading",
     r"insider trading|regulation 7\(|regulation 29|regulation 10\(|substantial acquisition"
     r"|(sale|purchase|acquisition|disposal) of shares by (the )?promoter|promoter.{0,40}(bought|sold|acquired|disposed)",
     35, "Promoter / insider share trade"),

    # ---- legal (insolvency & regulator orders are specific enough to beat M&A) ------------------
    ("insolvency", "litigation", r"insolvency|\bcirp\b|winding[- ]up|bankruptcy|\bibc\b", 65, "Insolvency proceedings"),
    ("regulatory_action", "litigation",
     r"action\(s\) (taken|initiated)|orders? passed|show[- ]cause|penalty|\bfine\b|adjudicat|warning letter|demand (order|notice)"
     r"|sebi order|income tax|gst (authorities|demand)|search and seizure|enforcement directorate|\bcbi\b|investigation",
     50, "Regulatory action / order"),

    # ---- corporate actions -----------------------------------------------------------------------
    ("ma_subsidiary", "M&A",
     r"incorporat(ion|ed)|investment in (a |the )?(wholly[- ]owned )?(subsidiary|joint venture)|new subsidiary",
     50, "Subsidiary set-up / investment"),
    ("ma_major", "M&A",
     r"^(acquisition|amalgamation/merger|other restructuring)|acquisition|acquire|amalgamation|merger|demerger"
     r"|scheme of arrangement|joint venture|business transfer|share purchase agreement|slump sale|divest|disposal of"
     r"|sale of (stake|shares|business|undertaking)|stake (sale|purchase)|takeover|open offer|strategic investment",
     80, "Acquisition / merger / stake change"),
    ("fund_equity", "fund_raise",
     r"buy[- ]?back|\bqip\b|qualified institutional|rights issue|rights entitlement|preferential (issue|allotment|basis)"
     r"|warrants|fund[- ]?raising|raising of funds|raise funds|\bfccb\b|\becb\b|follow[- ]on|\bfpo\b|offer for sale|institutional placement",
     75, "Equity raise / buyback"),
    ("fund_debt", "fund_raise",
     r"non[- ]convertible|\bncds?\b|commercial paper|debentures?|\bbonds?\b|term loan|borrowing", 40, "Debt raise - routine funding"),
    ("dividend", "dividend", r"dividend", 40, "Dividend declared"),
    ("bonus_split", "bonus_split", r"bonus (issue|shares?|equity)|stock split|split of (equity )?shares|sub-?division", 50,
     "Bonus / split - share count changes"),
    ("capex", "capex",
     r"capex|capital expenditure|capacity (expansion|addition)|new (manufacturing|plant|facility|factory|unit|refinery)"
     r"|greenfield|brownfield|expansion of (plant|capacity|facility)", 55, "Capex / capacity expansion"),

    # ---- credit rating (base 30: downgrade nudge +45 = 75; reaffirmation pinned low) ------------------
    ("rating_reaffirmed", "credit_rating", _all(r"rating", r"reaffirm|re-affirm|reiterat|retain|maintain"), 20, "Rating reaffirmed"),
    ("rating_action", "credit_rating",
     r"credit rating|\brating\b|crisil|\bicra\b|care ratings|india ratings|ind-ra|brickwork|acuite|moody|fitch", 30, "Rating action"),

    # ---- news flow --------------------------------------------------------------------------------------
    ("order_win", "press_release",
     r"bagging|receiving of orders?|order (win|received|worth|inflow)|letter of (award|intent)|\bloa\b|\bloi\b|contract (awarded|win)"
     r"|bagged|secures? (an? )?(order|contract)|awarded (an? )?(order|contract)", 55, "Order win"),
    ("rumour", "press_release",
     r"rumou?r|news verification|market (rumour|speculation)|clarification.{0,40}(news|media|report)|price movement",
     45, "Exchange queried a news report / price move"),
    ("business_update", "press_release",
     r"monthly business update|business update|operational update|quarterly update|production update|production volume|sales (update|volume)|store opening",
     40, "Business / operating update"),
    ("press_release", "press_release", r"press release|media release|media statement", 25, "Press release"),

    # ---- governance meetings ---------------------------------------------------------------------------------
    ("postal_ballot", "postal_ballot", r"postal ballot", 15, "Postal ballot notice / result"),
    ("agm_egm", "agm_egm",
     r"\bagm\b|\begm\b|annual general meeting|extraordinary general meeting|shareholders'? meeting|general meeting"
     r"|book closure|voting results|e-voting", 12, "AGM / EGM notice or result"),

    # ---- investor-facing, lowest-information buckets ----------------------------------------------------------
    ("investor_meet", "investor_meetings",
     r"investor meet|analyst meet|analyst\(s\)|investor\(s\)|institutional investor|one[- ]on[- ]one|group meeting|investor conference|conference",
     15, "Investor meeting schedule"),
    ("investor_presentation", "investor_meetings", r"^investor presentation|analyst presentation", 25, "Investor presentation"),
    ("board_outcome_generic", "results", r"outcome of (the )?board meeting", 60,
     "Board outcome, details only in PDF (usually results/dividend)"),
]

# (pattern, delta, why, only-for-categories or None)
NUDGES = [
    (r"downgrad", 45, "downgrade", None),
    (r"\bupgrad(ed|e)\b", 25, "upgrade", {"credit_rating"}),
    (r"negative (outlook|watch)|outlook.{0,20}negative|credit watch", 20, "negative outlook", {"credit_rating"}),
    (r"withdraw", 15, "withdrawn", {"credit_rating"}),
    (r"warning letter", 18, "warning letter", None),
    (r"payment default|defaulted|loan default", 25, "default", None),
    (r"fraud|forensic|siphon|misappropriat|going concern|disclaimer of opinion|adverse (opinion|remark)|qualified (opinion|conclusion)",
     25, "governance red flag", None),
    (r"search and seizure|\braid\b|enforcement directorate|\bcbi\b", 20, "agency action", None),
    (r"imposition of penalty|penalty of|fine of", 10, "penalty imposed", None),
    (r"auditor.{0,80}resign|resign.{0,80}auditor", 45, "auditor resignation", None),
    (r"with immediate effect|\babrupt", 8, "abrupt exit", {"management_change"}),
    (r"special dividend", 10, "special dividend", {"dividend"}),
]

_RULES = [(i, c, re.compile(p, _F), b, w) for i, c, p, b, w in RULES]
_NUDGES = [(re.compile(p, _F), d, w, cats) for p, d, w, cats in NUDGES]


def classify(desc: str, text: str):
    """Return (category, priority, why, rule_id) or None if no rule matches."""
    s = f"{desc or ''} | {text or ''}"
    for rid, cat, rx, base, why in _RULES:
        if rx.search(s):
            score, notes = base, []
            for nrx, delta, nwhy, cats in _NUDGES:
                if (cats is None or cat in cats) and nrx.search(s):
                    score += delta
                    notes.append(f"+{delta} {nwhy}")
            return cat, max(0, min(100, score)), why + (f" ({', '.join(notes)})" if notes else ""), rid
    return None
