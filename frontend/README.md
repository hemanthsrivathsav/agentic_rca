# Supersede frontend

React + TypeScript (Vite), plain CSS. No UI, routing or graph libraries. Needs Node.js 20.19+ or 22.12+ (Vite 8).

```powershell
npm install
npm run dev        # http://localhost:5173, forwards /api to port 8000
npm run typecheck  # tsc only
npm run build      # type-check and build to dist/ (served by the backend)
```

- `src/pages/Overview.tsx`: Runs page (attention band, totals, runs table, recently replaced).
- `src/pages/Decision.tsx`: decision graph page (canvas, Play and breakpoints, replay toggle, fork and resume, branches, panels). The page stays mounted when the run changes, so forking, resuming or opening a branch animates the graph instead of reloading.
- `src/components/EvidenceGraph.tsx` + `src/layout.ts`: the graph, laid out like design v2. Evidence on the left, one column per agent, the outcome on the right. Claims step down in run order, each piece of evidence sits level with the claim it feeds, versions of one source are grouped, and the decision sits in the vertical middle. Node size is how much it drove the decision. Positions depend only on the graph's structure, so a run, its replay and its forks share one layout. On wide screens the graph spreads its columns and scales up.
  - Edge routing (`routeEdges`) keeps any size of graph readable. Every claim has its own row, so edges run along rows and turn only in the lanes between columns. Each edge gets its own port on a box and its own slot in a lane, lanes widen to fit, and the outcome grows with its inputs. Agents that work again later, and claims of one agent with another box between them, are routed around through the lane beside the column. Lines never cross boxes or run on top of each other.
- `src/components/Panels.tsx`: analyst read, selected node, decision stability, mark decision.
- `src/components/StateDrawer.tsx`: state after a step.
- `src/styles.css`: all styles and colour tokens.
