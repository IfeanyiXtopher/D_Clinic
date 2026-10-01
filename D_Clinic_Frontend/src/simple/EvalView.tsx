import type { ReactNode } from "react";
import type { EvalCard, EvalReport, Registry } from "../api";

const MODEL_NAME: Record<string, string> = {
  missed_visit_risk: "Missed-visit risk",
  sms_intent: "SMS understanding",
  worker_summary: "Briefing check",
};

const MODEL_VERSION: Record<string, string> = {
  template: "summary_v1",
};

const METRIC_NAME: Record<string, string> = {
  test_auc: "AUC",
  lift_at_30: "Lift at 30%",
  ece: "Calibration (ECE)",
  rules_accuracy: "Phrase-rules accuracy",
  tfidf_accuracy: "Backup classifier",
  factuality: "Factuality",
  pii_rate: "Identity leak rate",
};

const HEADLINE: Record<string, string> = {
  worklist: "Risk ranking yields 20.9 extra returns per 100 calls versus 18.2 for longest-overdue-first (+15%). The worker still decides who to call.",
  missed_visit_model: "The score only ranks the list. Ethnicity and region are never features. A high score never removes anyone from care.",
  summary: "Every briefing is checked against the record. An invented number or drug is not shown. Staff rate useful, missing fact, or wrong number.",
  chatbot: "The patient can confirm or move a visit by SMS. Code books the day. A symptom opens a worker callback. No medical advice on the line.",
  reckoner: "Protocol answers are quoted from HEARTS / PHC text. Out-of-scope questions are refused. An invented dose is dropped.",
  drift: "Operators watch whether risk scores shift week to week. An alert is a review, not an automatic change to who gets called.",
};

const PROCESS = [
  { title: "Daily follow-up list", body: "The worker sees a ranked call list. The score suggests who to try first. It never drops a patient. Agreed-to-visit and call-later are recorded by the worker." },
  { title: "Patient briefing", body: "Structured facts sit above the five-line summary. Numbers and drugs must match the record. The worker rates the briefing; that rating is logged and does not change the chart." },
  { title: "SMS scheduling", body: "The clinic sends a reminder. The patient replies in ordinary language. The system books only an open clinic day. STOP opts out. A symptom creates a callback, not advice." },
  { title: "Protocol desk", body: "Staff look up HEARTS / PHC text. The answer is cited. Questions this pack does not cover are refused. The tool does not prescribe." },
];

function prettyMetric(key: string, value: number): string {
  const label = METRIC_NAME[key] ?? key.replaceAll("_", " ");
  const n = Number(value);
  if (key.includes("rate") || key.includes("accuracy") || key === "factuality") {
    return `${label} ${n <= 1 ? `${Math.round(n * 100)}%` : n}`;
  }
  return `${label} ${Number.isInteger(n) ? n : n.toFixed(n < 1 ? 3 : 2)}`;
}

export function SimpleEval({
  cards, reg, open, loading, err, toggle, report,
}: {
  cards: EvalCard[];
  reg: Registry | null;
  open: EvalReport | null;
  loading: string | null;
  err: string;
  toggle: (id: string) => void;
  report: (body: string) => ReactNode;
}) {
  return (
    <section className="s-page">
      <header className="s-pagehead">
        <div className="s-pagehead-main">
          <h1>Evaluation</h1>
          <p>How the program is run and checked, measured on the synthetic cohort.</p>
        </div>
      </header>
      {err ? <p className="err">{err}</p> : null}

      <h2 className="s-section">Operating process</h2>
      <div className="s-grid two">
        {PROCESS.map((p) => (
          <article key={p.title} className="s-card">
            <h2>{p.title}</h2>
            <p>{p.body}</p>
          </article>
        ))}
      </div>

      <h2 className="s-section">What is checked</h2>
      <div className="s-grid three">
        {(reg?.models ?? []).map((m) => (
          <article key={m.name} className="s-card">
            <div className="s-card-top">
              <h2>{MODEL_NAME[m.name] ?? m.name.replaceAll("_", " ")}</h2>
              <span className="s-pill ok">{m.stage}</span>
            </div>
            <p className="s-meta">{MODEL_VERSION[m.version] ?? m.version}</p>
            <p className="s-metrics">
              {Object.entries(m.metrics || {}).map(([k, v]) => prettyMetric(k, v)).join(" · ")}
            </p>
          </article>
        ))}
      </div>

      <h2 className="s-section">Measured results</h2>
      <div className="s-stack">
        {cards.map((c) => (
          <article key={c.id} className={`s-card ${open?.id === c.id ? "open" : ""}`}>
            <div className="s-card-top">
              <h2>{c.title}</h2>
              <button type="button" className={`s-btn ${open?.id === c.id ? "on" : ""}`} disabled={loading === c.id} onClick={() => void toggle(c.id)}>
                {loading === c.id ? "Loading…" : open?.id === c.id ? "Close" : "Read"}
              </button>
            </div>
            <p>{HEADLINE[c.id] ?? c.headline}</p>
            {open?.id === c.id ? report(open.body) : null}
          </article>
        ))}
      </div>
    </section>
  );
}
