import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import Alerts from "./Alerts.jsx";
import Brief from "./Brief.jsx";
import Holdings from "./Holdings.jsx";
import Research from "./Research.jsx";
import Sheet from "./Sheet.jsx";

const ICON = {
  brief: <path d="M5 4h11a2 2 0 0 1 2 2v13H7a2 2 0 0 1-2-2V4zm13 5h2v8a2 2 0 0 1-2 2M8.5 8h6M8.5 11.5h6M8.5 15h3.5" />,
  alerts: <path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15L6 16zM10 20.5a2 2 0 0 0 4 0" />,
  holdings: <path d="M4 19V9M10 19V5M16 19v-7M21 19H3M4 9l6-4 6 7" />,
  research: <path d="M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15zM16 16l5 5" />,
};
const TABS = [["brief", "Brief"], ["alerts", "Alerts"], ["holdings", "Holdings"], ["research", "Research"]];

function route() {
  const [, tab, arg] = (window.location.hash || "").split("/");
  if (tab === "filing" && arg) return { tab: "brief", arg: null, filing: decodeURIComponent(arg) };   // deep link to a filing
  return { tab: ICON[tab] ? tab : "brief", arg: arg ? decodeURIComponent(arg) : null };
}

export default function App() {
  const [r, setR] = useState(route);
  const [sheet, setSheet] = useState(null);
  const [badge, setBadge] = useState(null);
  const [now, setNow] = useState(null);

  useEffect(() => {
    const on = () => { setR(route()); setSheet(null); window.scrollTo(0, 0); };   // navigating (incl. the back button) dismisses any open sheet
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => { if (r.filing) setSheet({ id: r.filing, facts: undefined }); }, [r.filing]);
  useEffect(() => { api.alerts().then((a) => setBadge(a.alerts.filter((x) => !x.seen).length), () => {}); }, []);

  const go = useCallback((tab, arg) => { window.location.hash = "/" + tab + (arg ? "/" + encodeURIComponent(arg) : ""); }, []);
  const goStock = useCallback((sym) => go("holdings", sym), [go]);
  const open = useCallback((it) => { setSheet(it); if (it.ann_dt && !now) setNow(it.ann_dt); }, [now]);

  return (
    <>
      <main className="app" key={r.tab + (r.arg || "")}>
        {r.tab === "brief" && <Brief onOpen={open} goStock={goStock} />}
        {r.tab === "alerts" && <Alerts onOpen={open} goStock={goStock} onBadge={setBadge} />}
        {r.tab === "holdings" && <Holdings symbol={r.arg} go={go} onOpen={open} />}
        {r.tab === "research" && <Research symbol={r.arg} go={go} />}
      </main>
      <nav className="tabbar" aria-label="Main">
        <div className="tabbar-in">
          {TABS.map(([id, label]) => (
            <button key={id} className={`tab ${r.tab === id ? "on" : ""}`} onClick={() => go(id)} aria-current={r.tab === id ? "page" : undefined}>
              <svg viewBox="0 0 24 24" aria-hidden>{ICON[id]}</svg>
              {label}
              {id === "alerts" && badge > 0 && <span className="dot">{badge > 99 ? "99+" : badge}</span>}
            </button>
          ))}
        </div>
      </nav>
      {sheet && <Sheet key={sheet.id} item={sheet} now={now} onClose={() => { setSheet(null); if (r.filing) go("brief"); }} />}
    </>
  );
}
