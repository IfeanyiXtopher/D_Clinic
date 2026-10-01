import { useEffect, useId, useRef, useState } from "react";
import type { Facility } from "../api";

export function FacilityPicker({
  facilities,
  value,
  onChange,
}: {
  facilities: Facility[];
  value: string;
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const labelId = useId();
  const chosen = facilities.find((f) => f.id === value) ?? facilities[0];

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
    <div className="picker" ref={wrap}>
      <span className="picker-label" id={labelId}>Facility</span>
      <button
        type="button"
        className={`picker-btn ${open ? "open" : ""}`}
        aria-labelledby={labelId}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="picker-copy">
          <strong>{chosen?.name ?? "Select a facility"}</strong>
          {chosen ? (
            <span className="picker-sub">
              {[chosen.facility_type, chosen.district].filter(Boolean).join(" · ") || "PHC"}
            </span>
          ) : null}
        </span>
        <span className="picker-chevron" aria-hidden>▾</span>
      </button>
      {open ? (
        <ul className="picker-menu" role="listbox">
          {facilities.map((f) => {
            const active = f.id === value;
            return (
              <li key={f.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={`picker-option ${active ? "active" : ""}`}
                  onClick={() => {
                    onChange(f.id);
                    setOpen(false);
                  }}
                >
                  <strong>{f.name}</strong>
                  <span className="picker-sub">
                    {[f.facility_type, f.district].filter(Boolean).join(" · ")}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
