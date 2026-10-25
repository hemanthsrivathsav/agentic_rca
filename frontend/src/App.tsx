import { useEffect, useState } from "react";
import Header from "./components/Header";
import Overview from "./pages/Overview";
import Decision from "./pages/Decision";

// Tiny hash router: #/ (runs) and #/runs/<id> (decision graph). No router library.
function useRoute(): string {
  const [hash, setHash] = useState(() => window.location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash.slice(1);
}

export default function App() {
  const route = useRoute();
  const runMatch = route.match(/^\/runs\/([^/]+)/);
  return (
    <div className="app">
      <Header active={runMatch ? "decision" : "runs"} />
      {/* not keyed by run id: moving between a run and its forks animates instead of reloading */}
      {runMatch ? <Decision runId={decodeURIComponent(runMatch[1])} /> : <Overview />}
    </div>
  );
}
