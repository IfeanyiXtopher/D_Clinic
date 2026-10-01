import type { ReactNode } from "react";

export function Tip({ tip, children }: { tip: string; children: ReactNode }) {
  return (
    <span className="tip" data-tip={tip} aria-label={tip}>
      {children}
    </span>
  );
}
