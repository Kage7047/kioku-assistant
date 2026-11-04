# Command center

The web UI for Kioku: chat with live streaming, runs, agent credit, the approval inbox, activity,
the knowledge graph, skills and people. Vite + React, GSAP (via `@gsap/react`), Lenis smooth
scrolling, and [React Bits](https://reactbits.dev) components (`src/components/rb/`, vendored
unchanged: SpotlightCard, CountUp, ClickSpark, Magnet, SplitText).

```bash
npm ci
npm run dev        # http://localhost:5173, proxies the API to a Kioku on :8000
npm run build      # writes ../src/kioku/api/static — commit the result
```

The build is committed so the Python package and the Docker image need no Node; CI rebuilds it and
fails if the committed output is stale.

- **Same origin.** FastAPI serves `index.html` at `/` and the hashed assets at `/static/assets/`;
  every data call carries the dashboard token (bearer header; `?token=` for the SSE stream only).
- **Motion.** Follows the OS reduce-motion setting; `?motion=on` / `?motion=off` or the footer
  toggle override it, and the choice is remembered.
- **Accessibility.** Skip link, labelled regions and controls, an `aria-live` conversation log,
  visible focus, keyboard-only use, and the layout reflows to one column on phones.
