import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { CAT, dir, inr, pct, stamp } from "./format.js";
import { useAsync } from "./hooks.js";
import { disablePush, enablePush, pushStatus } from "./push.js";

const FOLLOW = ["results", "M&A", "management_change", "litigation", "credit_rating", "fund_raise", "dividend",
  "bonus_split", "capex", "insider_trading", "pledging", "earnings_call"];

function Stepper({ value, set, min, max, step, fmt, label }) {
  const bump = (d) => set(Math.min(max, Math.max(min, Math.round((value + d) * 100) / 100)));
  return (
    <div className="stepper" role="group" aria-label={label}>
      <button onClick={() => bump(-step)} disabled={value <= min} aria-label={`Decrease ${label}`}>−</button>
      <output className="num">{fmt(value)}</output>
      <button onClick={() => bump(step)} disabled={value >= max} aria-label={`Increase ${label}`}>+</button>
    </div>
  );
}

function PushRow() {
  const st = useAsync(pushStatus, []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const s = st.data?.state;
  if (!s || s === "unavailable") return null;
  const toggle = async () => {
    setBusy(true); setErr("");
    try { s === "on" ? await disablePush() : await enablePush(st.data.key); st.reload(); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };
  const note = {
    "needs-install": "On iPhone, add FINN to your Home Screen first (Share, then Add to Home Screen), then open it from there to turn this on.",
    unsupported: "This browser can't show notifications.",
    denied: "Notifications are blocked for this site in your browser settings.",
    on: "On. We'll notify you when a refresh finds something new that crosses your limits.",
    off: "Get a notification on this device when something new crosses your limits.",
  }[s];
  return (
    <div className="panel" style={{ marginTop: 12 }}>
      <div className="rowset">
        <div><div className="lbl">Notify me on this device</div><div className="sub">{note}</div></div>
        {(s === "on" || s === "off") && (
          <button className={`tog ${s === "on" ? "on" : ""}`} onClick={toggle} disabled={busy} aria-pressed={s === "on"}>{s === "on" ? "On" : "Turn on"}</button>
        )}
      </div>
      {err && <div className="err" style={{ marginBottom: 10 }}>{err}</div>}
    </div>
  );
}

export default function Alerts({ onOpen, goStock, onBadge }) {
  const settings = useAsync(api.settings, []);
  const list = useAsync(api.alerts, []);
  const [s, setS] = useState(null);
  const [status, setStatus] = useState("");
  const timer = useRef(null);
  const dirty = useRef(false);

  useEffect(() => { if (settings.data && !s) setS(settings.data); }, [settings.data, s]);
  useEffect(() => { onBadge?.(list.data ? list.data.alerts.filter((a) => !a.seen).length : null); }, [list.data]); // eslint-disable-line

  function change(patch) {
    const next = { ...s, ...patch };
    setS(next);
    dirty.current = true;
    setStatus("Saving…");
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try {
        const r = await api.saveSettings({
          price_move_pct: next.price_move_pct, volume_multiple: next.volume_multiple, alert_categories: next.alert_categories,
        });
        setStatus(`Saved. Watching with these limits: ${r.alerts_after} alert${r.alerts_after === 1 ? "" : "s"} in the last week.`);
        list.reload();
      } catch (e) {
        setStatus("Couldn't save: " + e.message);
      }
    }, 600);
  }

  const toggle = (c) => change({ alert_categories: s.alert_categories.includes(c) ? s.alert_categories.filter((x) => x !== c) : [...s.alert_categories, c] });

  async function read(a) {
    if (!a.seen) { api.seen(a.key).then(list.reload); }
  }
  async function readAll() {
    await api.seenAll();
    list.reload();
  }

  const alerts = list.data?.alerts || [];
  const unseen = alerts.filter((a) => !a.seen).length;

  return (
    <>
      <h1 className="page-title">Alerts</h1>
      <p className="standfirst" style={{ marginBottom: 4 }}>You decide what counts as unusual. FINN watches the closing prices and the filings for you.</p>

      <div className="sec"><h2>What counts as unusual</h2></div>
      {settings.error && <div className="err">{settings.error}<button onClick={settings.reload}>Try again</button></div>}
      {s && (
        <>
          <div className="panel">
            <div className="rowset">
              <div><div className="lbl">Price moves by more than</div><div className="sub">in one day, up or down</div></div>
              <Stepper value={s.price_move_pct} set={(v) => change({ price_move_pct: v })} min={1} max={20} step={0.5} fmt={(v) => `±${v}%`} label="price move" />
            </div>
            <div className="rowset">
              <div><div className="lbl">Volume above</div><div className="sub">times its {s.volume_avg_days}-day average</div></div>
              <Stepper value={s.volume_multiple} set={(v) => change({ volume_multiple: v })} min={1.5} max={10} step={0.5} fmt={(v) => `${v}×`} label="volume multiple" />
            </div>
            <div className="lbl" style={{ fontFamily: "var(--serif)", fontSize: 17, padding: "12px 0 8px", borderTop: "1px solid var(--rule)" }}>
              Tell me about these filings <span className="sub" style={{ fontFamily: "var(--sans)", fontSize: 12.5, color: "var(--ink3)" }}>(when ranked {s.alert_min_priority}+ of 100)</span>
            </div>
            <div className="toggles">
              {FOLLOW.map((c) => (
                <button key={c} className={`tog ${s.alert_categories.includes(c) ? "on" : ""}`} aria-pressed={s.alert_categories.includes(c)} onClick={() => toggle(c)}>
                  {CAT[c] || c}
                </button>
              ))}
            </div>
          </div>
          <div className="status" role="status">{status}</div>
        </>
      )}

      <PushRow />

      <div className="sec"><h2>Triggered</h2>
        {unseen > 0 && <button className="linkbtn" style={{ marginLeft: "auto", order: 4 }} onClick={readAll}>Mark all read</button>}
      </div>
      {list.error && <div className="err">{list.error}<button onClick={list.reload}>Try again</button></div>}
      {list.data && alerts.length === 0 && <div className="empty">Nothing has crossed your limits.<br />Loosen them above to see more.</div>}
      {alerts.map((a) => <AlertRow key={a.key} a={a} onOpen={onOpen} goStock={goStock} read={read} />)}
    </>
  );
}

function AlertRow({ a, onOpen, goStock, read }) {
  const d = a.detail || {};
  const tap = () => {
    read(a);
    if (a.kind === "announcement") onOpen({ id: a.ref_id, symbol: a.symbol, name: a.name, facts: undefined });
    else goStock(a.symbol);
  };
  let cls = "", big, meta;
  if (a.kind === "price_move") {
    cls = dir(d.pct);
    big = <>{a.symbol} <span className={`num ${cls}`}>{pct(d.pct, 1)}</span></>;
    meta = `Closed at ₹${inr(d.close)} from ₹${inr(d.prev_close)}${d.provisional ? " · session still open" : ""}`;
  } else if (a.kind === "volume_spike") {
    cls = "vol";
    big = <>{a.symbol} traded <span className="num">{d.multiple.toFixed(1)}×</span> its usual volume</>;
    meta = `${inr(d.volume)} shares against a ${inr(d.avg_volume)} average${d.provisional ? " · session still open" : ""}`;
  } else {
    big = a.summary || a.title.replace(/^[^:]+:\s*/, "");
    meta = `${a.name || a.symbol} · ${CAT[d.category] || d.category}`;
  }
  return (
    <button className={`alert ${cls} ${a.seen ? "seen" : ""}`} onClick={tap}>
      <span className="bar" />
      <span className="in">
        <div className="big">{!a.seen && <span className="unseen-dot" aria-label="unread" />}{big}</div>
        <div className="meta num">{meta} · {stamp(a.event_at)}</div>
      </span>
    </button>
  );
}
