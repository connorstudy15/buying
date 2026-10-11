# Cloud beta baseline — 2026-10-11

This baseline records the code and deployment configuration used for the initial
Alibaba Cloud beta. It is a source snapshot, not a backup of cloud databases,
credentials, or the exact running container images.

## Deployment

- Ubuntu 24.04; 2 vCPU / 4 GiB lightweight server.
- Compose project name: `globex`.
- Configuration: `docker/docker-compose.cloud.yaml`.
- Backend image: `globex-backend:beta`, built with `Dockerfile.cloud`.
- Frontend image: `globex-frontend:beta`, built with `frontend/Dockerfile.beta`.
- Frontend binds only `127.0.0.1:5173`; access currently uses an SSH tunnel.
- Redis, Qdrant, API, and worker do not publish host ports.
- SQLite, Redis, and Qdrant use `globex_app-data`, `globex_redis-data`, and
  `globex_qdrant-data` named volumes. Preserve the Compose project name.
- Cloud `.env` uses HMAC identity and session ownership binding. Secrets and
  personal access credentials must remain outside Git and release archives.
- Personal beta tokens expire within 24 hours. The frontend stores tokens and
  strict-mode client caches in the current tab's session storage.

The production frontend consumes prebuilt `frontend/dist`. After editing frontend
source, rebuild it before building the frontend container:

```powershell
cd frontend
npm ci
npm run build
```

`frontend/Dockerfile.beta.dockerignore` permits `dist` in that build context;
the general frontend Dockerfile retains its ordinary source-build behavior.

## Verification evidence

User-reported cloud checks: frontend and `/health` returned HTTP 200; chat,
product retrieval, refresh recovery, and signed beta login worked. A test order
was confirmed and a subsequent verbal confirmation did not add an order, checked
with a read-only SQLite query.

Local verification for the login update: production frontend build passed;
5 access-gate tests and 6 commerce-client tests passed; 58 identity and order
confirmation route tests passed, including concurrent confirmation resolution.
These local tests do not substitute for cloud multi-user acceptance tests.

## Remaining work before sharing publicly

- Integrate selected upstream features on a separate branch.
- Implement invitation exchange and cookie login; the present login accepts a
  manually pasted personal token.
- Verify cloud tenant isolation using two distinct signed buyers.
- Configure HTTPS and a restricted public entry point.
- Set and verify usage limits; currently zero token-budget values mean no such
  budget cap is enabled.
- Back up cloud SQLite and other required state; test restoration.
- Retain versioned images before the next release and verify rollback. Current
  `:beta` image tags are mutable. Schema-changing upgrades need a migration and
  a compatible rollback plan.
- If tools change during integration, check the prompt registry contract and
  publish a compatible prompt version before release.

## Future integration and release

Save current work first. Fetch upstream commits, inspect their scope and
dependencies, merge or cherry-pick on a separate integration branch, then test.
Build a release from the tested commit and deploy the release artifact; do not
archive an older HEAD while leaving intended changes uncommitted. Updating
containers preserves named volumes; never use `down -v` as a routine update.
