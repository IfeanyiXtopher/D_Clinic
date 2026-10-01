import type { Dispatch, RefObject, SetStateAction } from "react";
import { Link, type SetURLSearchParams } from "react-router-dom";
import type { SmsOut, Thread } from "../api";

const CALLBACK: Record<string, string> = {
  medical_callback: "Call the patient — they reported a symptom or asked for medical advice.",
  wrong_number: "Wrong number — stop messages to this line and check the register.",
  handoff: "Call the patient — the bot could not finish the booking.",
};

const LANG: Record<string, string> = {
  en: "English", pcm: "Pidgin", ha: "Hausa", yo: "Yoruba",
};

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "Time not recorded";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

type HistoryRow = {
  at: string | null;
  kind: string;
  title: string;
  detail: string;
  tone?: "agree" | "later" | "remove";
};

export function SimpleChat({
  patientId, setPatientId, setParams, asOf, setAsOf, thread, last, draft, setDraft,
  err, busy, showHistory, setShowHistory, scroller, caseId,
  startReminder, send, sendText, openTasks, brief, n, history,
}: {
  patientId: string;
  setPatientId: (id: string) => void;
  setParams: SetURLSearchParams;
  asOf: string;
  setAsOf: (d: string) => void;
  thread: Thread | null;
  last: SmsOut | null;
  draft: string;
  setDraft: (v: string) => void;
  err: string;
  busy: "remind" | "send" | null;
  showHistory: boolean;
  setShowHistory: Dispatch<SetStateAction<boolean>>;
  scroller: RefObject<HTMLDivElement | null>;
  caseId: string;
  startReminder: () => void;
  send: () => void;
  sendText: (text: string) => void;
  openTasks: { id: string; kind: string; status: string }[];
  brief: { title: string; body: string; tone: "ok" | "warn" | "idle" };
  n: number;
  history: HistoryRow[];
}) {
  return (
    <section className="s-page">
      <header className="s-pagehead">
        <p className="s-crumb">
          <Link to="/">Follow-up list</Link>
          {patientId ? <> / <Link to={`/patients/${patientId}?as_of=${asOf}`}>Case {caseId}</Link></> : null}
          {" "}/ SMS
        </p>
        <div className="s-pagehead-main">
          <h1>SMS thread</h1>
          <p>You type as the patient. This is the clinic view of their handset.</p>
        </div>
        <div className="s-pagehead-side">
          <span className="s-meta">Case {caseId} · {asOf}</span>
          {patientId ? <Link className="s-link" to={`/patients/${patientId}?as_of=${asOf}`}>Open briefing</Link> : null}
        </div>
      </header>

      <div className="s-toolbar">
        <label className="s-field grow">
          Case
          <input value={patientId} spellCheck={false} onChange={(e) => { setPatientId(e.target.value); setParams({ patient_id: e.target.value }); }} />
        </label>
        <label className="s-field">
          As-of
          <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </label>
        <button type="button" className="s-btn on" onClick={() => void startReminder()} disabled={!!busy || !patientId}>
          {busy === "remind" ? "Sending…" : "Send reminder"}
        </button>
      </div>
      {err ? <p className="err">{err}</p> : null}

      <div className="s-split sms">
        <div className="s-handset">
          <div className="s-bezel">
            <div className="s-ear" aria-hidden />
            <div className="s-screen">
              <div className="s-thread-bar">
                <strong>Clinic SMS</strong>
                <span>Case {caseId}</span>
              </div>
              <div className="s-bubbles" ref={scroller}>
                {(thread?.messages ?? []).map((m, i) => (
                  <div key={i} className={`s-msg ${m.direction === "outbound" ? "out" : "in"}`}>
                    <div className="s-bubble">{m.body}</div>
                    <time dateTime={m.at ?? undefined}>{formatWhen(m.at)}</time>
                  </div>
                ))}
                {!n ? <p className="s-empty">No messages yet. Send a reminder to start.</p> : null}
              </div>
              <div className="s-tries">
                {["I will come", "Wed 30 is fine", "STOP", "my head is paining"].map((phrase) => (
                  <button
                    key={phrase}
                    type="button"
                    className="s-btn"
                    disabled={!!busy || !patientId}
                    onClick={() => void sendText(phrase)}
                  >
                    {phrase}
                  </button>
                ))}
              </div>
              <div className="s-composer">
                <input
                  value={draft}
                  placeholder="Type as the patient…"
                  disabled={!!busy || !patientId}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") void send(); }}
                />
                <button type="button" className="s-btn on" onClick={() => void send()} disabled={!!busy || !draft.trim()}>
                  {busy === "send" ? "…" : "Send"}
                </button>
              </div>
              <div className="s-home" aria-hidden />
            </div>
          </div>
        </div>

        <div className="s-stack">
          <article className="s-card">
            <div className="s-card-top">
              <h2>Last action</h2>
              <span className={`s-pill ${brief.tone === "ok" ? "ok" : brief.tone === "warn" ? "warn" : ""}`}>{brief.title}</span>
            </div>
            <p>{brief.body}</p>
            {last && last.intent !== "reminder" ? (
              <p className="s-meta">
                {LANG[last.language] ?? last.language}
                {last.nlu_source === "llm" ? " · read as ordinary wording" : " · read as a short reply"}
              </p>
            ) : null}
          </article>
          <article className="s-card">
            <div className="s-card-top">
              <h2>Worker callbacks</h2>
              <span className="s-pill">{openTasks.length}</span>
            </div>
            <p className="s-meta">Only when the line must stop — a symptom, a wrong number, or a stuck booking.</p>
            {openTasks.length ? (
              <ul className="s-callbacks">
                {openTasks.map((t) => <li key={t.id}>{CALLBACK[t.kind] ?? t.kind}</li>)}
              </ul>
            ) : <p className="s-last">Clear. Nothing for a worker to chase.</p>}
          </article>
        </div>
      </div>

      <div className="s-card s-history">
        <button type="button" className="s-btn" onClick={() => setShowHistory((v) => !v)} aria-expanded={showHistory}>
          {showHistory ? "Hide history" : "Show history"} · {history.length} events
        </button>
        {showHistory ? (
          history.length ? (
            <ol>
              {history.map((row, i) => (
                <li key={`${row.kind}-${row.at}-${i}`}>
                  <div className="s-card-top">
                    <span className="s-pill">{row.kind}</span>
                    <time className="s-meta">{formatWhen(row.at)}</time>
                  </div>
                  <strong className={row.tone ? `call-${row.tone}` : ""}>
                    {row.tone ? <span className={`s-dot ${row.tone}`} aria-hidden /> : null}
                    {row.title}
                  </strong>
                  <p className="s-meta">{row.detail}</p>
                </li>
              ))}
            </ol>
          ) : <p className="s-empty">No calls or messages on this case yet.</p>
        ) : null}
      </div>
    </section>
  );
}
