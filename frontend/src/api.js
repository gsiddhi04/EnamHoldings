async function call(path, opts = {}) {
  let r;
  try {
    r = await fetch("/api" + path, { headers: { "content-type": "application/json" }, ...opts });
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
  seen: (id) => call(`/alerts/${id}/seen`, { method: "POST" }),
  settings: () => call("/settings"),
  saveSettings: (body) => call("/settings", { method: "PUT", body: JSON.stringify(body) }),
  holdings: () => call("/holdings"),
  stock: (sym) => call(`/stock/${encodeURIComponent(sym)}?ann_limit=15&price_days=45`),
  announcement: (id) => call(`/announcement/${encodeURIComponent(id)}`),
  research: (sym) => call(`/research/${encodeURIComponent(sym)}`),
  promises: (sym) => call(`/research/${encodeURIComponent(sym)}/promises`),
  bullbear: (sym) => call(`/research/${encodeURIComponent(sym)}/bullbear`),
  ask: (body) => call("/ask", { method: "POST", body: JSON.stringify(body) }),
};
