import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { shortId, type DemoContext, type Worklist, type WorklistItem } from "../api";
import { FacilityPicker } from "../components/FacilityPicker";
import { Tip } from "../components/Tip";

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

const BAND_TIP: Record<string, string> = {
  high: "Top 20% of training scores — most likely to miss the next visit.",
  medium: "Above the typical patient. Worth a closer look.",
  low: "Below typical miss risk. Still on the list if eligible.",
};

const INTERACTION: Record<string, string> = {
  agreed_to_visit: "Agreed to visit",
  remind_to_call_later: "Call later",
  removed_from_overdue_list: "Removed from overdue list",
  visited: "Visited",
};

function interactionLine(item: WorklistItem): string {
  if (!item.last_interaction) return "Last interaction · None recorded";
  const label = INTERACTION[item.last_interaction] ?? item.last_interaction.replaceAll("_", " ");
  if (!item.last_interaction_at) return `Last interaction · ${label}`;
  const d = new Date(item.last_interaction_at);
  if (Number.isNaN(d.getTime())) return `Last interaction · ${label}`;
  const when = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })
    .replace(/ /g, "-")
    .toUpperCase();
  return `Last interaction · ${when} · ${label}`;
}

function sentence(text: string) {
  const t = text.trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : t;
}

const PAGE_SIZE = 8;

type Kind = "agreed_to_visit" | "remind_to_call_later" | "skip";
type Act = (item: WorklistItem, kind: Kind) => void | Promise<void>;

type Filters = {
  section: "overdue" | "pre_visit";
  highOnly: boolean;
  phone: "any" | "yes" | "no";
};

export function SimpleWorklist({
  ctx, facilityId, setFacilityId, listDate, setListDate, data, err, busy, load, act,
}: {
  ctx: DemoContext | null;
  facilityId: string;
  setFacilityId: (id: string) => void;
  listDate: string;
  setListDate: (d: string) => void;
  data: Worklist | null;
  err: string;
  busy: boolean;
  load: (rebuild?: boolean) => void;
  act: Act;
}) {
  const [draft, setDraft] = useState<Filters>({ section: "overdue", highOnly: false, phone: "any" });
  const [applied, setApplied] = useState<Filters>(draft);
  const [page, setPage] = useState(1);

  function setFilters(next: Filters) {
    setDraft(next);
    setApplied(next);
  }

  useEffect(() => { setPage(1); }, [facilityId, listDate, applied]);

  const source = applied.section === "overdue" ? (data?.overdue ?? []) : (data?.pre_visit ?? []);
  const items = useMemo(() => source.filter((item) => {
    if (applied.highOnly && item.band !== "high") return false;
    if (applied.phone === "yes" && !item.has_phone) return false;
    if (applied.phone === "no" && item.has_phone) return false;
    return true;
  }), [source, applied]);

  const pages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const start = (page - 1) * PAGE_SIZE;
  const slice = items.slice(start, start + PAGE_SIZE);

  return (
    <section className="s-page">
      <header className="s-pagehead">
        <div className="s-pagehead-main">
          <h1>Follow-up list</h1>
          <p>Ranked by missed-visit risk. A score never removes anyone. You see a case stub, not a name.</p>
        </div>
      </header>

      <div className="s-toolbar">
        <FacilityPicker facilities={ctx?.facilities ?? []} value={facilityId} onChange={setFacilityId} />
        <label className="s-field">
          List date
          <input type="date" value={listDate} onChange={(e) => setListDate(e.target.value)} />
        </label>
        <button type="button" className="s-btn" onClick={() => void load(true)} disabled={busy}>Rebuild</button>
      </div>

      {data ? (
        <p className="s-count">
          {data.counts.total} on the list · {data.counts.open} open · {data.counts.done} done · {data.counts.skipped} skipped
        </p>
      ) : null}
      {err ? <p className="err">{err}</p> : null}

      <div className="s-panel">
        <div className="s-filters">
          <p className="s-filters-label">Filters</p>
          <label><input type="radio" name="section" checked={draft.section === "overdue"} onChange={() => setFilters({ ...draft, section: "overdue" })} /> Overdue — already missed</label>
          <label><input type="radio" name="section" checked={draft.section === "pre_visit"} onChange={() => setFilters({ ...draft, section: "pre_visit" })} /> Pre-visit — next 7 days</label>
          <label><input type="checkbox" checked={draft.highOnly} onChange={(e) => setFilters({ ...draft, highOnly: e.target.checked })} /> High risk only</label>
          <label><input type="checkbox" checked={draft.phone === "yes"} onChange={(e) => setFilters({ ...draft, phone: e.target.checked ? "yes" : "any" })} /> Has phone</label>
          <label><input type="checkbox" checked={draft.phone === "no"} onChange={(e) => setFilters({ ...draft, phone: e.target.checked ? "no" : "any" })} /> No phone</label>
          <button type="button" className="s-btn" onClick={() => setApplied(draft)}>Apply filters</button>
        </div>

        <div className="s-list-head">
          <strong>{applied.section === "overdue" ? "Overdue" : "Pre-visit"}</strong>
          <span>{items.length} patient{items.length === 1 ? "" : "s"}</span>
        </div>

        {!data ? <p className="s-empty">Loading the list…</p> : null}
        {data && !items.length ? <p className="s-empty">No rows for these filters.</p> : null}

        <div className="s-list">
          {slice.map((item) => (
            <SimpleCard key={item.id} item={item} asOf={listDate} onAct={act} />
          ))}
        </div>

        {pages > 1 ? (
          <nav className="s-pager" aria-label="Worklist pages">
            <span>{start + 1}–{Math.min(start + PAGE_SIZE, items.length)} of {items.length}</span>
            <button type="button" className="s-btn" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</button>
            {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
              <button
                key={n}
                type="button"
                className={n === page ? "s-btn on" : "s-btn"}
                aria-current={n === page ? "page" : undefined}
                onClick={() => setPage(n)}
              >
                {n}
              </button>
            ))}
            <button type="button" className="s-btn" disabled={page === pages} onClick={() => setPage(page + 1)}>Next</button>
          </nav>
        ) : null}
      </div>
    </section>
  );
}

function SimpleCard({ item, asOf, onAct }: { item: WorklistItem; asOf: string; onAct: Act }) {
  const overdue = item.days_overdue > 0;
  const [saving, setSaving] = useState<Kind | "">("");

  async function run(kind: Kind) {
    if (saving) return;
    setSaving(kind);
    try {
      await onAct(item, kind);
    } finally {
      setSaving("");
    }
  }

  const done = item.status !== "open";
  return (
    <article className="s-patient">
      <div className="s-patient-head">
        <div className="s-case">
          <Link to={`/patients/${item.patient_id}?as_of=${asOf}`}>Case {shortId(item.patient_id)}</Link>
          {done ? <span className="s-recorded-tag">Recorded</span> : null}
        </div>
        <div className="s-head-right">
          {item.band === "high" ? (
            <Tip tip={BAND_TIP.high}>
              <span className="s-risk">High risk</span>
            </Tip>
          ) : null}
          <span className="s-days">{overdue ? `${item.days_overdue} days overdue` : `Visit in ${-item.days_overdue} days`}</span>
        </div>
      </div>
      <div className="s-chips">
        <Tip tip="Place on this facility’s list. Rank 1 is the first call.">
          <span className="s-chip">Rank {item.rank}</span>
        </Tip>
        {item.p_missed != null ? (
          <Tip tip="The model’s estimate that the next visit will be missed (no blood pressure in the visit window).">
            <span className="s-chip">Miss chance {item.p_missed.toFixed(2)}</span>
          </Tip>
        ) : null}
        {item.uncontrolled ? (
          <Tip tip="Last clinic BP at or above 140/90.">
            <span className="s-chip warn">BP not at goal</span>
          </Tip>
        ) : null}
        {item.protected_slot ? (
          <Tip tip="One of about 25% of today’s slots reserved for uncontrolled BP so they are not buried.">
            <span className="s-chip">Protected slot</span>
          </Tip>
        ) : null}
        {item.basis ? (
          <Tip tip={BASIS_TIP[item.basis] ?? "How much personal history the score used."}>
            <span className="s-chip">{BASIS[item.basis] ?? item.basis}</span>
          </Tip>
        ) : null}
        {item.band && item.band !== "high" ? (
          <Tip tip={BAND_TIP[item.band] ?? "Miss-risk band from the training scores."}>
            <span className="s-chip">{sentence(item.band)} risk</span>
          </Tip>
        ) : null}
      </div>
      {item.reasons.length ? (
        <p className="s-reasons">{item.reasons.map(sentence).join(". ")}.</p>
      ) : null}
      <div className={`s-actions ${done ? "is-done" : ""}`}>
        {item.has_phone ? (
          <Link className="s-phone" to={`/chat?patient_id=${item.patient_id}`}>Open SMS</Link>
        ) : (
          <span className="s-phone off">No phone</span>
        )}
        <button type="button" className="s-btn agree" disabled={done || !!saving} onClick={() => void run("agreed_to_visit")}>
          <span className="s-dot agree" aria-hidden />
          {saving === "agreed_to_visit" ? "Saving…" : "Agreed to visit"}
        </button>
        <button type="button" className="s-btn later" disabled={done || !!saving} onClick={() => void run("remind_to_call_later")}>
          <span className="s-dot later" aria-hidden />
          {saving === "remind_to_call_later" ? "Saving…" : "Call later"}
        </button>
        <button type="button" className="s-btn remove" disabled={done || !!saving} onClick={() => void run("skip")}>
          <span className="s-dot skip" aria-hidden />
          {saving === "skip" ? "Saving…" : "Skip"}
        </button>
      </div>
      <p className="s-suggest">
        <Tip tip="What the rules suggest. You still decide whether to call.">
          Suggested · {item.suggested_action.replaceAll("_", " ")}
        </Tip>
      </p>
      <p className="s-interact">{interactionLine(item)}</p>
    </article>
  );
}
