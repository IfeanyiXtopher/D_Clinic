import { useEffect, useId, useRef, useState } from "react";

export type QuestionOption = { label: string; q: string };

export function QuestionPicker({
  options,
  value,
  disabled,
  onChange,
}: {
  options: QuestionOption[];
  value: string;
  disabled?: boolean;
  onChange: (question: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const labelId = useId();
  const chosen = options.find((o) => o.q === value);

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
    <div className="picker qa-picker" ref={wrap}>
      <span className="picker-label" id={labelId}>Suggested question</span>
      <button
        type="button"
        className={`picker-btn ${open ? "open" : ""}`}
        aria-labelledby={labelId}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="picker-copy">
          <strong>{chosen?.label ?? "Choose a protocol question"}</strong>
          <span className="picker-sub">
            {chosen?.q ?? `${options.length} HEARTS / PHC questions`}
          </span>
        </span>
        <span className="picker-chevron" aria-hidden>▾</span>
      </button>
      {open ? (
        <ul className="picker-menu" role="listbox">
          {options.map((o) => {
            const active = o.q === value;
            return (
              <li key={o.label}>
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={`picker-option ${active ? "active" : ""}`}
                  onClick={() => {
                    onChange(o.q);
                    setOpen(false);
                  }}
                >
                  <strong>{o.label}</strong>
                  <span className="picker-sub">{o.q}</span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
