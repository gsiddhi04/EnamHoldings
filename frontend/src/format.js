const MINUS = "−";

export const inr = (n, d = 0) =>
  n == null || Number.isNaN(n) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

export const rupee = (n, d = 0) => (n == null ? "—" : "₹" + inr(n, d));

/** +12.0% / −3.4% (real minus sign so columns line up) */
export function pct(n, d = 1, plus = true) {
  if (n == null || Number.isNaN(n)) return "—";
  const s = Math.abs(n).toFixed(d) + "%";
  return n < 0 ? MINUS + s : (plus && n > 0 ? "+" : "") + s;
}

export const dir = (n) => (n == null || Math.abs(n) < 0.05 ? "flat" : n > 0 ? "up" : "down");

export const CAT = {
  results: "Results", "M&A": "Deals", fund_raise: "Fund-raising", management_change: "Leadership",
  litigation: "Legal & regulatory", insider_trading: "Insider trading", earnings_call: "Earnings call",
  investor_meetings: "Investor meetings", credit_rating: "Credit rating", dividend: "Dividend",
  bonus_split: "Bonus / split", capex: "Capex", press_release: "News", postal_ballot: "Postal ballot",
  agm_egm: "Shareholder meeting", pledging: "Promoter pledge", unclassified: "Other",
};

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const FULL_MON = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** Parse "2026-11-02T18:45:24" without timezone games: the server already speaks IST. */
function parts(iso) {
  const m = /^(\d{4})-(\d\d)-(\d\d)(?:[T ](\d\d):(\d\d))?/.exec(iso || "");
  return m ? { y: +m[1], mo: +m[2], d: +m[3], h: m[4] == null ? null : +m[4], mi: m[5] == null ? null : +m[5] } : null;
}

export function clock(p) {
  if (p.h == null) return "";
  const h12 = p.h % 12 || 12;
  return `${h12}:${String(p.mi).padStart(2, "0")} ${p.h < 12 ? "am" : "pm"}`;
}

/** "6:45 pm" today, "Yesterday" , else "2 Nov" - relative to the server's now */
export function when(iso, nowIso) {
  const p = parts(iso), n = parts(nowIso);
  if (!p) return "";
  const dd = n ? Math.round((Date.UTC(n.y, n.mo - 1, n.d) - Date.UTC(p.y, p.mo - 1, p.d)) / 864e5) : 99;
  if (dd === 0) return clock(p) || "Today";
  if (dd === 1) return "Yesterday" + (p.h != null ? ", " + clock(p) : "");
  return `${p.d} ${MON[p.mo - 1]}`;
}

export function dateline(nowIso) {
  const p = parts(nowIso);
  if (!p) return "";
  const dow = DAYS[new Date(Date.UTC(p.y, p.mo - 1, p.d)).getUTCDay()];
  return `${dow} ${p.d} ${FULL_MON[p.mo - 1]} ${p.y}`;
}

export function shortDate(iso) {
  const p = parts(iso);
  return p ? `${p.d} ${MON[p.mo - 1]} ${p.y}` : iso || "";
}

const WORDS = ["Nothing", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve"];
export const word = (n) => (n < WORDS.length ? WORDS[n] : String(n));
export const lower = (s) => s.charAt(0).toLowerCase() + s.slice(1);
export const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;

/** "2 Nov 2026, 6:45 pm" */
export function stamp(iso) {
  const p = parts(iso);
  return p ? `${p.d} ${MON[p.mo - 1]} ${p.y}${p.h != null ? ", " + clock(p) : ""}` : iso || "";
}
