/** A random id per browser: alert thresholds and read-state are personal, even on a shared public link. */
function visitorId() {
  try {
    let v = localStorage.getItem("finn.visitor");
    if (!v) {
      v = (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36)).replace(/[^A-Za-z0-9-]/g, "");
      localStorage.setItem("finn.visitor", v);
    }
    return v;
  } catch {
    return "anonymous";
  }
}

async function call(path, opts = {}) {
  let r;
  try {
    r = await fetch("/api" + path, { headers: { "content-type": "application/json", "x-visitor": visitorId() }, ...opts });
  } catch {
    throw new Error("Can't reach the FINN server. Is it running?");
  }
  if (!r.ok) {
    let msg = `Request failed (${r.status})`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : msg;
    } catch { /* keep default */ }
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  digest: (hours) => call(`/digest?hours=${hours}&movers=8`),
  alerts: () => call("/alerts?limit=80"),
  seen: (key) => call(`/alerts/${encodeURIComponent(key)}/seen`, { method: "POST" }),
  seenAll: () => call("/alerts/seen-all", { method: "POST" }),
  pushKey: () => call("/push/key"),
  pushSubscribe: (sub) => call("/push/subscribe", { method: "POST", body: JSON.stringify(sub) }),
  pushUnsubscribe: (sub) => call("/push/unsubscribe", { method: "POST", body: JSON.stringify(sub) }),
  settings: () => call("/settings"),
  saveSettings: (body) => call("/settings", { method: "PUT", body: JSON.stringify(body) }),
  holdings: () => call("/holdings"),
  stock: (sym) => call(`/stock/${encodeURIComponent(sym)}?ann_limit=15&price_days=45`),
  announcement: (id) => call(`/announcement/${encodeURIComponent(id)}`),
  research: (sym) => call(`/research/${encodeURIComponent(sym)}`),
  promises: (sym) => call(`/research/${encodeURIComponent(sym)}/promises`),
  business: (sym) => call(`/research/${encodeURIComponent(sym)}/business`),
  bullbear: (sym) => call(`/research/${encodeURIComponent(sym)}/bullbear`),
  ask: (body) => call("/ask", { method: "POST", body: JSON.stringify(body) }),
};
