import { useEffect, useState } from "react";
import { api } from "./api.js";
import AskFinn from "./AskFinn.jsx";
import { People, RatingLine, ResultsTable, headlineFor, kindOf } from "./cards.jsx";
import { CAT, stamp } from "./format.js";

const SUGGEST = {
  results: ["What drove the change in profit?", "How do margins compare with last year?", "Is anything unusual in these numbers?"],
  mgmt: ["Who is the new person and where did they work before?", "Why is this change happening?", "When does it take effect?"],
  rating: ["What does this rating change mean for the company's borrowing?", "Which facilities does it cover?", "What did the agency say drove it?"],
  generic: ["What does this mean for shareholders?", "What are the key amounts or terms?", "What's missing from this filing?"],
};

/** Bottom sheet: the full filing story, a link to the PDF, and grounded Q&A. */
export default function Sheet({ item, now, onClose }) {
  const [full, setFull] = useState(item.facts === undefined ? null : item);

  useEffect(() => {
    if (full) return undefined;
    let live = true;
    api.announcement(item.id).then((r) => live && setFull(r), () => live && setFull({ ...item, failed: true }));
    return () => { live = false; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const key = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", key);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", key); document.body.style.overflow = prev; };
  }, [onClose]);

  const it = full;
  const k = it ? kindOf(it) : "generic";
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="sheet" role="dialog" aria-modal="true" aria-label="Filing details">
        <div className="grab" />
        <div className="head"><button className="x" onClick={onClose} aria-label="Close">×</button></div>
        <div className="body">
          {!it ? <><div className="skel" style={{ width: "40%" }} /><div className="skel" style={{ height: 30 }} /><div className="skel" /><div className="skel" style={{ width: "70%" }} /></> : (
            <>
              <div className="kicker"><span><b>{it.name}</b> · {CAT[it.category] || it.category}</span><span className="when">{stamp(it.ann_dt)}</span></div>
              <h3>{headlineFor(it)}</h3>

              {k === "results" && <ResultsTable facts={it.facts} />}
              {k === "results" && (
                <p className="note">
                  Read from the filing's {it.facts.basis} profit-and-loss page and cross-checked: profit before tax less tax equals PAT in all
                  three periods. EBITDA is PBT + finance costs + depreciation − other income, worked out by us, not printed in the filing.
                </p>
              )}
              {k === "mgmt" && <People people={it.facts.people} bios />}
              {k === "rating" && <><RatingLine f={it.facts} full />{it.summary && <p className="deck" style={{ marginTop: 8 }}>{it.summary}</p>}</>}
              {k === "generic" && (
                <>
                  {it.summary && <p className="deck" style={{ fontSize: 17 }}>{it.summary}</p>}
                  <div className="block"><h4>As filed with the exchange</h4>
                    <p className="deck">{it.subject}{it.text && it.text !== it.subject ? ": " + it.text : ""}</p></div>
                </>
              )}
              {it.facts?.type === "results" && it.facts.status !== "ok" && (
                <p className="note">We couldn't read this statement's table reliably, so no figures are shown. The PDF below is the source.</p>
              )}

              <div className="block">
                <p className="foot" style={{ marginBottom: 12 }}>Ranked {it.priority} of 100: {it.why}.</p>
                {it.attachment && <a className="btn" href={it.attachment} target="_blank" rel="noreferrer">Open the filing (PDF) ↗</a>}
              </div>

              <div className="block">
                <h4>Ask FINN</h4>
                <p className="foot" style={{ margin: "0 0 8px" }}>Answers come only from this filing and the company's figures.</p>
                <AskFinn symbol={it.symbol} annId={it.id} suggestions={SUGGEST[k]} placeholder="Ask about this filing…" />
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
