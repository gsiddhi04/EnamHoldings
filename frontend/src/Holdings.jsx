import { api } from "./api.js";
import { Spark, PriceChart } from "./charts.jsx";
import { CAT, dir, inr, pct, plural, when, shortDate } from "./format.js";
import { useAsync } from "./hooks.js";

export default function Holdings({ symbol, go, onOpen }) {
  return symbol ? <StockPage symbol={symbol} go={go} onOpen={onOpen} /> : <List go={go} />;
}

function List({ go }) {
  const { data, error, loading, reload } = useAsync(api.holdings, []);
  const rows = data?.holdings || [];
  const stamp = rows.find((r) => r.date)?.date;
  const live = rows.some((r) => r.intraday);
  return (
    <>
      <h1 className="page-title">Holdings</h1>
      <p className="standfirst" style={{ marginBottom: 0 }}>
        {rows.length ? plural(rows.length, "company", "companies") : "Your portfolio"}, last 30 sessions.
        {stamp && <> Prices as of {shortDate(stamp).replace(/ \d{4}$/, "")}{live ? ", session still open" : ""}.</>}
      </p>
      {error && <div className="err" style={{ marginTop: 14 }}>{error}<button onClick={reload}>Try again</button></div>}
      {loading && !data && <div style={{ marginTop: 14 }}>{[...Array(7)].map((_, i) => <div key={i} className="skel" style={{ height: 44 }} />)}</div>}
      <ul className="hold">
        {rows.map((h) => (
          <li key={h.symbol}>
            <button onClick={() => go("holdings", h.symbol)}>
              <span><span className="s">{h.symbol}{h.important_filings_7d > 0 && <i className="flag" title="Important filing this week" />}</span><span className="n" style={{ display: "block" }}>{h.name}</span></span>
              <Spark data={h.spark} />
              <span className="px num"><b>{h.close == null ? "—" : "₹" + inr(h.close, h.close < 100 ? 2 : 1)}</b><span className={dir(h.change_pct)}>{pct(h.change_pct, 2)}</span></span>
            </button>
          </li>
        ))}
      </ul>
      {rows.some((h) => h.important_filings_7d > 0) && <p className="foot" style={{ marginTop: 10 }}><i className="flag" style={{ marginLeft: 0, marginRight: 6 }} />An important filing this week</p>}
    </>
  );
}

function StockPage({ symbol, go, onOpen }) {
  const { data, error, loading, reload } = useAsync(() => api.stock(symbol), [symbol]);
  const s = data?.snapshot;
  const px = data?.prices || [];
  const now = px.length ? px[px.length - 1].date + "T23:59:00" : undefined;
  return (
    <>
      <button className="back" onClick={() => go("holdings")}>‹ Holdings</button>
      {error && <div className="err">{error}<button onClick={reload}>Try again</button></div>}
      {loading && !data && <><div className="skel" style={{ height: 36, width: "60%" }} /><div className="skel" style={{ height: 150 }} /></>}
      {data && (
        <>
          <h1 className="page-title">{data.name}</h1>
          <div className="foot" style={{ marginTop: 0 }}>NSE:{data.symbol}{data.sector ? " · " + data.sector : ""}</div>
          {s && (
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, margin: "14px 0 8px" }}>
              <span className="bigprice num">₹{inr(s.close, 1)}</span>
              <span className={`num ${dir(s.change_pct)}`} style={{ fontWeight: 600, fontSize: 18 }}>{pct(s.change_pct, 2)}</span>
            </div>
          )}
          <PriceChart data={px.map((p) => p.close)} dates={px.map((p) => shortDate(p.date).replace(/ \d{4}$/, ""))} />
          {s && (
            <div className="stats num">
              <div><div className="k">Volume</div><div className="v">{s.volume ? (s.volume / 1e5).toFixed(1) + "L" : "—"}</div></div>
              <div><div className="k">20-day avg</div><div className="v">{s.avg_volume ? (s.avg_volume / 1e5).toFixed(1) + "L" : "—"}</div></div>
              <div><div className="k">Vs average</div><div className="v">{s.volume_multiple ? s.volume_multiple.toFixed(1) + "×" : "—"}</div></div>
            </div>
          )}
          <button className="btn" style={{ width: "100%" }} onClick={() => go("research", symbol)}>Research {symbol}: promises, numbers, bull &amp; bear</button>

          <div className="sec"><h2>Recent filings</h2></div>
          {data.announcements.length === 0 && <div className="empty">No filings in the last week.</div>}
          <ul className="glance">
            {data.announcements.map((a) => (
              <li key={a.id}>
                <button onClick={() => onOpen({ id: a.id, symbol, name: data.name, facts: undefined })}>
                  <div className="t">{a.summary || a.nse_desc}</div>
                  <div className="m">{CAT[a.category] || a.category} · {when(a.ann_dt, now)}{a.priority >= 60 ? " · important" : ""}</div>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
