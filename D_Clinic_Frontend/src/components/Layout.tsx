import { NavLink, Outlet } from "react-router-dom";

const links = [
  { to: "/", label: "Worklist", end: true, icon: HomeIcon },
  { to: "/chat", label: "SMS", end: false, icon: ChatIcon },
  { to: "/eval", label: "Evaluation", end: false, icon: ChartIcon },
];

export function Layout() {
  return (
    <div className="simple-app">
      <aside className="simple-side" aria-label="Sections">
        <NavLink to="/" end className="simple-logo" aria-label="Follow-up">
          <DropIcon />
          <span>Follow-up</span>
        </NavLink>
        {links.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.end}
            className={({ isActive }) => `simple-nav${isActive ? " active" : ""}`}
            aria-label={l.label}
          >
            <l.icon />
            <span>{l.label}</span>
          </NavLink>
        ))}
      </aside>
      <div className="simple-main">
        <header className="simple-top">
          <span className="simple-word">Follow-up</span>
        </header>
        <Outlet />
      </div>
    </div>
  );
}

function DropIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#e11d48" d="M12 2s7 8.2 7 12.2A7 7 0 1 1 5 14.2C5 10.2 12 2 12 2z" />
    </svg>
  );
}

function HomeIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z" />
    </svg>
  );
}

function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M4 5h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H8l-4 3V6a1 1 0 0 1 1-1z" />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M4 19h16v2H4zm2-3h2V9H6zm5 0h2V5h-2zm5 0h2v-6h-2z" />
    </svg>
  );
}
