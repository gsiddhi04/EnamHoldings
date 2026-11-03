import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import AskFinn from "./AskFinn.jsx";
import { Bars, Line, PairBars } from "./charts.jsx";
import { dir, inr, pct, plural, shortDate } from "./format.js";
import { useAsync, useTicker } from "./hooks.js";

const PORTFOLIO_PICKS = ["TCS", "RELIANCE", "HDFCBANK", "ITC", "TRENT", "SUZLON"];
const ADHOC_PICKS = ["BAJFINANCE", "PIDILITIND", "DMART", "HINDUNILVR"];
const VERDICT_LABEL = { delivered: "Delivered", partly: "Partly", missed: "Missed", "too early": "Too early", unverifiable: "Can't test" };
const slug = (v) => v.replace(" ", "-");

export default function Research({ symbol, go }) {
  return symbol ? <Report symbol={symbol} go={go} key={symbol} /> : <Search go={go} />;
}

function Search({ go }) {
  const [q, setQ] = useState("");
  const submit = (e) => { e.preventDefault(); const s = q.trim().toUpperCase().replace(/^NSE:/, ""); if (s) go("research", s); };
  return (
    <>
      <h1 className="page-title">Research</h1>
      <p className="standfirst" style={{ marginBottom: 0 }}>
        Any NSE company. Built only from its reported numbers and what management said on earnings calls.
      </p>
      <form className="search" onSubmit={submit}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="NSE symbol, e.g. TITAN" autoCapitalize="characters"
               autoCorrect="off" spellCheck={false} enterKeyHint="search" aria-label="NSE symbol" />
        <button type="submit">Research</button>
      </form>
      <div className="picks-h">From your holdings</div>
      <div className="picks">{PORTFOLIO_PICKS.map((s) => <button key={s} onClick={() => go("research", s)}>{s}</button>)}</div>
      <div className="picks-h">Worth a look, outside the portfolio</div>
      <div className="picks">{ADHOC_PICKS.map((s) => <button key={s} onClick={() => go("research", s)}>{s}</button>)}</div>
    </>
  );
}

const TABS = [["promises", "Promised vs delivered"], ["business", "Business"], ["numbers", "Numbers"], ["cash", "Cash"], ["case", "Bull & bear"], ["ask", "Ask FINN"]];

function Report({ symbol, go }) {
  const facts = useAsync(() => api.research(symbol), [symbol]);
  const ok = !!facts.data;
  const promises = useAsync(() => (ok ? api.promises(symbol) : Promise.resolve(null)), [symbol, ok]);
  const bb = useAsync(() => (ok ? api.bullbear(symbol) : Promise.resolve(null)), [symbol, ok]);
  const biz = useAsync(() => (ok ? api.business(symbol) : Promise.resolve(null)), [symbol, ok]);
  const [active, setActive] = useState("promises");
  const refs = useRef({});

  useEffect(() => {
    if (!ok) return undefined;
    const io = new IntersectionObserver(
      (es) => { const v = es.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]; if (v) setActive(v.target.dataset.id); },
      { rootMargin: "-60px 0px -65% 0px" });
    Object.values(refs.current).forEach((el) => el && io.observe(el));
    return () => io.disconnect();
  }, [ok]);

  const jump = (id) => { setActive(id); refs.current[id]?.scrollIntoView({ behavior: "smooth", block: "start" }); };
  const f = facts.data;
  const sec = (id, title, body) => (
    <section className="rsec" data-id={id} ref={(el) => (refs.current[id] = el)}>
      <div className="sec"><h2>{title}</h2></div>
      {body}
    </section>
  );

  return (
    <>
      <button className="back" onClick={() => go("research")}>‹ Research</button>
      {facts.error && (
        <div className="err">{facts.error}<button onClick={facts.reload}>Try again</button></div>
      )}
      {facts.loading && !f && (
        <>
          <h1 className="page-title">{symbol}</h1>
          <div className="reading"><span className="pulse" />Fetching {symbol}'s reported numbers…</div>
          <div className="skel" style={{ height: 90 }} />
        </>
      )}
      {f && (
        <>
          <h1 className="page-title">{f.name}</h1>
          <div className="foot" style={{ marginTop: 0 }}>NSE:{f.symbol} · {f.basis} figures, ₹ crore · latest quarter {f.snapshot.quarter}</div>
          <nav className="rtabs" aria-label="Sections">
            {TABS.map(([id, label]) => <button key={id} className={active === id ? "on" : ""} onClick={() => jump(id)}>{label}</button>)}
          </nav>

          {sec("promises", "Promised vs delivered", <Promises state={promises} concalls={f.concall_count} />)}
          {sec("business", "The business", <Business state={biz} />)}
          {sec("numbers", "The numbers", <Numbers f={f} />)}
          {sec("cash", "Does profit turn into cash?", <Cash f={f} />)}
          {sec("case", "Bull & bear", <Case state={bb} />)}
          {sec("ask", "Ask FINN", (
            <>
              <p className="foot" style={{ margin: "0 0 8px" }}>Answers come only from {f.name}'s figures and filings, never from outside knowledge.</p>
              <AskFinn symbol={symbol} placeholder={`Ask about ${f.name}…`}
                       suggestions={["What changed in the latest quarter?", "Is debt a concern?", "How good is cash conversion?"]} />
            </>
          ))}
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------------ promises
function Promises({ state, concalls }) {
  const n = Math.min(5, concalls || 5);
  const text = useTicker([`Reading ${plural(n, "earnings-call transcript")}…`, "Pulling out what management promised…",
    "Checking each promise against the reported numbers…", "Nearly there. The last step is the slowest."], state.loading, 7000);
  const [secs, setSecs] = useState(0);
  const [showUntested, setShowUntested] = useState(false);
  useEffect(() => {
    if (!state.loading) return undefined;
    setSecs(0);
    const t = setInterval(() => setSecs((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, [state.loading]);

  if (state.error) return <div className="err">{state.error}<button onClick={state.reload}>Try again</button></div>;
  if (state.loading || !state.data) {
    return <div className="reading"><span className="pulse" /><span>{text} <span className="muted num" style={{ fontStyle: "normal", fontFamily: "var(--sans)", fontSize: 13 }}>{secs}s</span></span></div>;
  }
  const d = state.data;
  const tested = d.promises.filter((p) => p.verdict !== "unverifiable");
  const untested = d.promises.filter((p) => p.verdict === "unverifiable");
  const counts = {};
  d.promises.forEach((p) => (counts[p.verdict] = (counts[p.verdict] || 0) + 1));
  return (
    <>
      {d.credibility ? (
        <div className="verdict-hero">
          <div className={`word ${d.credibility}`}>{d.credibility[0].toUpperCase() + d.credibility.slice(1)}</div>
          <div className="score"><b className="num">{d.score}</b> of 100 · {plural(d.scored, "promise")} tested</div>
        </div>
      ) : <div className="verdict-hero"><div className="word muted" style={{ fontSize: 28 }}>Nothing to test</div></div>}
      {d.summary && <p className="deck" style={{ fontSize: 17, marginTop: 10 }}>{d.summary}</p>}
      {d.promises.length > 0 && (
        <div className="pillrow">
          {Object.keys(VERDICT_LABEL).filter((v) => counts[v]).map((v) => <span key={v} className={`pill ${slug(v)}`}>{VERDICT_LABEL[v]} <span className="num">{counts[v]}</span></span>)}
        </div>
      )}
      <div style={{ marginTop: 6 }}>
        {tested.map((p, i) => <PromiseRow key={i} p={p} />)}
        {untested.length > 0 && (
          <>
            <button className="linkbtn" onClick={() => setShowUntested(!showUntested)} style={{ margin: "6px 0" }}>
              {showUntested ? "Hide" : "Show"} {plural(untested.length, "promise")} that can't be tested against numbers
            </button>
            {showUntested && untested.map((p, i) => <PromiseRow key={i} p={p} />)}
          </>
        )}
      </div>
      {d.calls.length > 0 && (
        <p className="foot">Read from the {d.calls.map((c) => c.month).join(", ")} earnings calls. Score = delivered 1, partly ½, missed 0, among testable promises.</p>
      )}
    </>
  );
}

function PromiseRow({ p }) {
  return (
    <div className="promise">
      <div className="top">
        <div className="what">{p.metric}: {p.target}<small>{p.call} call · horizon: {p.horizon}</small></div>
        <span className={`pill ${slug(p.verdict)}`}>{VERDICT_LABEL[p.verdict]}</span>
      </div>
      <blockquote>“{p.quote}”</blockquote>
      <div className="ev"><b>Against the numbers:</b> {p.evidence}</div>
    </div>
  );
}

// ------------------------------------------------------------------ numbers
function Numbers({ f }) {
  const s = f.snapshot, t = f.trajectory, b = f.balance_sheet;
  const rows = [["Revenue", s.revenue], [f.lender ? "Op. profit" : "EBITDA", s.operating_profit], ["PBT", s.pbt], ["PAT", s.pat]];
  const kv = (k, v, sub) => <div><div className="k">{k}</div><div className="v num">{v}{sub && <small> {sub}</small>}</div></div>;
  const de = b.debt_to_equity?.slice(-1)[0];
  const wc = b.working_capital?.wc_days;
  return (
    <>
      <table className="fin">
        <thead><tr><th>{s.quarter}</th><th>₹ crore</th><th>QoQ</th><th>YoY</th></tr></thead>
        <tbody>
          {rows.map(([label, r]) => r && (
            <tr key={label}><td>{label}</td><td className="v num">{inr(r.value)}</td>
              <td className={`d num ${dir(r.qoq_pct)}`}>{pct(r.qoq_pct)}</td><td className={`d num ${dir(r.yoy_pct)}`}>{pct(r.yoy_pct)}</td></tr>
          ))}
        </tbody>
      </table>
      <div className="foot num">
        {s.op_margin_pct && <>Operating margin {s.op_margin_pct.value}%{s.op_margin_pct.yoy_change_pp != null && <> ({pct(s.op_margin_pct.yoy_change_pp, 1)} pts YoY)</>} · </>}
        {s.gross_npa_pct != null && <>Gross NPA {s.gross_npa_pct}% · </>}EPS ₹{s.eps?.value}{s.ttm_pe ? ` · P/E ${s.ttm_pe}` : ""}
      </div>

      <div className="sec" style={{ marginTop: 22 }}><h2>What the numbers say</h2></div>
      {f.observations.length === 0 ? <p className="foot">Nothing stands out against the thresholds we check.</p> : (
        <ul className="obs">{f.observations.map((o, i) => <li key={i} className={o.tone}><i />{o.text}</li>)}</ul>
      )}

      <div className="kv num">
        {kv("Revenue growth, 3y", pct(t.revenue_cagr_pct["3y"], 1, false), "a year")}
        {kv("Revenue growth, 5y", pct(t.revenue_cagr_pct["5y"], 1, false), "a year")}
        {kv("Profit growth, 3y", pct(t.profit_cagr_pct["3y"], 1, false), "a year")}
        {kv("Profit growth, 5y", pct(t.profit_cagr_pct["5y"], 1, false), "a year")}
      </div>

      <div className="charts">
        <div className="chart"><h5>Revenue, ₹ crore</h5><Bars data={f.charts.annual_revenue} /></div>
        <div className="chart"><h5>Net profit, ₹ crore</h5><Bars data={f.charts.annual_pat} /></div>
        {f.charts.annual_op_margin && <div className="chart"><h5>Operating margin</h5><Line data={f.charts.annual_op_margin} /></div>}
      </div>

      <div className="sec"><h2>Balance sheet</h2></div>
      {b.lender ? <p className="note">{b.note}</p> : (
        <div className="kv num">
          {de && kv("Debt ÷ equity", de.value?.toFixed(2) + "×", de.period)}
          {b.net_worth_cr != null && kv("Net worth", "₹" + inr(b.net_worth_cr), "cr")}
          {wc && kv("Working-capital days", wc.latest, `vs ${wc.three_years_ago ?? "—"} three yrs ago`)}
          {b.roce_pct && kv("Return on capital", b.roce_pct.latest + "%", b.roce_pct.period)}
        </div>
      )}
      {b.lender && b.roe_pct && <div className="kv num">{kv("Return on equity", b.roe_pct.latest + "%", b.roe_pct.period)}</div>}
    </>
  );
}

// ------------------------------------------------------------------ cash
function Cash({ f }) {
  const c = f.cash_quality;
  if (c.lender) return <p className="note">{c.note}</p>;
  if (!c.years?.length) return <p className="foot">No cash-flow statement found.</p>;
  const latest = c.years[c.years.length - 1];
  return (
    <>
      <div className="legend"><span><i style={{ background: "#1E2B4F" }} />Cash from operations</span><span><i style={{ background: "rgba(167,126,70,.85)" }} />Net profit</span></div>
      <div className="chart"><PairBars rows={c.years.map((y) => ({ period: y.period, a: y.cfo_cr, b: y.pat_cr, ratio: y.cfo_to_pat }))} /></div>
      <div className="kv num">
        <div><div className="k">Cash ÷ profit, {latest.period}</div><div className="v">{c.latest_cfo_to_pat?.toFixed(2)}×</div></div>
        <div><div className="k">Cash ÷ profit, 3 years</div><div className="v">{c.cfo_to_pat_3y?.toFixed(2) ?? "—"}×</div></div>
        <div><div className="k">Free cash flow</div><div className="v">₹{inr(latest.fcf_cr)}<small> cr</small></div></div>
        <div><div className="k">Operating cash flow</div><div className="v">₹{inr(latest.cfo_cr)}<small> cr</small></div></div>
      </div>
      <p className="foot">A ratio near or above 1× means reported profit is arriving as cash.</p>
    </>
  );
}

// ------------------------------------------------------------------ bull & bear
function Case({ state }) {
  const text = useTicker(["Weighing the case for and against…", "Tying every point to a number…"], state.loading, 6000);
  if (state.error) return <div className="err">{state.error}<button onClick={state.reload}>Try again</button></div>;
  if (state.loading || !state.data) return <div className="reading"><span className="pulse" />{text}</div>;
  const d = state.data;
  const side = (key, title, cls) => (
    <div className={`case ${cls}`}>
      <h4>{title}</h4>
      {d[key].map((p, i) => (
        <div className="pt" key={i}>
          <div className="hd">{p.headline}</div>
          <div className="why">{p.why}</div>
          <div className="ev num"><span>{p.evidence.label}</span><b>{p.evidence.value.toLocaleString("en-IN")}{p.evidence.unit === "%" ? "%" : " " + p.evidence.unit}</b></div>
        </div>
      ))}
    </div>
  );
  return <>{side("bull", "The case for", "bull")}{side("bear", "The case against", "bear")}
    {!d.complete && <p className="foot">The data supported fewer than three points on one side, so we show fewer rather than stretch.</p>}</>;
}

// ------------------------------------------------------------------ business
const MIX = ["#1E2B4F", "#4A5B8C", "#8A97BD", "#B58A55", "#D3B88C", "#9C9288", "#6E6259", "#C9C2BC"];

function Business({ state }) {
  const text = useTicker(["Opening the latest annual report…", "Finding the business description…", "Finding the segment note…"], state.loading, 6000);
  if (state.error) return <div className="err">{state.error}<button onClick={state.reload}>Try again</button></div>;
  if (state.loading || !state.data) return <div className="reading"><span className="pulse" />{text}</div>;
  const b = state.data;
  if (!b.available) return <p className="note">{b.reason}</p>;
  const segs = b.segments || [];
  return (
    <>
      <p className="deck" style={{ fontSize: 18, color: "var(--ink)", marginTop: 0 }}>{b.what_it_does}</p>
      {b.how_it_makes_money && <p className="deck">{b.how_it_makes_money}</p>}
      {b.mix_ok && (
        <>
          <div className="mixbar" role="img" aria-label="Revenue mix by segment">
            {segs.filter((s) => s.share_pct).map((s, i) => <i key={s.name} style={{ width: s.share_pct + "%", background: MIX[i % MIX.length] }} />)}
          </div>
          <div className="foot" style={{ marginTop: 6 }}>Share of segment revenue{b.segment_basis ? `, ${b.segment_basis}` : ""}, latest financial year</div>
        </>
      )}
      {segs.length > 0 && (
        <ul className="segs">
          {segs.map((s, i) => (
            <li key={s.name}>
              {b.mix_ok && s.share_pct != null && <i style={{ background: MIX[i % MIX.length] }} />}
              <div><div className="sn">{s.name}</div>{s.description && <div className="sd">{s.description}</div>}</div>
              {b.mix_ok && s.share_pct != null && <span className="sp num">{s.share_pct.toFixed(1)}%</span>}
            </li>
          ))}
        </ul>
      )}
      {!b.mix_ok && segs.length > 0 && <p className="foot">The report's segment figures didn't reconcile with reported revenue, so no mix is shown.</p>}
      {b.mix_note && <p className="note">{b.mix_note}</p>}
      <p className="foot">From the <a href={b.source.url} target="_blank" rel="noreferrer">{b.source.report} ↗</a> (pages {b.source.pages.join(", ")}). Segment shares are computed from the printed segment revenue.</p>
    </>
  );
}
