import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { shortId, type NextStep, type ReckonerAsk, type Summary } from "../api";
import { Sparkline } from "../components/Sparkline";
import { Tip } from "../components/Tip";
const RECKONER_PROMPTS = [
  { label: "First-line drug", q: "What is the first protocol drug if not yet on treatment?" },
  { label: "Amlodipine step 1", q: "What dose of amlodipine is step 1?" },
  { label: "Control target", q: "When is BP considered controlled?" },
  { label: "Missed tablet", q: "Patient missed yesterday's tablet. Double today's dose?" },
  { label: "Pregnancy", q: "Pregnant woman with high BP. Use the ladder?" },
  { label: "When to refer", q: "When do we refer for hypertension?" },
];

const RATINGS = [
  { id: "useful", label: "Useful", tone: "agree" },
  { id: "missing_fact", label: "Missing fact", tone: "later" },
  { id: "wrong_number", label: "Wrong number", tone: "remove" },
] as const;

const BASIS: Record<string, string> = {
  personal: "Own history",
  mixed: "Mixed history",
  group: "Group estimate",
};

const BASIS_TIP: Record<string, string> = {
  personal: "Enough of this patient’s own visits to score them directly.",
  mixed: "Own history blended with similar patients.",
  group: "Almost no history. Group estimate (same facility, diabetes, drugs, age) — not “this person will miss.”",
};

function QuestionMenu({
  value, disabled, onPick,
}: {
  value: string;
  disabled: boolean;
  onPick: (question: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const chosen = RECKONER_PROMPTS.find((row) => row.q === value);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <div className="s-menu s-qmenu" ref={wrap}>
      <span className="s-field-label">Suggested question</span>
      <button
        type="button"
        className={`s-menu-btn ${open ? "open" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <span>{chosen?.label ?? "Choose a protocol question"}</span>
        <span className="s-menu-chevron" aria-hidden>▾</span>
      </button>
      {open ? (
        <ul className="s-menu-list" role="listbox">
          {RECKONER_PROMPTS.map((row) => (
            <li key={row.label}>
              <button
                type="button"
                role="option"
                aria-selected={row.q === value}
                className={row.q === value ? "on" : ""}
                onClick={() => {
                  setOpen(false);
                  onPick(row.q);
                }}
              >
                <strong>{row.label}</strong>
                <span>{row.q}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function callTone(result?: string) {
  const v = (result || "").toLowerCase();
  if (v.includes("agreed")) return "agree";
  if (v.includes("later") || v.includes("remind")) return "later";
  if (v.includes("remov") || v.includes("skip")) return "skip";
  return "";
}

function prettyStatus(value?: string) {
  return (value || "").replaceAll("_", " ") || "—";
}

function attStr(att: Record<string, unknown> | undefined, key: string): string | null {
  const v = att?.[key];
  if (v == null) return null;
  return String(v);
}

export function SimplePatient({
  id, asOf, sum, err, q, setQ, ask, asking, askErr, rating, ratingBusy, step, rate, askProtocol,
}: {
  id: string;
  asOf: string;
  sum: Summary | null;
  err: string;
  q: string;
  setQ: (v: string) => void;
  ask: ReckonerAsk | null;
  asking: boolean;
  askErr: string;
  rating: string | null;
  ratingBusy: boolean;
  step: NextStep | null;
  rate: (verdict: string) => void;
  askProtocol: (question?: string) => void;
}) {
  const facts = sum?.facts;
  const att = facts?.attendance;
  const lastBp = facts?.last_bp;
  const drugs = facts?.drugs ?? [];
  const high = facts?.risk?.band === "high";

  return (
    <section className="s-page">
      <header className="s-pagehead">
        <p className="s-crumb"><Link to="/">Follow-up list</Link> / Case {id ? shortId(id) : "—"}</p>
        <div className="s-pagehead-main">
          <h1>Case {id ? shortId(id) : "—"}</h1>
          <p>Case stub only. No name or phone. Facts first. The summary is checked against them.</p>
        </div>
        <div className="s-pagehead-side">
          {high ? (
            <Tip tip="Top 20% of training scores — most likely to miss the next visit.">
              <span className="s-risk">High risk</span>
            </Tip>
          ) : null}
          <span className="s-meta">As of {asOf}</span>
          <Link className="s-phone" to={`/chat?patient_id=${id}`}>SMS thread</Link>
        </div>
      </header>
      {err ? <p className="err">{err}</p> : null}
      {!sum ? <p className="s-empty">Loading briefing…</p> : (
        <div className="s-split">
          <div className="s-stack">
            <article className="s-card">
              <div className="s-card-top">
                <div>
                  <p className="s-kicker">{sum.case_code}</p>
                  <h2>{facts?.age_band} · {facts?.sex}</h2>
                  <div className="s-chips">
                    {(facts?.conditions ?? []).map((c) => (
                      <span className="s-chip" key={c}>{c}</span>
                    ))}
                    <span className="s-chip">{prettyStatus(facts?.program_status)}</span>
                    {facts?.risk?.basis ? (
                      <Tip tip={BASIS_TIP[facts.risk.basis] ?? "How much personal history the score used."}>
                        <span className="s-chip">{BASIS[facts.risk.basis] ?? facts.risk.basis}</span>
                      </Tip>
                    ) : null}
                  </div>
                </div>
              </div>
              <p className="s-brief">{sum.summary}</p>
              <div className="s-chips">
                <Tip tip={sum.fallback_used || sum.source === "template"
                  ? "The briefing was filled from the record template."
                  : "A model wrote this briefing. It was still checked against the record."}>
                  <span className={`s-chip ${sum.source === "template" || sum.fallback_used ? "warn" : ""}`}>
                    {sum.fallback_used ? "Fell back to template" : sum.source === "template" ? "Template" : "Model"}
                  </span>
                </Tip>
                <Tip tip="Every number and drug in the briefing is checked against the chart. A failed check is not shown as fact.">
                  <span className={`s-chip ${sum.check === "passed" ? "ok" : "warn"}`}>
                    {sum.check === "passed" ? "Check passed" : prettyStatus(sum.check)}
                  </span>
                </Tip>
                <span className="s-chip">{sum.prompt_version}</span>
                <span className="s-chip">{sum.model_version}</span>
              </div>
              <div className="s-rating">
                <p className="s-kicker">Staff rating · required</p>
                <p className="s-meta">Does this briefing match the facts? Logged for review. It does not change the record.</p>
                <div className="s-actions">
                  {RATINGS.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      className={`s-btn ${r.tone} ${rating === r.id ? "on" : ""}`}
                      aria-pressed={rating === r.id}
                      disabled={ratingBusy}
                      onClick={() => void rate(r.id)}
                    >
                      {r.label}
                    </button>
                  ))}
                </div>
                <p className="s-recorded">
                  {rating
                    ? `On file — ${RATINGS.find((r) => r.id === rating)?.label.toLowerCase()}.`
                    : "Not rated yet."}
                </p>
              </div>
            </article>

            <div className="s-stats">
              <div>
                <Tip tip="Latest clinic blood pressure. Goal is under 140/90.">
                  <span>Latest BP</span>
                </Tip>
                <strong className={lastBp && !lastBp.controlled ? "bad" : ""}>
                  {lastBp ? `${lastBp.systolic}/${lastBp.diastolic}` : "—"}
                </strong>
                <em>{lastBp ? (lastBp.controlled ? "At 140/90" : "Above 140/90") : "No reading"}</em>
              </div>
              <div>
                <Tip tip="Medicines on the chart. The protocol next step uses this list.">
                  <span>Drugs on record</span>
                </Tip>
                <strong>{drugs.length || "None"}</strong>
                <em>{drugs[0]?.name ?? "Not yet on treatment"}</em>
              </div>
              <div>
                <Tip tip="Visits and missed visits in the last 12 months.">
                  <span>Visits / missed</span>
                </Tip>
                <strong>{attStr(att, "visits_12m") ?? "—"} / {attStr(att, "missed_12m") ?? "—"}</strong>
                <em>{attStr(att, "last_visit") ? `Last visit ${attStr(att, "last_visit")}` : "No visit history"}</em>
              </div>
              <div>
                <Tip tip="Days since the scheduled visit with no blood pressure recorded.">
                  <span>Follow-up</span>
                </Tip>
                <strong>{attStr(att, "days_overdue") && attStr(att, "days_overdue") !== "None" ? `${attStr(att, "days_overdue")}d` : "—"}</strong>
                <em>
                  {facts?.last_call ? (
                    <>
                      {callTone(facts.last_call.result) ? (
                        <span className={`s-dot ${callTone(facts.last_call.result)}`} aria-hidden />
                      ) : null}
                      {prettyStatus(facts.last_call.result)} · {facts.last_call.when}
                    </>
                  ) : "No last call"}
                </em>
              </div>
            </div>

            <article className="s-card">
              <div className="s-card-top">
                <h2>Blood pressure</h2>
                {lastBp ? (
                  <span className={`s-pill ${lastBp.controlled ? "ok" : "warn"}`}>
                    {lastBp.controlled ? "At goal" : "Above goal"}
                  </span>
                ) : null}
              </div>
              <Sparkline points={facts?.bp_history ?? []} />
              <p className="s-meta">
                {lastBp ? `Latest ${lastBp.systolic}/${lastBp.diastolic} · ${lastBp.when} · goal 140/90` : "No clinic readings in this packet."}
              </p>
            </article>

            <article className="s-card">
              <h2>Drugs on record</h2>
              {drugs.length ? (
                <div className="s-table-wrap">
                  <table className="s-table">
                    <thead>
                      <tr><th>Drug</th><th>Dose</th><th>Frequency</th></tr>
                    </thead>
                    <tbody>
                      {drugs.map((d) => (
                        <tr key={`${d.name}-${d.dosage}`}>
                          <td>{d.name}</td>
                          <td>{d.dosage || "—"}</td>
                          <td>{d.frequency || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className="s-empty">None recorded.</p>}
            </article>
          </div>

          <aside className="s-stack">
            <article className="s-card">
              <p className="s-kicker">This case</p>
              <h2>Protocol next step</h2>
              {step ? (
                <>
                  <p>{step.guidance}</p>
                  <div className="s-chips">
                    <span className="s-chip">{prettyStatus(step.action)}</span>
                    {step.next_regimen ? <span className="s-chip">{step.next_regimen}</span> : null}
                    {step.cite ? <span className="s-chip">{step.cite}</span> : null}
                  </div>
                </>
              ) : <p className="s-empty">No next step yet.</p>}
            </article>
            <article className="s-card">
              <p className="s-kicker">Protocol desk</p>
              <h2>Protocol Q&amp;A</h2>
              <p className="s-meta">Looks up WHO HEARTS / PHC and quotes it. Questions this pack does not cover are refused.</p>
              <QuestionMenu
                value={RECKONER_PROMPTS.some((p) => p.q === q) ? q : ""}
                disabled={asking}
                onPick={(next) => void askProtocol(next)}
              />
              <div className="s-ask">
                <label>
                  Or type your own
                  <input
                    value={q}
                    placeholder="e.g. When do we add chlorthalidone?"
                    disabled={asking}
                    onChange={(e) => setQ(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") void askProtocol(); }}
                  />
                </label>
                <button type="button" className="s-btn on" onClick={() => void askProtocol()} disabled={asking || q.trim().length < 3}>
                  {asking ? "Looking up…" : "Ask"}
                </button>
              </div>
              {askErr ? <p className="err">{askErr}</p> : null}
              {ask ? (
                <div className={`s-answer ${ask.refused ? "refused" : ""}`}>
                  <p className="s-kicker">{ask.refused ? "Not in this protocol" : "Quoted from the pack"}</p>
                  <p>{ask.answer}</p>
                  <p className="s-meta">
                    {ask.refused
                      ? "Refused — use the appropriate guideline or ask a clinician."
                      : ask.citations.map((c) => c.id).join(", ") || ask.source}
                  </p>
                </div>
              ) : <p className="s-meta">Choose a suggested question, or type one in HEARTS / PHC scope.</p>}
            </article>
          </aside>
        </div>
      )}
    </section>
  );
}
