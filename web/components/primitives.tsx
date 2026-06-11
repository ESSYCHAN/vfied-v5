// Shared dark-research primitives. Behaviour is the primary object: the
// scientific units (risk verdict, lambda, cues) get consistent, prominent styling.

export function RiskBadge({ label }: { label: string | null }) {
  if (!label) return null;
  const cls = label.includes("LOW") ? "low" : label.includes("MEDIUM") ? "med" : "high";
  return <span className={`badge ${cls}`}>{label}</span>;
}

// LambdaMeter — the core scientific unit (0..1), shown identically everywhere.
export function LambdaMeter({ value }: { value: number | null }) {
  const v = value ?? 0;
  const color = v < 0.3 ? "var(--risk-low)" : v < 0.6 ? "var(--risk-med)" : "var(--risk-high)";
  return (
    <div className="row" style={{ gap: 8 }}>
      <div className="meter" style={{ maxWidth: 120 }}>
        <span style={{ width: `${Math.min(100, v * 100)}%`, background: color }} />
      </div>
      <span className="mono dim" style={{ fontSize: 12 }}>{v.toFixed(3)}</span>
    </div>
  );
}

export function CueChip({ cue, configural }: { cue: string; configural?: boolean }) {
  return <span className={`chip ${configural ? "configural" : ""}`}>{cue}</span>;
}
