import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api, type NextStep, type ReckonerAsk, type Summary } from "../api";
import { SimplePatient } from "../simple/PatientView";

export function PatientPage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const asOf = params.get("as_of") || "2026-09-26";
  const [sum, setSum] = useState<Summary | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [ask, setAsk] = useState<ReckonerAsk | null>(null);
  const [asking, setAsking] = useState(false);
  const [askErr, setAskErr] = useState("");
  const [rating, setRating] = useState<string | null>(null);
  const [ratingBusy, setRatingBusy] = useState(false);
  const [step, setStep] = useState<NextStep | null>(null);

  async function load() {
    setErr("");
    try {
      const s = await api.summary(id, asOf);
      setSum(s);
      try {
        const last = await api.lastFeedback(id);
        setRating(last.verdict);
      } catch {
        /* briefing still loads if the rating row is missing */
      }
      const bp = s.facts.last_bp;
      setStep(await api.nextStep(bp?.systolic ?? null, bp?.diastolic ?? null, s.facts.drugs ?? []));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => { void load(); }, [id, asOf]);

  async function rate(verdict: string) {
    if (!sum || ratingBusy) return;
    setRatingBusy(true);
    try {
      await api.feedback(id, verdict, sum.case_code);
      setRating(verdict);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRatingBusy(false);
    }
  }

  async function askProtocol(question = q) {
    const text = question.trim();
    if (text.length < 3 || asking) return;
    setQ(text);
    setAsking(true);
    setAskErr("");
    try {
      setAsk(await api.ask(text));
    } catch (e) {
      setAskErr((e as Error).message);
    } finally {
      setAsking(false);
    }
  }

  return (
    <SimplePatient
      id={id}
      asOf={asOf}
      sum={sum}
      err={err}
      q={q}
      setQ={setQ}
      ask={ask}
      asking={asking}
      askErr={askErr}
      rating={rating}
      ratingBusy={ratingBusy}
      step={step}
      rate={rate}
      askProtocol={askProtocol}
    />
  );
}
