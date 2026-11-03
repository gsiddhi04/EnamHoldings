import { CAT, dir, inr, pct, shortDate, when } from "./format.js";

const HONORIFIC = /^(mr|ms|mrs|dr|shri|smt|prof)\.?\s+/i;
const bare = (n) => (n || "").replace(HONORIFIC, "").trim();
const CHANGE = {
  appointment: ["Joins", "in", "joins as"], "re-appointment": ["Re-appointed", "in", "is re-appointed as"],
  resignation: ["Resigns", "out", "resigns as"], cessation: ["Steps down", "out", "steps down as"],
  retirement: ["Retires", "out", "retires as"], change_in_designation: ["New role", "in", "moves to"],
};
const SENIOR = /chair|managing|ceo|chief|cfo|whole[- ]time|president/i;

export function kindOf(it) {
  const f = it.facts;
  if (f?.type === "results" && f.status === "ok") return "results";
  if (f?.type === "management_change" && f.people?.length) return "mgmt";
  return "generic";
}

const mag = (n) => Math.round(Math.abs(n));

/** A newspaper headline written from the extracted numbers, not a template over the filing title. */
export function headlineFor(it) {
  const f = it.facts, nm = it.name;
  const k = kindOf(it);
  if (k === "results") {
    const rev = f.metrics.revenue.yoy_pct, pat = f.metrics.pat.yoy_pct;
    if (pat == null) return `${nm} reports quarterly results`;
    const pUp = pat >= 1, pDn = pat <= -1;
    const pv = pUp ? "rises" : pDn ? "falls" : "is flat";
    const head = `${nm} profit ${pv}${pUp || pDn ? " " + mag(pat) + "%" : ""}`;
    if (rev == null) return head;
    const rUp = rev >= 1, rDn = rev <= -1;
    if (pUp && rUp || pDn && rDn) return `${head} on ${mag(rev)}% ${rUp ? "higher" : "lower"} revenue`;
    if (pDn && rUp) return `${head} even as revenue climbs ${mag(rev)}%`;
    if (pUp && rDn) return `${head} despite ${mag(rev)}% lower revenue`;
    return rUp ? `${head}; revenue up ${mag(rev)}%` : rDn ? `${head}; revenue down ${mag(rev)}%` : head;
  }
  if (k === "mgmt") {
    const p = f.people.find((x) => SENIOR.test(x.role || "")) || f.people[0];
    const [, , verb] = CHANGE[p.change_type] || ["", "", "—"];
    return `${nm}: ${bare(p.name)} ${verb} ${p.role || ""}`.trim();
  }
  if (f?.type === "results") return `${nm} files quarterly results`;
  return it.summary || it.subject || it.why;
}

export function ResultsTable({ facts, compact }) {
  const bank = facts.is_bank_or_nbfc;
  const rows = [["Revenue", "revenue"], [bank ? "Op. profit" : "EBITDA", "ebitda"], ["PBT", "pbt"], ["PAT", "pat"]];
  const m = facts.metrics;
  return (
    <>
      <table className="fin">
        <thead><tr><th /><th>₹ crore</th><th>QoQ</th><th>YoY</th></tr></thead>
        <tbody>
          {rows.map(([label, k]) => (
            <tr key={k}>
              <td>{label}</td>
              <td className="v num">{inr(m[k].values[0])}</td>
              <td className={`d num ${dir(m[k].qoq_pct)}`}>{pct(m[k].qoq_pct, 1)}</td>
              <td className={`d num ${dir(m[k].yoy_pct)}`}>{pct(m[k].yoy_pct, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="foot num">
        {bank ? "Op. profit before provisions" : "EBITDA margin"} {m.ebitda.margin_pct?.[0] ?? "—"}% · PAT margin {m.pat.margin_pct?.[0] ?? "—"}%
        {!compact && facts.basis && <> · {facts.basis}</>}
      </div>
    </>
  );
}

export function People({ people, bios, limit }) {
  const list = limit ? people.slice(0, limit) : people;
  return (
    <ul className="people">
      {list.map((p, i) => {
        const [label, side] = CHANGE[p.change_type] || [p.change_type || "Change", "in"];
        return (
          <li key={i}>
            <span className="nm">{bare(p.name)}</span>
            <span className={`chg ${side}`}>{label}</span>
            <span className="role">{p.role}</span>
            {p.effective_date && <span className="when2">{side === "out" ? "Effective" : "From"} {shortDate(p.effective_date)}</span>}
            {bios && p.background && <span className="bio">{p.background}</span>}
            {bios && p.reason && <span className="when2">Reason given: {p.reason}</span>}
          </li>
        );
      })}
    </ul>
  );
}

export function Card({ item, now, onOpen }) {
  const k = kindOf(item), f = item.facts;
  const hl = headlineFor(item);
  const kick = k === "results" ? "Results" : k === "mgmt" ? "Leadership" : item.why || CAT[item.category];
  const deck = k === "generic" && !item.summary && item.text && item.text !== hl ? item.text.slice(0, 150) : null;
  return (
    <button className="card" onClick={() => onOpen(item)}>
      <div className="kicker"><span><b>{item.name}</b> · {kick}</span><span className="when">{when(item.ann_dt, now)}</span></div>
      <h3>{hl}</h3>
      {k === "results" && <ResultsTable facts={f} compact />}
      {k === "mgmt" && <>
        <People people={f.people} limit={3} />
        {f.people.length > 3 && <div className="related">+{f.people.length - 3} more changes in this filing</div>}
      </>}
      {f?.type === "results" && f.status !== "ok" && <p className="deck">Figures couldn't be read reliably from the PDF; open the filing to check.</p>}
      {deck && <p className="deck">{deck}</p>}
      {item.related > 0 && <div className="related">+{item.related} related {item.related === 1 ? "filing" : "filings"} folded in</div>}
    </button>
  );
}
