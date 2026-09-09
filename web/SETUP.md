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
