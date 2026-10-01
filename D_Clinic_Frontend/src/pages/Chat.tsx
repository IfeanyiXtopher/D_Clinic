import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, shortId, type SmsOut, type Thread } from "../api";
import { SimpleChat } from "../simple/ChatView";

const CALLBACK: Record<string, string> = {
  medical_callback: "Call the patient — they reported a symptom or asked for medical advice.",
  wrong_number: "Wrong number — stop messages to this line and check the register.",
  handoff: "Call the patient — the bot could not finish the booking.",
};

const CALL_LABEL: Record<string, string> = {
  agreed_to_visit: "Agreed to visit",
  remind_to_call_later: "Call later",
  removed_from_overdue_list: "Removed from overdue list",
};

function waitingLine(state: string): string {
  switch (state) {
    case "confirming":
      return "Waiting for a reply: they can keep this visit, ask for another day, or opt out.";
    case "choosing_slot":
      return "Three clinic days were offered. Waiting for them to pick one — a number or words such as “Wed 30 is fine”.";
    case "rescheduling":
      return "Waiting for yes or no on the new day.";
    case "cancelling":
      return "Waiting for yes or no on cancelling the visit.";
    case "handoff":
      return "The bot stopped. A worker should call.";
    default:
      return "Nothing pending on this turn.";
  }
}

function staffBrief(last: SmsOut | null, hasThread: boolean): { title: string; body: string; tone: "ok" | "warn" | "idle" } {
  if (!last) {
    if (hasThread) {
      return {
        title: "Thread on file",
        body: "Older messages are already in the phone. Send a reminder or type as the patient to see what this turn did.",
        tone: "idle",
      };
    }
    return {
      title: "Not started",
      body: "Send a reminder first. The phone shows what the patient receives; this panel explains the last action.",
      tone: "idle",
    };
  }

  if (last.intent === "reminder" || (last.intent === "unknown" && last.state === "confirming" && !last.task_completed)) {
    return {
      title: "Reminder sent",
      body: "The clinic asked them to confirm the visit. They can write normally — they do not have to type 1 or 2.",
      tone: "ok",
    };
  }
  if (last.task_completed === "confirmed") {
    return { title: "Visit confirmed", body: "They said they will come. The appointment is marked agreed. No worker callback.", tone: "ok" };
  }
  if (last.task_completed === "rescheduled") {
    return { title: "Visit moved", body: "A new clinic day was written on the record. The phone has the date.", tone: "ok" };
  }
  if (last.task_completed === "cancelled") {
    return { title: "Visit cancelled", body: "That appointment is closed. A worker can book again if needed.", tone: "warn" };
  }
  if (last.task_completed === "stopped") {
    return { title: "Opted out", body: "They asked to stop clinic messages. Consent is denied.", tone: "warn" };
  }
  if (last.staff_task === "medical_callback" || last.intent === "symptom_or_medical") {
    return {
      title: "Needs a callback",
      body: "They mentioned a symptom or asked for medical advice. This line does not treat. A callback is on the list below.",
      tone: "warn",
    };
  }
  if (last.staff_task === "wrong_number" || last.intent === "wrong_number") {
    return { title: "Wrong number", body: "They said this is not their line. Messages should stop. Check the register.", tone: "warn" };
  }
  if (last.intent === "reschedule" || last.intent === "ask_slot") {
    return { title: "Asked for another day", body: waitingLine(last.state), tone: "ok" };
  }
  if (last.intent === "confirm") {
    return { title: "They replied", body: waitingLine(last.state), tone: "ok" };
  }
  return { title: "Last reply read", body: waitingLine(last.state), tone: "idle" };
}

export function ChatPage() {
  const [params, setParams] = useSearchParams();
  const [patientId, setPatientId] = useState(params.get("patient_id") || "");
  const [asOf, setAsOf] = useState("2026-09-26");
  const [thread, setThread] = useState<Thread | null>(null);
  const [last, setLast] = useState<SmsOut | null>(null);
  const [draft, setDraft] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<"remind" | "send" | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const caseId = patientId ? shortId(patientId) : "—";

  useEffect(() => {
    api.demo().then((c) => {
      setAsOf(c.sms_as_of);
      if (!patientId && c.chat_patient_id) {
        setPatientId(c.chat_patient_id);
        setParams({ patient_id: c.chat_patient_id }, { replace: true });
      }
    }).catch((e: Error) => setErr(e.message));
  }, []);

  async function refresh(pid = patientId) {
    if (!pid) return;
    setThread(await api.thread(pid));
  }

  useEffect(() => {
    if (patientId) void refresh(patientId).catch((e: Error) => setErr(e.message));
  }, [patientId]);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [thread?.messages]);

  async function startReminder() {
    if (!patientId || busy) return;
    setErr("");
    setBusy("remind");
    try {
      const out = await api.reminder(patientId, asOf);
      setLast(out);
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function sendText(text: string) {
    const body = text.trim();
    if (!body || busy) return;
    setErr("");
    setBusy("send");
    try {
      const out = await api.inbound(patientId, body, asOf, last?.session_id);
      setLast(out);
      setDraft("");
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function send() {
    await sendText(draft);
  }

  const openTasks = (thread?.staff_tasks ?? []).filter((t) => t.status === "open");
  const brief = staffBrief(last, Boolean(thread?.messages.length));
  const n = thread?.messages.length ?? 0;
  const history: {
    at: string | null;
    kind: string;
    title: string;
    detail: string;
    tone?: "agree" | "later" | "remove";
  }[] = [
    ...(thread?.messages ?? []).map((m) => ({
      at: m.at,
      kind: m.direction === "outbound" ? "SMS out" : "SMS in",
      title: m.direction === "outbound" ? "Clinic SMS" : "Patient SMS",
      detail: m.body || "—",
    })),
    ...(thread?.calls ?? []).map((c) => ({
      at: c.at,
      kind: "Call",
      tone: c.result_type === "agreed_to_visit" ? "agree" as const
        : c.result_type === "remind_to_call_later" ? "later" as const
        : c.result_type === "removed_from_overdue_list" ? "remove" as const
        : undefined,
      title: CALL_LABEL[c.result_type] ?? c.result_type.replaceAll("_", " "),
      detail: c.remove_reason ? c.remove_reason.replaceAll("_", " ") : "Worklist call result",
    })),
    ...(thread?.staff_tasks ?? []).map((t) => ({
      at: t.at ?? null,
      kind: "Callback",
      title: CALLBACK[t.kind]?.split(" — ")[0] ?? t.kind.replaceAll("_", " "),
      detail: t.status === "open" ? "Open" : t.status,
    })),
  ].sort((a, b) => {
    const ta = a.at ? new Date(a.at).getTime() : 0;
    const tb = b.at ? new Date(b.at).getTime() : 0;
    return tb - ta;
  });

  return (
    <SimpleChat
      patientId={patientId}
      setPatientId={setPatientId}
      setParams={setParams}
      asOf={asOf}
      setAsOf={setAsOf}
      thread={thread}
      last={last}
      draft={draft}
      setDraft={setDraft}
      err={err}
      busy={busy}
      showHistory={showHistory}
      setShowHistory={setShowHistory}
      scroller={scroller}
      caseId={caseId}
      startReminder={startReminder}
      send={send}
      sendText={sendText}
      openTasks={openTasks}
      brief={brief}
      n={n}
      history={history}
    />
  );
}
