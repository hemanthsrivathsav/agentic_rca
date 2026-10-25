export default function Header({ active }: { active: "runs" | "decision" }) {
  return (
    <header className="topbar">
      <a className="brand" href="#/">
        <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
          <rect x="1" y="1" width="24" height="24" rx="6" fill="#0E1D21" />
          <circle cx="8" cy="17" r="2.5" fill="#FF6A55" />
          <circle cx="18" cy="9" r="2.5" fill="#43C6AC" />
          <path d="M10 15.5L16 10.5" stroke="#E6EEEC" strokeWidth="1.6" />
        </svg>
        <span>Supersede</span>
      </a>
      <nav aria-label="Main" className="topnav">
        <a href="#/" aria-current={active === "runs" ? "page" : undefined}>
          Runs
        </a>
        <a href="#/runs/KYC-2041" aria-current={active === "decision" ? "page" : undefined}>
          Decision graph
        </a>
      </nav>
      <span className="topbar-note">Harborline Bank, synthetic data</span>
    </header>
  );
}
