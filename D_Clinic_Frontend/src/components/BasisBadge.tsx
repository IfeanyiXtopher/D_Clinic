import { Tip } from "./Tip";

const BAND: Record<string, string> = {
  high: "Top 20% of training scores — most likely to miss the next visit.",
  medium: "Above the typical patient. Worth a closer look.",
  low: "Below typical miss risk. Still on the list if eligible.",
};

const BASIS: Record<string, string> = {
  personal: "Enough of this patient’s own visits to score them directly.",
  mixed: "Own history blended with similar patients.",
  group: "Almost no history. Group estimate (same facility, diabetes, drugs, age) — not “this person will miss.”",
};

export function BasisBadge({ band, basis }: { band?: string | null; basis?: string | null }) {
  return (
    <span>
      {band ? (
        <Tip tip={BAND[band] ?? "Miss-risk band from the training scores."}>
          <span className={`badge ${band}`}>{band}</span>
        </Tip>
      ) : null}
      {basis ? (
        <Tip tip={BASIS[basis] ?? "How much personal history the score used."}>
          <span className={`badge ${basis}`}>{basis}</span>
        </Tip>
      ) : null}
    </span>
  );
}
