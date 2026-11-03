import { useState } from "react";
import { api } from "./api.js";
import { Card } from "./cards.jsx";
import { CAT, dateline, dir, inr, pct, plural, shortDate, when, word } from "./format.js";
import { useAsync } from "./hooks.js";

const WINDOWS = [[24, "24h"], [72, "3d"], [168, "7d"]];
const SPAN = { 24: "today", 72: "in the last three days", 168: "this week" };

function Skeleton() {
  return <div style={{ marginTop: 18 }}>
    <div className="skel" style={{ height: 34, width: "80%" }} /><div className="skel" style={{ width: "60%" }} />
    <div className="skel" style={{ height: 150, marginTop: 24 }} /><div className="skel" style={{ height: 150 }} />
  </div>;
}

export default function Brief({ onOpen, goStock }) {
  const [hours, setHours] = useState(() => +localStorage.getItem("finn.hours") || 24);
  const [folded, setFolded] = useState(false);
  const { data, error, loading, reload } = useAsync(() => api.digest(hours), [hours]);
  const pick = (h) => { setHours(h); localStorage.setItem("finn.hours", h); setFolded(false); };

  const now = data?.window.to;
  const n = data?.counts.top ?? 0;
  const headline = !data ? "Good morning." : n === 0 ? "Nothing urgent " + SPAN[hours] + "." : `${word(n)} ${n === 1 ? "thing matters" : "things matter"} ${SPAN[hours]}.`;
  const baseline = data?.movers[0]?.since;

  return (
    <>
      <header className="mast">
        <div className="logo">FINN</div>
        <div className="dateline"><span>{now ? dateline(now) : " "}</span><span>Your holdings</span></div>
      </header>

      <h1 className="headline">{headline}</h1>
      {data && (
        <p className="standfirst num">
          {plural(data.counts.total, "filing")} read across your holdings: {data.counts.top} above the fold,
          {" "}{data.counts.look} worth a glance, {data.counts.routine} routine.
        </p>
      )}
      <div className="seg" role="group" aria-label="Time window">
        {WINDOWS.map(([h, l]) => <button key={h} className={hours === h ? "on" : ""} onClick={() => pick(h)}>{l}</button>)}
      </div>

      {error && !data && <div className="err" style={{ marginTop: 18 }}>{error}<button onClick={reload}>Try again</button></div>}
      {loading && !data && <Skeleton />}

      {data && (
        <div style={{ opacity: loading ? 0.55 : 1, transition: "opacity .15s" }}>
          {data.movers.length > 0 && (
            <>
              <div className="sec"><h2>Biggest movers</h2><span className="aside">{baseline ? "since " + shortDate(baseline).replace(/ \d{4}$/, "") : ""}</span></div>
              <div className="movers">
                {data.movers.map((m) => (
                  <button key={m.symbol} className={`mover ${dir(m.change_pct)}`} onClick={() => goStock(m.symbol)}>
                    <div className="sym">{m.symbol}</div>
                    <div className={`chg num ${dir(m.change_pct)}`}>{pct(m.change_pct, 1)}</div>
                    <div className="px num">₹{inr(m.close)}{m.intraday ? " · live" : ""}</div>
                  </button>
                ))}
              </div>
            </>
          )}

          {data.top.length > 0 && (
            <>
              <div className="sec"><h2>Above the fold</h2></div>
              {data.top.map((it) => <Card key={it.id} item={it} now={now} onOpen={onOpen} />)}
            </>
          )}

          {data.look.length > 0 && (
            <>
              <div className="sec"><h2>Worth a glance</h2></div>
              <ul className="glance">
                {data.look.map((it) => (
                  <li key={it.id}>
                    <button onClick={() => onOpen(it)}>
                      <div className="t"><b>{it.name}</b>{it.summary || it.subject}</div>
                      <div className="m">{CAT[it.category] || it.category} · {when(it.ann_dt, now)}{it.related ? ` · +${it.related} related` : ""}</div>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}

          {data.counts.total === 0 && (
            <div className="empty">No filings from your holdings in this window.<br />Try a longer one.</div>
          )}

          {data.counts.routine > 0 && (
            <>
              <div className="fold" aria-hidden><span>the fold</span></div>
              <button className="btn-fold" onClick={() => setFolded(!folded)} aria-expanded={folded}>
                {folded ? "Fold the routine filings back" : `${plural(data.counts.routine, "routine filing")}, folded`}
                <span aria-hidden>{folded ? "▴" : "▾"}</span>
              </button>
              {folded && (
                <div className="routine">
                  {data.routine.map((g) => (
                    <div className="co" key={g.symbol}>
                      <b>{g.name}<i>{g.count}</i></b>
                      {g.items.map((r) => (
                        <button key={r.id} onClick={() => onOpen({ ...r, symbol: g.symbol, name: g.name, facts: undefined })}>
                          {r.summary || r.subject} <span className="muted">· {when(r.ann_dt, now)}</span>
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {data.quiet.length > 0 && (
            <div className="quiet foot">
              <span>Nothing filed in this window by:</span>
              {data.quiet.map((q) => <button key={q.symbol} onClick={() => goStock(q.symbol)}>{q.symbol}</button>)}
            </div>
          )}
        </div>
      )}
    </>
  );
}
