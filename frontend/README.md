# Supersede frontend

React + TypeScript (Vite), plain CSS. No UI, routing or graph libraries.

```powershell
npm install
npm run dev        # http://localhost:5173, forwards /api to port 8000
npm run build      # type-check and build to dist/ (served by the backend)
```

- `src/pages/Overview.tsx`: Runs page (attention band, totals, runs table, recently replaced).
- `src/pages/Decision.tsx`: decision graph page (canvas, Play and breakpoints, replay toggle, branches, panels).
- `src/components/EvidenceGraph.tsx` + `src/layout.ts`: the graph. Columns are agents, rows are steps, node size is how much it drove the decision.
- `src/components/Panels.tsx`: analyst read, selected node, decision stability, mark decision.
- `src/components/StateDrawer.tsx`: state after a step.
- `src/styles.css`: all styles and colour tokens.
