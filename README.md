# Health Guard

Health Guard is a bounded replenishment agent for recurring OTC health supplies. It uses real merchant UCP catalog data and Prava's trust layer; it never uses fake products, mock payment outcomes, or simulated checkout data.

## Normal user workflow

1. Add a beneficiary (including **Self**).
2. Describe a recurring supply using the wording on its label and ordinary inventory quantities.
3. Select trusted merchants.
4. Create a merchant-specific Prava mandate and complete its one-time passkey approval.

Health Guard's backend then searches live merchant catalogs, asks the configured OpenAI model to
review only deterministic exact-match candidates, creates internal equivalence/variant approvals,
and runs the existing deterministic replenishment and REST mandate-charge workflow. Product IDs,
variant IDs, JSON traces, and payment credentials are not part of the normal user interface.

Authenticated server-sent events keep supply setup, mandates, agent outcomes, and transactions live
in the browser. `OPENAI_MODEL` selects the model without requiring code changes; the default is
`gpt-5.6-terra`.

## Local development

1. Copy the safe placeholders in `.env.example` into the existing root `.env` and add only your real sandbox values.
2. Start the project-local PostgreSQL cluster: `npm run db:start`.
3. Install frontend dependencies: `npm install`.
4. Create and activate a Python environment, then install the backend: `python3 -m venv .venv && . .venv/bin/activate && pip install -e 'apps/api[dev]'`.
5. Apply migrations: `cd apps/api && alembic upgrade head`.
6. Start the API: `npm run dev:api`.
7. Start the web app: `npm run dev:web`.

## Service checks

- API liveness: `http://localhost:8000/api/v1/health/live`
- API database readiness: `http://localhost:8000/api/v1/health/ready`
- API → Prava sandbox connectivity: `http://localhost:8000/api/v1/integrations/prava/health`
- Web app: `http://localhost:3000`
- UCP profile: `http://localhost:3000/.well-known/ucp`

## Phase 2 care setup

Open `http://localhost:3000` to create an account and configure care inventory. The setup flow uses the
live local PostgreSQL database; it does not seed or display fabricated products.

- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, and
  `GET /api/v1/auth/me` provide bearer-token MVP authentication. Passwords are salted and scrypt-hashed;
  session tokens are stored only as hashes in PostgreSQL.
- `GET /api/v1/setup/dashboard` and the `/setup/*` mutation endpoints are owner-scoped. An account cannot
  read or modify another account's beneficiaries, supplies, merchant permissions, or approved variants.
- New supplies start paused. They can be enabled only after an enabled merchant authorization and at least
  one exact approved merchant product/variant have been recorded. Product matching is never fuzzy.

The PostgreSQL tables are defined in `apps/api/app/models.py` and created by migration
`ce93b398178e_phase_2_care_setup.py`. Database storage remains in ignored `.postgres-data/`; it is not a
single file checked into the backend source tree.

## Phase 3 Replenishment Agent

- `POST /api/v1/agent-runs/supplies/{supply_id}` starts an owner-scoped evaluation. Send the same optional
  `trigger_id` to reuse an existing run rather than create a duplicate.
- `GET /api/v1/agent-runs` and `GET /api/v1/agent-runs/{run_id}` return the safe, ordered trace shown in the
  dashboard.
- Agent state transitions are constrained to `observe → discover → decide → act → verify → complete`, with
  `blocked` as a safe terminal state. Phase 3 exposes no payment or checkout tool.
- The real catalog adapter intentionally arrives in Phase 4. When an enabled supply reaches its safety buffer,
  the agent records a `blocked` trace rather than inventing catalog results, quotes, or a transaction.

## Phase 4 UCP readiness and live discovery

- `GET /api/v1/integrations/ucp/readiness` reports whether direct Shopify UCP calls are safe to make.
- `HEALTH_GUARD_UCP_PROFILE_URL` is set to Health Guard's own deployed HTTPS profile. Himalaya has
  successfully negotiated catalog search, lookup, and product read through that profile.
- Safe catalog and quote fields will persist in `offer_snapshots` (merchant/product/variant identity,
  availability, currency, price, ETA, quote ID, and expiry). Payment credentials and raw addresses are never
  part of this record.
- A controlled unpaid quote identified that a delivery destination is required before a delivery estimate can
  be trusted. The agent therefore records a safe blocked result instead of choosing or paying for an offer
  with an invented ETA.

## Phase 5 Prava mandates

- `POST /api/v1/mandates/{merchant_authorization_id}/setup-session` creates a merchant-scoped,
  authorize-only Prava mandate session. Its short-lived hosted approval URL is returned only to the signed-in
  browser; the backend stores safe configuration/state but never the URL, session token, card details, or
  credentials.
- `POST /api/v1/mandates/{merchant_authorization_id}/sync` lists standing mandates for the opaque Health
  Guard user reference and records the mandate ID, status, cap, frequency, expiry, cycle balance, and sync
  time.
- Owner-confirmed `pause`, `resume`, and `cancel` endpoints call Prava's lifecycle APIs and append a safe
  `mandate_events` record. The deterministic agent rejects a merchant when its mandate is not active,
  expired, over its cap, or has insufficient remaining cycle balance.
- The live sandbox currently rejects the documented optional `mandate_setup.valid_until` field. Health Guard
  therefore omits it from the Prava request, records Prava's own validity horizon on sync, and separately
  enforces the owner's selected **Health Guard stops after** time before the agent can initiate any charge.
- Start the local API and web app, create a merchant authorization, choose a cap/frequency in **Prava mandate
  controls**, open the Prava approval page, complete the passkey step, and then select **Sync Prava status**.

## Security boundary

- The browser never receives Prava secret keys, card data, dynamic CVVs, or mandate-charge responses.
- All Prava and direct UCP calls will live behind the FastAPI integration boundary.
- The application has no demo checkout mode. A failed upstream integration is surfaced as a failed state, never converted into a fake success.

## Local database storage

Health Guard uses the already-installed PostgreSQL binaries, not Docker. `npm run db:start` creates
the database cluster and Unix socket under the ignored `.postgres-data/` and `.postgres-socket/`
directories in this repository. It does not install packages or write a database image/volume outside
this project. Set `DATABASE_URL` only when connecting to an explicitly chosen external PostgreSQL
server.
