# Dashboard

`index.html` is a modified copy of `SCC_Profitability_Dashboard2.html` with three changes (see PLAN.md §7):

1. The embedded `const DATA = {...}` literal is replaced with `fetch('/api/dashboard?year=Y')`.
2. The base64 `SCC_LOGO_B64` block is removed; the masthead `<img>` and the PDF export both read from `/tenant-logo.png`, which the backend serves per-tenant.
3. The year `<select>` is populated by `/api/years` and triggers `loadYear(value)` on change.

`login.html` is a small, USWDS-styled sign-in form that posts JSON to `/auth/login`.

`assets/scc.png` is the default logo shown when a tenant hasn't uploaded their own.
