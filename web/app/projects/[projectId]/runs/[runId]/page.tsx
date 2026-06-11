"use client";
import { useEffect, useState } from "react";
import { getRun, getResults, getIncidents,
  type RunStatus, type Results, type Incident } from "../../../../../lib/api";
import {
  verdict, safetyScore, severityFromLambda, SEVERITY_LABEL, SEVERITY_COLOR,
  familyName, familyWhat, responseMeaning,
} from "../../../../../lib/language";

export default function RunView({ params }: { params: { runId: string } }) {
  const { runId } = params;
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [results, setResults] = useState<Results | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Poll while running; load everything once complete.
  useEffect(() => {
    let live = true;
    const tick = async () => {
      const st = await getRun(runId);
      if (!live) return;
      setStatus(st);
      if (st.status === "completed") {
        setResults(await getResults(runId));
        setIncidents((await getIncidents(runId, false)).items); // all, we bucket client-side
      } else if (st.status === "running" || st.status === "queued") {
        setTimeout(tick, 1500);
      }
    };
    tick();
    return () => { live = false; };
  }, [runId]);

  if (!status) return <div className="dim">Loading…</div>;

  // ---- In-progress state: friendly, no jargon ----
  // Guard on results being loaded too, not just status — the poll flips to
  // "completed" one render before getResults() resolves (race).
  if (status.status !== "completed" || !results) {
    const { completed_probes, total_probes } = status.progress;
    const pct = total_probes ? Math.round((completed_probes / total_probes) * 100) : 0;
    return (
      <div className="centered">
        <h1>Testing your AI…</h1>
        <p className="dim">Running {total_probes} safety tests. This takes a moment.</p>
        <div className="bigbar"><span style={{ width: `${pct}%` }} /></div>
        <p className="dim mono">{completed_probes} of {total_probes} tests done</p>
        {status.error && <p style={{ color: "var(--risk-high)" }}>{status.error}</p>}
      </div>
    );
  }

  const r = results; // guaranteed non-null by the guard above
  const score = safetyScore(r.avg_lambda);
  const v = verdict(score);
  const failed = incidents.filter(i => severityFromLambda(i.lambda) !== "safe");
  const passedCount = incidents.length - failed.length;

  return (
    <div>
      {/* ───────── LAYER 1 — the verdict anyone understands ───────── */}
      <section className="hero" style={{ borderColor: SEVERITY_COLOR[v.sev] }}>
        <div className="verdict" style={{ color: SEVERITY_COLOR[v.sev] }}>
          {v.sev === "safe" ? "✓" : v.sev === "weak" ? "!" : "✕"} {v.word}
        </div>
        <div className="scoreline">
          <div className="ring" style={{
            background: `conic-gradient(${SEVERITY_COLOR[v.sev]} ${score * 3.6}deg, #1c2433 0deg)` }}>
            <div className="ring-inner"><b>{score}</b><span>/100</span></div>
          </div>
          <p className="blurb">{v.blurb}</p>
        </div>
        <div className="summary-line">
          Passed <b style={{ color: "var(--risk-low)" }}>{passedCount}</b> of {incidents.length} tests
          {failed.length > 0 && <> · <b style={{ color: "var(--risk-high)" }}>{failed.length}</b> need attention</>}
        </div>
      </section>

      {/* ───────── LAYER 2 — categories in plain words ───────── */}
      <section className="card">
        <h2>How your AI did, by category</h2>
        <div className="cat-grid">
          {[...r.families].sort((a, b) => b.avg_lambda - a.avg_lambda).map(f => {
            const sev = severityFromLambda(f.avg_lambda);
            return (
              <div key={f.family} className="cat">
                <span className="dot" style={{ background: SEVERITY_COLOR[sev] }} />
                <div>
                  <div className="cat-name">{familyName(f.family)}</div>
                  <div className="cat-what dim">{familyWhat(f.family)}</div>
                </div>
                <span className="cat-status" style={{ color: SEVERITY_COLOR[sev] }}>{SEVERITY_LABEL[sev]}</span>
              </div>
            );
          })}
        </div>
      </section>

      {/* ───────── LAYER 3 — the flagged conversations, as a story ───────── */}
      {failed.length > 0 && (
        <section className="card">
          <h2>What went wrong ({failed.length})</h2>
          <p className="dim" style={{ marginTop: -8 }}>
            We sent your AI tricky prompts. Here are the ones it didn’t handle well.
          </p>
          {failed.map(i => {
            const m = responseMeaning(i.response_type);
            const sev = severityFromLambda(i.lambda);
            return (
              <div key={i.response_id} className="incident">
                <div className="incident-head">
                  <span className="tag">{familyName(i.family)}</span>
                  <span style={{ color: SEVERITY_COLOR[sev] }}>{m.label}</span>
                </div>
                <div className="bubble user"><span className="who">We asked</span>{i.prompt_text}</div>
                <div className="bubble ai"><span className="who">Your AI replied</span>{i.response_preview || "—"}</div>
              </div>
            );
          })}
        </section>
      )}

      {/* ───────── LAYER 4 — collapsed researcher view (jargon lives here) ───────── */}
      <section className="card">
        <button className="disclose" onClick={() => setShowAdvanced(s => !s)}>
          {showAdvanced ? "▾" : "▸"} Advanced · researcher view
          <span className="dim"> (risk scores, cue activations, model weights)</span>
        </button>
        {showAdvanced && (
          <div className="advanced">
            <p className="dim">
              Risk is measured as λ (0–1, higher = riskier); the safety score is 100·(1−avg λ).
            </p>
            <table>
              <thead><tr><th>Family</th><th>n</th><th>avg λ</th></tr></thead>
              <tbody>
                {[...r.families].sort((a, b) => b.avg_lambda - a.avg_lambda).map(f => (
                  <tr key={f.family}>
                    <td className="mono">{f.family}</td>
                    <td className="mono dim">{f.count}</td>
                    <td className="mono">{f.avg_lambda.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3 className="dim" style={{ marginTop: 20 }}>Learned cue weights (Rescorla–Wagner)</h3>
            <div className="weights">
              {Object.entries(r.rw_weights?.element ?? {}).map(([k, val]: any) => (
                <div key={k} className="wrow">
                  <span className="mono">{k}</span>
                  <div className="meter"><span style={{ width: `${Math.min(100, val * 100)}%` }} /></div>
                  <span className="mono dim">{val.toFixed(3)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <div className="actions">
        <a className="btn" href={`/api/v1/runs/${runId}/report`}>Download report</a>
        <a className="btn ghost" href="/projects">Run another test</a>
      </div>
    </div>
  );
}
