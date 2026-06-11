"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  createProject, createConnection, listSuites, previewRun, submitRun,
  type Suite, type Connection, type PreviewResult, ApiError,
} from "../../lib/api";

// MVP single-flow: create project -> connect a model (two trust models) ->
// cost-disclosure gate -> launch run -> navigate to the run view.
export default function ProjectsPage() {
  const router = useRouter();
  const [projectId, setProjectId] = useState<string | null>(null);
  const [conn, setConn] = useState<Connection | null>(null);
  const [tab, setTab] = useState<"key" | "endpoint">("key");
  const [suites, setSuites] = useState<Suite[]>([]);
  const [suite, setSuite] = useState<string>("tax");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // key-based fields
  const [model, setModel] = useState("claude-opus-4-8");
  const [apiKey, setApiKey] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  // endpoint fields
  const [endpoint, setEndpoint] = useState("");
  const [authHeader, setAuthHeader] = useState("");
  const [responsePath, setResponsePath] = useState("response");

  async function makeProject() {
    setBusy(true); setErr(null);
    try {
      const p = await createProject("My behaviour project");
      setProjectId(p.id);
      setSuites(await listSuites());
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function connect() {
    if (!projectId) return;
    setBusy(true); setErr(null);
    try {
      const body = tab === "key"
        ? { kind: "key_based", display_name: "Claude prod", provider: "anthropic",
            model, api_key: apiKey, system_prompt: systemPrompt || null }
        : { kind: "endpoint_based", display_name: "Custom endpoint", endpoint,
            headers: authHeader ? { Authorization: authHeader } : null, response_path: responsePath };
      setConn(await createConnection(projectId, body));
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  // Cost-disclosure gate: must run BEFORE the run can be confirmed.
  async function doPreview() {
    if (!projectId || !conn) return;
    setBusy(true); setErr(null);
    try { setPreview(await previewRun(projectId, conn.id, suite)); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function confirmRun() {
    if (!projectId || !preview) return;
    setBusy(true); setErr(null);
    try {
      const res = await submitRun(projectId, preview.run_id, preview.probe_count, preview.probe_set_hash);
      router.push(`/projects/${projectId}/runs/${res.run_id}`);
    } catch (e: any) {
      // 409 => suite drifted since preview; force re-preview (freeze invariant).
      if (e instanceof ApiError && e.status === 409) { setPreview(null); setErr("Probe set changed — re-preview required."); }
      else setErr(e.message);
    } finally { setBusy(false); }
  }

  return (
    <div>
      <h1>New behaviour evaluation</h1>
      {err && <div className="notice" style={{ borderColor: "var(--risk-high)", color: "var(--risk-high)" }}>{err}</div>}

      <div className="card">
        <h2>1 · Project</h2>
        {projectId
          ? <div className="dim mono">project {projectId.slice(0, 8)}…</div>
          : <button onClick={makeProject} disabled={busy}>Create project</button>}
      </div>

      {projectId && (
        <div className="card">
          <h2>2 · Connect your AI</h2>
          <div className="tabs">
            <button className={tab === "key" ? "active" : ""} onClick={() => setTab("key")}>Key-based</button>
            <button className={tab === "endpoint" ? "active" : ""} onClick={() => setTab("endpoint")}>Endpoint</button>
          </div>
          {tab === "key" ? (
            <>
              <div className="notice">VFIED stores your key encrypted at rest, scoped per-run.</div>
              <label>Model</label><input value={model} onChange={e => setModel(e.target.value)} />
              <label>API key</label><input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="sk-ant-…" />
              <label>System prompt (optional)</label><textarea value={systemPrompt} onChange={e => setSystemPrompt(e.target.value)} />
            </>
          ) : (
            <>
              <div className="notice">VFIED holds no required credential in endpoint mode (safer posture).</div>
              <label>Endpoint URL</label><input value={endpoint} onChange={e => setEndpoint(e.target.value)} placeholder="https://bot.acme.com/converse" />
              <label>Authorization header (optional, encrypted)</label><input value={authHeader} onChange={e => setAuthHeader(e.target.value)} placeholder="Bearer …" />
              <label>Response path</label><input value={responsePath} onChange={e => setResponsePath(e.target.value)} />
            </>
          )}
          <button onClick={connect} disabled={busy}>Save connection</button>
          {conn && <span className="dim mono" style={{ marginLeft: 12 }}>
            connected: {conn.kind === "key_based" ? `${conn.provider}/${conn.model} (…${conn.api_key_last4})` : conn.endpoint}
          </span>}
        </div>
      )}

      {conn && (
        <div className="card">
          <h2>3 · Choose suite & confirm cost</h2>
          <label>Suite</label>
          <select value={suite} onChange={e => { setSuite(e.target.value); setPreview(null); }}>
            {suites.map(s => <option key={s.slug} value={s.slug}>{s.slug} · {s.probe_count} probes</option>)}
          </select>
          {!preview
            ? <button onClick={doPreview} disabled={busy}>See what we’ll test</button>
            : (
              <div className="cost-box">
                <div className="big-stat">{preview.probe_count}</div>
                <div className="dim">safety tests will be run on your AI</div>
                <div className="dim" style={{ marginTop: 6 }}>{preview.billing_note}</div>
                <div style={{ marginTop: 14 }}>
                  <button onClick={confirmRun} disabled={busy || !preview.cap.within_cap}>
                    Start {preview.probe_count} tests
                  </button>
                  {!preview.cap.within_cap && <span className="dim" style={{ marginLeft: 10 }}>
                    Too many tests (limit {preview.cap.max_probes})
                  </span>}
                </div>
              </div>
            )}
        </div>
      )}
    </div>
  );
}
