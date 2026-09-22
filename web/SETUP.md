# ArcAgent website

The site includes a product landing page, a synthetic demo workspace, and an authenticated read-only console for the existing FastAPI service. Calls, scoring breakdowns, saved evaluation transcripts, and regression comparisons come from the existing database. The website never initiates calls or changes qualification rules.

## Development

Use the Node version declared in package.json. From this directory, run `npm ci` and `npm run dev`. Open the URL printed by the development server. `/demo` always uses fictional examples; `/workspace` requires sign-in. The Sites development server supplies a mock identity locally. Never treat that mock identity as production authentication.

Run `npm run typecheck`, `npm run lint`, `npm test`, and `npm run build` before pushing. GitHub Actions runs the same checks. Lint excludes the unmodified generated component catalog and its mobile hook; application components remain checked. Targeted React compiler exceptions cover synchronizing request state and clearing stale records during fetches.

## Connect real records

Deploy the Python application and apply its existing database migrations. Set a strong random `CONSOLE_API_TOKEN` in the backend environment. Copy `.env.example` to an ignored `.env.local` for local development, or set the corresponding server environment variables in Sites for the hosted application:

- `ARCAGENT_API_URL`: HTTPS origin of the FastAPI service. Local development additionally permits HTTP loopback.
- `ARCAGENT_API_TOKEN`: the same secret as the backend's `CONSOLE_API_TOKEN`.
- `ARCAGENT_ALLOWED_USER_IDS`: explicitly authorized ChatGPT account user IDs, obtained from the trusted Sites identity. An empty allowlist denies all live access.

Do not use browser-exposed environment variables for these values. The production identity is supplied by the Sites dispatcher; self-hosting requires an equivalent trusted authentication boundary. The proxy does not trust browser-supplied user IDs or authorization headers, and never follows upstream redirects. API responses are not cached. The shared backend credential is intended for this private single-workspace console, not tenant isolation.

The hosted site starts without backend connection settings. Its demo works independently; the live workspace displays an explicit configuration message. It does not silently substitute sample data for real records. The Python telephony service remains a separate deployment.

## Product behavior

Conversation search and date/outcome filters apply to the loaded page, as indicated in the table footer. Pagination retrieves additional saved calls. Evaluation exploration loads the latest runs with their saved scenario groups, expected/actual fields, and transcripts. Comparisons reuse the existing harness compatibility checks and regression guards. Missing latency and evaluation measurements remain marked as unavailable.

The interface uses React, Vinext's Next-compatible app routing, Tailwind, shadcn/Base UI primitives, Lucide icons, Recharts, and resizable panels. The Sites/Vite/Cloudflare dependencies provide authenticated Worker hosting. Security updates and matching peer dependencies are pinned in the lockfile. No Python dependencies were added.

A feature-detected WebMCP read tool exposes only the currently visible conversation summaries. Unsupported browsers continue normally. A supported browser WebMCP validation context was unavailable during implementation, so browser-level registration has not been verified.


## Operations workspace and native Next.js

The workspace now opens on Operations: configuration checks, recent call counts, abandoned/unfinished call review, and recovery guidance. The authenticated read-only `operations` endpoint exposes no caller names or contact details. Active calls can appear as unfinished. Database outages preserve configuration findings but leave counts unavailable. Request timeouts and invalid data show retry states; no live errors are replaced with demo data. `/demo?view=operations` offers clearly fictional setup/configured/outage scenarios.

The existing default scripts retain the Vinext/Sites build and identity boundary. Native Next.js is available with `npm run dev:next`, `npm run build:next`, and `npm run start:next`. Both builds are checked in CI. Run them sequentially: Next and Vinext generate the same ignored type declaration file. Native Next uses `tsconfig.next.json` and the existing Tailwind PostCSS dependency.

Native Next deliberately denies live workspace access until a verified session adapter is implemented. It never trusts incoming Sites identity headers. Only the Sites Vite build defines the trusted-runtime marker, and that artifact still must run behind the trusted Sites dispatcher. Do not add the marker to a native deployment to bypass authentication. The landing page and fictional demo work in native Next without account setup.

New dependencies: Next.js for the native App Router build and Motion for reduced-motion-aware status transitions. Tailwind v4, TypeScript, shadcn/Base UI, and Lucide remain the shared UI stack. A selective static Magic UI DotPattern adaptation is attributed in `THIRD_PARTY_NOTICES.md`; no separate Aceternity library or paid templates were added. [Next TypeScript configuration](https://nextjs.org/docs/app/api-reference/config/next-config-js/typescript), [Motion accessibility](https://motion.dev/docs/react-use-reduced-motion).

## Failure experiments and coordinator workflows

The sidebar now includes Failure lab and Follow-up & feedback. `/demo?view=lab` presents saved, explicitly simulated comparisons; live authenticated workspaces run the Python policy harness through the console proxy. The demo queue is read-only. Live call timing includes percentile coverage and missing/invalid sample counts. Latency summaries can fail independently while the original stored turn values remain visible.

Before using live workflows, apply the new Alembic migration with the backend's database connection: `alembic upgrade head`. It adds follow-up, regression-feedback, and audit tables. Back up any existing database first. No new dependencies were added in this iteration.

Writes require same-origin JSON requests and a server-derived actor ID; the browser cannot choose the acting reviewer. Console credentials remain server-only. The backend bearer is a trusted service credential whose holder can assert actors, so never expose it to clients. Feedback creation uses a UUID idempotency key for the current form intent; matching retries return the original record. Refresh saved records after an uncertain response. A full browser reload loses an unsaved draft and its in-memory request key; inspect the queue before submitting a new intent. No writes are automatically retried.

Follow-up updates require the current revision. After a conflict, copy your draft note, refresh the list, open the latest task, and reconcile your changes. The audit API is `GET /api/console/followups/{id}/audit`. Feedback requires a fictional rewritten scenario, expected behavior, and explicit confirmation that personal information was removed. A different authenticated reviewer must approve it before candidate export. This is human review and attestation, not an automatic de-identification guarantee. Exports are specifications for a human-authored regression test; they are not executable personas and never automatically join the evaluation suite.

## Vercel deployment

Deploy from the `web/` directory. `vercel.json` explicitly selects the native Next.js build and `.next-native` output; the default Vinext scripts remain available for Sites. The deployment ignore file excludes local environment files and generated output. When importing the GitHub repository in Vercel, set the project Root Directory to `web`.

The deployed `/demo` works without backend credentials. It includes fictional calls, evaluation examples, operations scenarios, saved failure comparisons, and a read-only queue preview. Native `/workspace` remains closed until a verified identity adapter is implemented. Deploying the frontend does not deploy the Python telephony service, database, or live failure-lab runner. Do not bypass the identity guard or expose the backend token in client environment variables.
