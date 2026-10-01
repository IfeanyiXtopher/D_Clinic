const BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (r.status === 204) return undefined as T;
  const text = await r.text();
  if (!r.ok) throw new Error(text.slice(0, 240) || r.statusText);
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export type Facility = { id: string; name: string; facility_type: string | null; district: string | null };

export type WorklistItem = {
  id: string;
  list_type: string;
  rank: number;
  patient_id: string;
  appointment_id: string;
  days_overdue: number;
  p_missed: number | null;
  band: string | null;
  basis: string | null;
  uncontrolled: boolean;
  protected_slot: boolean;
  has_phone: boolean;
  suggested_action: string;
  reasons: string[];
  status: string;
  call_result_id: string | null;
  last_interaction?: string | null;
  last_interaction_at?: string | null;
};

export type Worklist = {
  facility_id: string;
  list_date: string;
  overdue: WorklistItem[];
  pre_visit: WorklistItem[];
  counts: Record<string, number>;
};

export type Summary = {
  patient_id: string;
  case_code: string;
  facts: {
    age_band?: string;
    sex?: string;
    conditions?: string[];
    last_bp?: { systolic: number; diastolic: number; when: string; controlled: boolean } | null;
    bp_history?: { systolic: number; diastolic: number; when: string; controlled: boolean }[];
    drugs?: { name: string; dosage: string; frequency: string }[];
    attendance?: Record<string, unknown>;
    last_call?: { result: string; when: string } | null;
    risk?: { band: string; basis: string; reasons: string[] } | null;
    program_status?: string;
    suggested_next_step?: string;
  };
  summary: string;
  source: string;
  check: string;
  provider: string;
  model: string | null;
  prompt_version: string;
  model_version: string;
  fallback_used: boolean;
  packet_hash: string;
};

export type SmsOut = {
  reply: string;
  session_id: string;
  state: string;
  intent: string;
  language: string;
  task_completed: string | null;
  staff_task: string | null;
  patient_id: string | null;
  nlu_source: string;
};

export type Thread = {
  patient_id: string;
  messages: { direction: string; body: string; language: string | null; communication_type: string; at: string | null }[];
  calls: { result_type: string; remove_reason: string | null; at: string | null }[];
  staff_tasks: { id: string; kind: string; status: string; at?: string | null }[];
};

export type ReckonerAsk = {
  question: string;
  answer: string;
  refused: boolean;
  covered: boolean;
  citations: { id: string; title: string; source: string; score: number }[];
  source: string;
  check: string;
  fallback_used: boolean;
};

export type NextStep = {
  controlled: boolean | null;
  current_step: number | null;
  action: string;
  guidance: string;
  cite: string | null;
  next_regimen: string | null;
};

export type EvalCard = { id: string; title: string; headline: string };
export type EvalReport = EvalCard & { body: string };
export type Registry = {
  updated_at: string;
  models: { name: string; version: string; stage: string; prompt_version: string | null; metrics: Record<string, number> }[];
};

export type DemoContext = {
  worklist_as_of: string;
  sms_as_of: string;
  facilities: Facility[];
  chat_patient_id: string | null;
};

export const api = {
  demo: () => req<DemoContext>("/demo/context"),
  facilities: () => req<Facility[]>("/facilities"),
  worklist: (facilityId: string, date: string, rebuild = false) =>
    req<Worklist>(`/worklist?facility_id=${facilityId}&date=${date}${rebuild ? "&rebuild=true" : ""}`),
  callResult: (appointmentId: string, resultType: string, extra: Record<string, string> = {}) =>
    req("/call-results", { method: "POST", body: JSON.stringify({ appointment_id: appointmentId, result_type: resultType, ...extra }) }),
  skip: (itemId: string) => req<void>(`/worklist/items/${itemId}/skip`, { method: "POST" }),
  summary: (patientId: string, asOf: string) =>
    req<Summary>(`/patients/${patientId}/summary`, { method: "POST", body: JSON.stringify({ as_of: asOf }) }),
  feedback: (patientId: string, verdict: string, caseCode?: string) =>
    req<{ verdict: string; case_code: string | null; rated_at: string | null }>(
      `/patients/${patientId}/feedback`,
      { method: "POST", body: JSON.stringify({ verdict, case_code: caseCode }) },
    ),
  lastFeedback: (patientId: string) =>
    req<{ verdict: string | null; case_code: string | null; rated_at: string | null }>(
      `/patients/${patientId}/feedback`,
    ),
  ask: (question: string) => req<ReckonerAsk>("/reckoner/ask", { method: "POST", body: JSON.stringify({ question }) }),
  nextStep: (systolic: number | null, diastolic: number | null, drugs: { name: string; dosage?: string }[]) =>
    req<NextStep>("/reckoner/next-step", { method: "POST", body: JSON.stringify({ systolic, diastolic, drugs }) }),
  reminder: (patientId: string, asOf: string) =>
    req<SmsOut>("/sms/outbound", { method: "POST", body: JSON.stringify({ patient_id: patientId, as_of: asOf }) }),
  inbound: (patientId: string, body: string, asOf: string, sessionId?: string) =>
    req<SmsOut>("/sms/inbound", {
      method: "POST",
      body: JSON.stringify({ patient_id: patientId, body, as_of: asOf, session_id: sessionId }),
    }),
  thread: (patientId: string) => req<Thread>(`/sms/threads/${patientId}`),
  reports: () => req<EvalCard[]>("/eval/reports"),
  report: (id: string) => req<EvalReport>(`/eval/reports/${id}`),
  registry: () => req<Registry>("/eval/registry"),
};

export function shortId(id: string): string {
  return id.replace(/-/g, "").slice(0, 8).toUpperCase();
}
