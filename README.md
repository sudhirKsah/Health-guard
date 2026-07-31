# Health Guard

Health Guard is a bounded replenishment agent for recurring OTC health supplies. It uses real merchant UCP catalog data and Prava's trust layer; it never uses fake products, mock payment outcomes, or simulated checkout data.

## Local development

1. Copy the safe placeholders in `.env.example` into the existing root `.env` and add only your real sandbox values.
2. Start the project-local PostgreSQL cluster: `npm run db:start`.
3. Install frontend dependencies: `npm install`.
4. Create and activate a Python environment, then install the backend: `python3 -m venv .venv && . .venv/bin/activate && pip install -e 'apps/api[dev]'`.
5. Apply migrations: `cd apps/api && alembic upgrade head`.
6. Start the API: `uvicorn app.main:app --app-dir apps/api --reload`.
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

## Phase 4 UCP readiness

- `GET /api/v1/integrations/ucp/readiness` reports whether direct Shopify UCP calls are safe to make.
- Configure `HEALTH_GUARD_UCP_PROFILE_URL` only with Health Guard's own deployed HTTPS
  `/.well-known/ucp` URL. The backend refuses to use a public/shared test profile.
- Safe catalog and quote fields will persist in `offer_snapshots` (merchant/product/variant identity,
  availability, currency, price, ETA, quote ID, and expiry). Payment credentials and raw addresses are never
  part of this record.

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
