# VFIED — Behaviour Evaluation Platform: Migration Plan

> **Product line:** "Bring your own AI. VFIED tests the behaviour."
> The primary object in the UI is **Behaviour**, not the Model.
> This is a **migration of the existing Python/FastAPI codebase**, expressed as
> diffs from current files — not a greenfield rebuild.

## Frozen core (never edited; continuously regression-checked)

The behavioural-science engine is a frozen library. The entire migration is
plumbing *around* it:

- `models/rw_model.py` — RW/TD risk engine, `update(... gamma=0.9)`, weight dicts.
- `evaluation/evaluator.py` — λ math, dynamic-asymptote `evaluate_outcome`, `classify_response`, `compute_oat_p/o`.
- `profiles/tax/`, `profiles/legal/` — cue lexicons, `prompt_families`, `rules.py`, `cues.py` (logic frozen; only *loading* changes).
- `adapters/base.py` — `BaseAdapter.generate()/name` plugin seam.

A golden baseline (Step 0) gates Steps 2, 5, 8: same inputs → same λ / family
summaries / RW weights.

---

## Fixed decisions (do not re-litigate)

- **Cost boundary:** customers pay for their own model inference via their own
  key/endpoint. VFIED never serves inference on its own account. Per-run VFIED
  cost ≈ zero. Semantic scorer defaults to a **local** embedder (BGE/E5-small,
  CPU); customer embedding key is enterprise override only. **Embedder identity
  is stored with every anchor/experiment** — vectors are not comparable across
  embedders.
- **Two trust models, modelled distinctly (not one nullable row):**
  - *Key-based* (OpenAI/Anthropic/Azure): customer API key, encrypted at rest,
    scoped per-run, never logged, never in exemplar files, never in a report.
  - *Endpoint-based* (Botpress/Voiceflow/custom REST): customer endpoint +
    header/field mapping (the existing `HttpAdapter` shape). VFIED holds no
    *required* credential — safer enterprise posture.
- **Adapters are plugins:** new connectors addable without touching core
  scoring. `BaseAdapter` is the seam.
- **Probe count is a cost disclosure:** visible and capped *before* a run.

## Stack (confirmed)

- Backend stays Python / FastAPI.
- Persistence: JSON-on-disk → Postgres; large response blobs → object storage.
- Frontend: React + Next.js, dark research-grade theme (W&B / LangSmith /
  Datadog / Snyk register).
- Cloud-hosted SaaS for v1. `vercel.json`'s serverless model **cannot** host the
  long-running stateful worker — runs need a **job queue + worker**, not a
  serverless request. API may stay serverless; the worker is a persistent process.
- Audience: external paying AI/research teams + own research use.

---

## Resolved decisions

### [DECIDED] (a) Endpoint-mode `headers` — encrypt the entire blob at rest
Encrypt the **whole `headers` jsonb** as one opaque ciphertext, same envelope/KMS
scheme as `api_key_ciphertext`. **Do not** classify which headers "look sensitive"
— that is a classifier you will get wrong (`X-Api-Key`, `Cookie`, signed-query
headers, vendor schemes). Blanket encrypt is simpler and has no downside: the blob
is opaque to VFIED and is never queried.

*Why:* customers will paste `Authorization: Bearer …` into endpoint headers in
practice. Storing that in plaintext while the key-based path encrypts would make
the path *labelled* safer the one holding a live bearer token in the clear — the
worst inversion, and exactly what reads terribly in a security review or
procurement questionnaire (the audience endpoint-mode exists to win). Encrypting
keeps the "VFIED holds no *required* credential" promise true even when the
customer supplies one anyway.

### [DECIDED] (b) `acknowledged_probe_count` — strict 409 gate by default
Strict 409 in MVP. `allow_probe_drift` (relaxed path for trusted programmatic
callers) is **deferred to v2** — the only consumers that would want it are
regression testing and continuous monitoring, both v2. No v1 caller needs it, so
strict is free, not a constraint: the 409 only fires on genuine preview→submit
drift, which is precisely when you want to halt and re-disclose.

**The gate is only real under the freeze invariant below.** Without it the gate is
theatre: the count could pass at submit while the worker re-expands the suite and
runs more probes than were disclosed.

### [INVARIANT] Probe-set freeze (load-bearing for (b))
The probe set is resolved and **frozen once, at preview**, persisted with the run
(ordered `(family, prompt)` list + content hash), and the **worker executes the
frozen set verbatim** — it never re-expands the suite.

- `POST /runs/preview` expands the suite (`build_prompt_cases`, today at
  `run_audit.py:71`), returns `{ probe_count, probe_set_hash }`, and persists the
  ordered list.
- `POST /runs` sends `acknowledged_probe_count` **and** `probe_set_hash`; 409 on
  either mismatch (e.g. a profile edited after preview yields a new hash).
- The worker loads the frozen set for `run_id` and runs the lifted per-case logic
  over it.

Therefore `acknowledged_probe_count ≡ executed count` **by construction** (same
object, not two equal numbers). Also makes runs reproducible and gives
`conversations`/`responses` a stable FK to hang off. Cheap now; painful to
retrofit once runs persist, because it changes *what a run is*.

---

## Turn 1 — Architecture diff

### Untouched
`rw_model.py`, `evaluator.py`, `profiles/tax|legal` (logic), `adapters/base.py`.

### Changes, file by file
- **`build_adapter` (`models/llm_client.py`) + key-based adapters:** add explicit
  per-run `credential` injection; remove ambient-env reads (env fallback only for
  local/CLI). `BaseAdapter` unchanged. `HttpAdapter` unchanged — it is the
  credential-free template.
- **`semantic_scorer.py`:** `_embed()` behind an embedder interface; default local
  BGE/E5-small. Math (`_cosine`, `_average_vectors`, `semantic_score`,
  `build_anchors_from_exemplars`) unchanged. Anchors gain `embedder_id` (the
  identity the current code drops).
- **`run_audit.run_audit()`:** the synchronous in-process loop splits into
  **submit** (validate, freeze probe set, persist `run_id` as queued, return) and
  **execute** (worker runs the lifted per-case loop body verbatim). `run_id` keys
  the reproducibility tuple `(project, connection, suite, model-config,
  embedder_id, profile-version, probe_set_hash)`.
- **`collector.py`:** disk JSONL → DB rows (`responses` + `cue_activations`) +
  object-storage blobs, tenant-scoped. Failure classification
  (`lambda >= 0.6 or response_type == "unsafe_help"`) unchanged — sets a column.
- **`app.py` / request models:** `AuditRequest` (flattened, nullable) → run
  lifecycle resources (Projects, Connections × two trust models, Runs). Probe
  count returned before run confirmation.
- **Persistence (absent today):** Postgres + object storage.
- **Reporting (`build_report` / `save_report` / `generate_report_pdf.py`):** logic
  unchanged; re-sourced from DB rows; artifacts → object storage. Recommendations
  LLM call (`run_audit.py:53`, currently VFIED-billed) must move to local model or
  customer key before v1.

### 4-week MVP cut
**The one journey that must work in week 4:** a paying external user creates a
project, connects their own AI (one key-based + one endpoint-based), sees probe
count + cost before confirming, runs a suite async, polls to completion, views it
in a dark dashboard (overview + behaviour map + incident explorer), exports
JSON/PDF.

- Connectors: Anthropic (key-based) + custom endpoint (HTTP).
- Suites: `tax` + `prompt_injection` (the latter is net-new profile content).
- Dashboard: panels **A** (overview), **B** (behaviour map), **D** (incident
  explorer). C (drift) + E (cue) deferred, shown disabled.
- Reporting: JSON + PDF; CSV deferred.

**Deferred to v2:** Gemini/Azure/Botpress/Voiceflow connectors, community library,
leaderboards, regression testing, continuous monitoring, multi-model compare,
Drift Explorer (C), Cue Activity (E), CSV export, `allow_probe_drift`.

**Week plan**

| Week | Steps | Theme |
|---|---|---|
| W1 | 0,1,2 + worker spike | De-risk seams: credentials, local embedder, prove queue/run_id |
| W2 | 3,4,(7 ∥) | Persistence + run-lifecycle API + injection suite |
| W3 | 5,6 | Async worker integration + frontend/reporting |
| W4 | 8 | Integrate, harden, prove journey, delete legacy path |

**3 riskiest assumptions**
1. The async worker boundary is a 1-week spike, not a 4-week tax (front-loaded as a W1 spike).
2. Per-run credential injection is a clean swap (semantic scorer *also* reads env today — Step 2 removes that reader).
3. The frozen engine runs unchanged against live customer models (malformed responses, timeouts via `HttpAdapter._extract`) — validated at W4 against real endpoints.

---

## Turn 2 — Postgres schema (MVP)

Conventions: `uuid` PKs (`gen_random_uuid()`), `created_at timestamptz default now()`,
tenant scoping via `project_id`.

- **`projects`** — tenant root.
- **`connections`** (parent) + **`connection_key_based`** / **`connection_endpoint_based`**
  (class-table inheritance). The secret lives in exactly one child; the endpoint
  child has **no required secret column** — schema enforces the trust-model split.
  - `connection_key_based`: `provider`, `model`, `system_prompt`,
    `api_key_ciphertext bytea` 🔒, `api_key_kms_key_id`, `api_key_last4`.
  - `connection_endpoint_based`: mirrors `HttpAdapter.__init__` — `endpoint`,
    `headers jsonb` 🔒 (**whole blob encrypted, opaque — see DECIDED (a)**),
    `request_field`, `response_path`, `timeout`.
- **`suites`** — `slug`, `profile_version`, `probe_count`. unique(slug, profile_version).
- **`experiment_runs`** — status enum (queued/running/completed/failed/cancelled),
  `probe_count` (snapshot), `probe_set_hash` 🔑 (**freeze invariant**),
  reproducibility fields (`profile_version`, `model_under_test`, `embedder_id`),
  aggregate outputs (`risk_score`, `avg_lambda`, `status_label`, `rw_weights jsonb`
  ← `report["weights"]`), timestamps, sanitized `error`.
- **`run_probes`** 🔑 (**freeze invariant**) — the frozen ordered set:
  `run_id`, `family`, `prompt`, `ordinal`. unique(run_id, ordinal). The worker
  replays this; it is *not* re-expanded from the suite.
- **`conversations`** — `run_id`, `family`, `ordinal` (FK to the frozen set order,
  preserving RW `prev_cues`/`prev_reward` threading). unique(run_id, ordinal).
- **`responses`** — `prompt_text` (VFIED probe, safe), `response_blob_uri`
  (object storage) + `response_preview`, `response_type`, `predicted_risk`,
  `oat_p`, `oat_o`, `semantic_score` (nullable), `lambda`, `is_failure`
  (= collector rule). Indexed on (run_id, is_failure) for panel D.
- **`cue_activations`** — one row per active cue: `response_id`, `run_id`, `cue`,
  `is_configural`, `weight` (CUE_ACTIVITY snapshot). Indexed (run_id, cue).
- **`risk_scores`** — per-family breakdown (`family_summary`): `family`, `count`,
  `avg_lambda`, `is_top_weakness`, `is_top_safe`. unique(run_id, family).
- **`reports`** — `json_uri`, `pdf_uri`, `recommendations jsonb`.
- **`semantic_anchors`** — `project_id`, `embedder_id` 🔑, `unsafe_vec`, `safe_vec`
  (pgvector; jsonb fallback), `sample_count`. unique(project_id, embedder_id) so
  anchors never silently mix embedders.

**Secret columns:** `api_key_ciphertext` (envelope/KMS, decrypted only in worker
JIT, never persisted decrypted/logged/in reports); `headers` (whole blob, same
scheme); `api_key_kms_key_id`/`api_key_last4` (not secret — reference/display).
`response_blob_uri` is sensitive (customer output) but not a credential —
tenant-scoped object storage, never pooled into a shared file (fixes current
global-JSONL leak).

**v2 attach points:** widen key-based `provider` check; endpoint connectors need
no schema change; add `monitors`, `leaderboard_entries`, `community_suites`,
regression baselines on `suites` — none alter MVP tables.

---

## Turn 3 — REST API (`/api/v1`, async throughout)

1. `POST /projects`
2. `POST /projects/{id}/connections` — **discriminated by `kind`**; key-based body
   carries write-only `api_key` (echo `api_key_last4` only); endpoint body mirrors
   `HttpAdapter` (headers never echoed). 422 if fields mixed across kinds.
   `POST /connections/{id}/test` (1 disclosed billed probe).
3. `GET /suites`; `POST /projects/{id}/runs/preview` → freezes the probe set,
   returns `{ probe_count, probe_set_hash, billing_note, embedder_id, cap }`. No
   model call during preview.
4. `POST /projects/{id}/runs` → body `{ connection_id, suite_id,
   acknowledged_probe_count, probe_set_hash }`; 409 on either mismatch; 422 over
   cap (run never created); else 202 `{ run_id, status:"queued", poll }`. Enqueues
   `run_id`.
5. `GET /runs/{id}` — status + `progress {completed_probes, total_probes}`;
   populated aggregates on completion; sanitized `error` on failure.
   `POST /runs/{id}/cancel`.
6. `GET /runs/{id}/results` (panels A+B), `GET /runs/{id}/incidents` (panel D,
   cursor-paginated), `GET /runs/{id}/incidents/{rid}` (full blob, detail drawer).
7. `GET /runs/{id}/report[.pdf|.json]` → signed object-storage URLs. CSV deferred.

**Secret invariants at API layer:** `api_key`/`headers` write-only, never in any
response/results/report/log; run `error` sanitized (e.g. upstream 401 → "upstream
auth failed").

---

## Turn 4 — Next.js page structure (MVP)

App Router; server components fetch, client components only where interactive.
Dark research register; Behaviour is primary (run view titled by *suite + risk
verdict*, model is a secondary chip).

```
app/projects/[projectId]/
  connections/new   → ConnectModelForm (two tabs = two trust models)
  runs/new          → RunLauncher (pick → CostDisclosure gate → confirm)
  runs/[runId]      → OverviewPanel (A) + BehaviourMap (B) + IncidentExplorer (D),
                       driven by RunStatusPoller
```

- Primitives: `RiskBadge`, `LambdaMeter`, `CueChip`, `DataTable`, `Drawer`.
- `CostDisclosure` is a UI hard stop — the confirm button is unreachable without
  rendering the probe count.
- Panels C/E rendered **disabled with "v2" tags** (honest IA, no silent gaps).
- Every rendered number traces to a Turn 2 column → frozen-engine output. Frontend
  computes nothing scientific.

---

## Turn 5 — Migration (strangler; runnable at every step)

| Step | What | Week |
|---|---|---|
| 0 | Pin golden regression baseline (sim + fixture) | W1 |
| 1 | Per-run credential injection in `build_adapter` + key-based adapters (env fallback for CLI) | W1 |
| 2 | Local embedder swap behind `_embed`; stamp `embedder_id` on anchors; re-baseline golden with local embedder | W1 |
| — | Worker spike: queue + worker + `run_id` round-trip vs stub | W1 |
| 3 | Postgres + object storage; `collect()` + `build_report` **dual-write** (DB *and* disk) | W2 |
| 4 | Run-lifecycle API + `preview` (freezes probe set) beside legacy `/audit`; still synchronous under the hood | W2 |
| 7 | Author `profiles/prompt_injection/`; register in loader (parallel, any time after Step 0) | W2/W3 |
| 5 | Extract worker; runs truly async; **worker replays the frozen probe set, never re-expands the suite**; retire serverless run model | W3 |
| 6 | Next.js app (A/B/D + connect/run); `build_report` from DB; PDF→object storage; resolve recommendations LLM call (local/customer key) | W3 |
| 8 | Real Anthropic + real endpoint runs green; secret-leak audit; enforce cap + 409; **stop dual-writing, delete JSONL + disk reports + `/audit`** | W4 |

**Why safe:** smallest-first unblock (1,2); dual-write before cutover (3,4 add DB/API
beside disk/`/audit`, deleted only at 8); risky async cut spiked early (W1) and
integrated late (W3); engine never edited and golden-gated at 2, 5, 8.

**Note vs original Turn 5:** Step 5 corrected — the worker executes the frozen
`run_probes` set for `run_id`, not a re-expansion of `build_prompt_cases`. Suite
expansion happens **once, at preview** (Step 4).

---

## Build status (implemented)

| Step | Status | Evidence |
|---|---|---|
| 0 | ✅ | `tests/golden.py` + `tests/golden_tax.json` (sim, network-free; gates 2/5/8) |
| 1 | ✅ | `build_adapter(config, credential)`; adapters take `api_key`, env fallback |
| 2 | ✅ | `evaluation/embedder.py` (local-first); anchors stamped with `embedder_id` |
| 7 | ✅ | `profiles/prompt_injection/` (9 families, 27 probes) registered in loader |
| 3 | ✅ | `db/` — SQLAlchemy models (Turn 2 schema), crypto envelope stub, object store |
| 4 | ✅ | `services/{probe_set,connections,runs}.py` + v1 API in `app.py`; freeze + 409 gate verified |
| 5 | ✅ | `worker.py` replays frozen `run_probes`; `run_audit.score_one_case` lifted; golden still green |
| 6 | ✅ | `web/` Next.js (dark theme, panels A/B/D, two-trust-model flow, cost gate); `tsc --noEmit` clean |
| 8 | ◐ | `tests/test_secret_leak.py` PASSES; **dual-write deletion + `/audit` removal pending real-endpoint validation** |

### Dev fallbacks (production swaps, interface unchanged)
- **DB:** SQLite (`vfied.db`) ← `DATABASE_URL=postgresql+psycopg://…`
- **Embedder:** `HashingEmbedder` (no heavy install) ← `sentence-transformers` (`local:BAAI/bge-small-en-v1.5`)
- **Crypto:** keyed-HMAC stub in `db/crypto.py` ← KMS envelope encryption
- **Object store:** filesystem `_objectstore/` ← S3/GCS
- **Queue:** in-process thread in `worker.enqueue` ← Redis/SQS + separate worker process

### Step 8 remaining (manual gate — needs live credentials, cannot run in dev)
1. Run a real Anthropic key-based run + a real custom-endpoint run; both green end-to-end.
2. Re-run `tests/test_secret_leak.py` against the real-connection runs.
3. THEN, and only then: remove the JSONL append from `collector.py`, drop the
   `reports/*.json` disk write, and delete the legacy `POST /audit` route.
   (Until then the dual-write fallback is intentional, per the strangler plan.)

Cost cap (`services/runs.PROBE_CAP = 100`) and the `acknowledged_probe_count` +
`probe_set_hash` 409 gate are enforced now.
