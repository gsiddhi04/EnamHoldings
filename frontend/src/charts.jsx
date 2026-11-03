import { useId } from "react";
import { dir } from "./format.js";

const NAVY = "#1E2B4F", UP = "#1D6B47", DOWN = "#A7322A", INK3 = "rgba(26,23,20,.58)";
const col = (d) => (d === "up" ? UP : d === "down" ? DOWN : INK3);

/** "Mar 2026" -> "FY26"; anything else -> "Sep 26" */
export function period(p) {
  const m = /^(\w{3}) (\d{4})$/.exec(p || "");
  if (!m) return p || "";
  const yy = m[2].slice(2);
  return m[1] === "Mar" ? `FY${yy}` : `${m[1]} ${yy}`;
}

export function compact(n) {
  if (n == null) return "";
  const a = Math.abs(n), s = n < 0 ? "−" : "";
  if (a >= 1e5) return s + (a / 1e5).toFixed(2) + "L";
  if (a >= 1e3) return s + (a / 1e3).toFixed(1) + "k";
  return s + (a >= 100 ? a.toFixed(0) : a.toFixed(1));
}

function path(vals, w, h, pad = 3) {
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const x = (i) => pad + (i * (w - pad * 2)) / Math.max(vals.length - 1, 1);
  const y = (v) => pad + (h - pad * 2) * (1 - (v - lo) / span);
  return { x, y, lo, hi, d: vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("") };
}

/** Tiny trend line for the holdings list. */
export function Spark({ data, w = 86, h = 32 }) {
  if (!data || data.length < 2) return <svg width={w} height={h} aria-hidden />;
  const { d, x, y } = path(data, w, h);
  const c = col(dir(data[data.length - 1] - data[0]));
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden>
      <path d={d} fill="none" stroke={c} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(data.length - 1)} cy={y(data[data.length - 1])} r="2.4" fill={c} />
    </svg>
  );
}

/** Larger price chart for the stock page, with the range called out in print rather than gridlines. */
export function PriceChart({ data, dates }) {
  const id = useId();
  const w = 340, h = 150;
  if (!data || data.length < 2) return null;
  const { d, x, y, lo, hi } = path(data, w, h, 6);
  const c = col(dir(data[data.length - 1] - data[0]));
  const area = `${d}L${x(data.length - 1)},${h}L${x(0)},${h}Z`;
  const iHi = data.indexOf(hi), iLo = data.indexOf(lo);
  const lab = (i, v, above) => (
    <text x={Math.min(Math.max(x(i), 22), w - 22)} y={y(v) + (above ? -6 : 13)} textAnchor="middle" className="val">
      {Math.round(v).toLocaleString("en-IN")}
    </text>
  );
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${w} ${h + 14}`} role="img" aria-label="Closing price chart">
        <defs>
          <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor={c} stopOpacity=".22" />
            <stop offset="1" stopColor={c} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${id})`} />
        <path d={d} fill="none" stroke={c} strokeWidth="1.8" strokeLinejoin="round" />
        {lab(iHi, hi, true)}
        {lab(iLo, lo, false)}
        <circle cx={x(data.length - 1)} cy={y(data[data.length - 1])} r="3.5" fill={c} />
        <text x={x(0)} y={h + 12} textAnchor="start">{dates?.[0] || ""}</text>
        <text x={x(data.length - 1)} y={h + 12} textAnchor="end">{dates?.[dates.length - 1] || ""}</text>
      </svg>
    </div>
  );
}

/** Single-series bars. Latest bar in full navy, earlier ones washed; negatives in red. */
export function Bars({ data, h = 118 }) {
  const rows = (data || []).filter((r) => r.value != null);
  if (rows.length < 2) return <p className="foot">Not enough history to chart.</p>;
  const w = 340, base = h - 4, top = 16;
  const hi = Math.max(...rows.map((r) => r.value), 0), lo = Math.min(...rows.map((r) => r.value), 0);
  const span = hi - lo || 1, zero = top + ((base - top) * hi) / span;
  const bw = w / rows.length;
  return (
    <svg viewBox={`0 0 ${w} ${h + 16}`} role="img">
      <line x1="0" x2={w} y1={zero} y2={zero} stroke="rgba(26,23,20,.3)" />
      {rows.map((r, i) => {
        const bh = Math.max((Math.abs(r.value) / span) * (base - top), 1.5);
        const y0 = r.value >= 0 ? zero - bh : zero;
        const last = i === rows.length - 1;
        const fill = r.value < 0 ? DOWN : last ? NAVY : "rgba(30,43,79,.34)";
        return (
          <g key={r.period}>
            <rect x={i * bw + bw * 0.16} y={y0} width={bw * 0.68} height={bh} fill={fill} rx="1.5" />
            <text x={i * bw + bw / 2} y={(r.value >= 0 ? y0 : y0 + bh) + (r.value >= 0 ? -4 : 11)} textAnchor="middle" className={last ? "val" : ""}>
              {compact(r.value)}
            </text>
            <text x={i * bw + bw / 2} y={h + 12} textAnchor="middle">{period(r.period)}</text>
          </g>
        );
      })}
    </svg>
  );
}

/** Two bars per year: operating cash flow beside net profit. */
export function PairBars({ rows, h = 124 }) {
  if (!rows || rows.length < 2) return <p className="foot">Not enough history to chart.</p>;
  const w = 340, base = h - 4, top = 16;
  const hi = Math.max(...rows.flatMap((r) => [r.a, r.b]), 1);
  const bw = w / rows.length;
  const hgt = (v) => Math.max((Math.max(v, 0) / hi) * (base - top), 1.5);
  return (
    <svg viewBox={`0 0 ${w} ${h + 16}`} role="img">
      {rows.map((r, i) => {
        const x0 = i * bw + bw * 0.1, half = bw * 0.38;
        return (
          <g key={r.period}>
            <rect x={x0} y={base - hgt(r.a)} width={half} height={hgt(r.a)} fill={NAVY} rx="1.5" />
            <rect x={x0 + half + 2} y={base - hgt(r.b)} width={half} height={hgt(r.b)} fill="rgba(167,126,70,.85)" rx="1.5" />
            <text x={i * bw + bw / 2} y={base - Math.max(hgt(r.a), hgt(r.b)) - 4} textAnchor="middle" className="val">
              {r.ratio == null ? "" : r.ratio.toFixed(2) + "×"}
            </text>
            <text x={i * bw + bw / 2} y={h + 12} textAnchor="middle">{period(r.period)}</text>
          </g>
        );
      })}
    </svg>
  );
}

/** Line with the endpoints labelled; used for margins. */
export function Line({ data, suffix = "%" }) {
  const rows = (data || []).filter((r) => r.value != null);
  if (rows.length < 2) return <p className="foot">Not enough history to chart.</p>;
  const w = 340, h = 96;
  const { d, x, y } = path(rows.map((r) => r.value), w, h, 14);
  return (
    <svg viewBox={`0 0 ${w} ${h + 16}`} role="img">
      <path d={d} fill="none" stroke={NAVY} strokeWidth="1.8" strokeLinejoin="round" />
      {rows.map((r, i) => (
        <g key={r.period}>
          <circle cx={x(i)} cy={y(r.value)} r={i === rows.length - 1 ? 3.6 : 2.4} fill={NAVY} />
          <text x={x(i)} y={y(r.value) - 8} textAnchor="middle" className={i === rows.length - 1 ? "val" : ""}>{r.value.toFixed(1)}{suffix}</text>
          <text x={x(i)} y={h + 12} textAnchor="middle">{period(r.period)}</text>
        </g>
      ))}
    </svg>
  );
}
