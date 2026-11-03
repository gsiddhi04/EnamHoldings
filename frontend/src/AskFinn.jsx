import { useState } from "react";
import { api } from "./api.js";
import { useTicker } from "./hooks.js";

const SRC = { filing: "this filing", company_data: "screener.in figures" };

/** Grounded Q&A. Suggested questions first; answers show what was missing rather than guessing. */
export default function AskFinn({ symbol, annId, suggestions = [], placeholder = "Ask about this…" }) {
  const [thread, setThread] = useState([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const reading = useTicker(
    annId ? ["Reading the filing…", "Still reading, long filing…"] : ["Checking the numbers…", "Still working…"], busy, 9000);

  async function send(text) {
    text = text.trim();
    if (!text || busy) return;
    setBusy(true);
    setQ("");
    setThread((t) => [...t, { q: text }]);
    try {
      const r = await api.ask({ question: text, symbol: symbol || undefined, ann_id: annId ? String(annId) : undefined });
      setThread((t) => [...t.slice(0, -1), { q: text, ...r }]);
    } catch (e) {
      setThread((t) => [...t.slice(0, -1), { q: text, error: e.message }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ask">
      {thread.length === 0 && suggestions.length > 0 && (
        <div className="sugg">
          {suggestions.map((s) => (
            <button key={s} onClick={() => send(s)} disabled={busy}>{s}</button>
          ))}
        </div>
      )}
      <form onSubmit={(e) => { e.preventDefault(); send(q); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} maxLength={500}
               enterKeyHint="send" aria-label="Your question" />
        <button type="submit" disabled={busy || q.trim().length < 3}>Ask</button>
      </form>
      {thread.map((m, i) => (
        <div className="qa" key={i}>
          <div className="q">{m.q}</div>
          {m.error ? <div className="err" style={{ marginTop: 6 }}>{m.error}</div>
            : m.answer ? (
              <>
                <div className="a">{m.answer}</div>
                {!m.answerable && m.missing && <div className="miss">Not in the data: {m.missing}</div>}
                {m.sources?.length > 0 && <div className="src">Answered only from {m.sources.map((s) => SRC[s.type] || s.type).join(" and ")}.</div>}
              </>
            ) : <div className="reading"><span className="pulse" />{reading}</div>}
        </div>
      ))}
    </div>
  );
}
