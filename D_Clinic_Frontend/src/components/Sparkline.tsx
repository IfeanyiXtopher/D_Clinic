type Pt = { systolic: number; diastolic: number; when: string };

export function Sparkline({ points }: { points: Pt[] }) {
  if (!points.length) return <p className="empty">No BP series.</p>;
  const w = 420;
  const h = 72;
  const pad = 6;
  const xs = points.map((_, i) => (points.length === 1 ? w / 2 : pad + (i * (w - pad * 2)) / (points.length - 1)));
  const vals = points.flatMap((p) => [p.systolic, p.diastolic]);
  const min = Math.min(80, ...vals) - 4;
  const max = Math.max(180, ...vals) + 4;
  const y = (v: number) => pad + ((max - v) / (max - min)) * (h - pad * 2);
  const line = (key: "systolic" | "diastolic") =>
    points.map((p, i) => `${i === 0 ? "M" : "L"} ${xs[i].toFixed(1)} ${y(p[key]).toFixed(1)}`).join(" ");
  const goal = y(140);
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Blood pressure sparkline">
      <line x1={pad} x2={w - pad} y1={goal} y2={goal} stroke="#d8d0c2" strokeDasharray="3 3" />
      <path d={line("systolic")} fill="none" stroke="#9f1239" strokeWidth="2" />
      <path d={line("diastolic")} fill="none" stroke="#0f6b63" strokeWidth="2" />
      {points.map((p, i) => (
        <circle key={i} cx={xs[i]} cy={y(p.systolic)} r="2.4" fill="#9f1239">
          <title>{`${p.when}: ${p.systolic}/${p.diastolic}`}</title>
        </circle>
      ))}
    </svg>
  );
}
