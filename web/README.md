# Kotivalo UI

The phone and wall-panel UI for kotivalo: React, TypeScript, Vite, Tailwind v4 and shadcn/ui.
Finnish and English. It is built into `../src/kotivalo/static/`, which the Python service
serves; `deploy/deploy.sh` runs the build.

```sh
npm install
npm run dev          # http://localhost:5173, /api proxied to a local `kotivalo serve --fake` on :8080
npm run lint && npm test && npm run e2e
npm run build
```

See `../CLAUDE.md` for the UI rules (i18n, design tokens, touch targets).
