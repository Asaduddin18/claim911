Historical setup notes from 22 October 2026. For current status and surfaces, use the root README and docs/PROGRESS.md.

# Claim911 implementation

Working local implementation of the synthetic institution environment, evidence verifier, incident API and Next.js dashboard. This is an ongoing build, not a completed live-call product.

## Current evidence

- 114 tests passed, covering institution/coordinator integration, durable calls, scoped voice tools, evidence provenance, signature verification and public-gateway dispatch guards.
- Next.js production build passed.
- Live dashboard login and incident creation checked in the browser.
- Separate hospital and claims database permissions verified by a denied coordinator database query.
- Ed25519 recipient signatures verified with a public key only.
- Manual test conversations are labeled `MANUAL_RECONSTRUCTION`; they never count as real calls.
- A dedicated Bolna agent is saved: `4392053e-ad9a-4bde-900d-1ae28886846b`.
- Browser inspection found $3.54 credit, trial restrictions to verified recipient numbers, and no assigned inbound number. These account observations are dated 22 October 2026 and may change.

The verified participant received one provider dispatch, which ended in `NO_ANSWER`. No answered conversation, transcript, recording or complete real-call case has been proven. Mocked HTTP tests cover adapter behavior only. See `docs/PROGRESS.md` for remaining work.

## Local services

| Component | URL |
|---|---|
| Next.js dashboard | http://127.0.0.1:3110 |
| Incident API / OpenAPI | http://127.0.0.1:8110/docs |
| Hospital/claims environment | http://127.0.0.1:8111 |
| Institution OpenAPI | http://127.0.0.1:8111/docs |

Dashboard, incident API and institution services bind to loopback. The restricted voice gateway is connected to Bolna through a user-approved temporary Cloudflare tunnel. Live outbound calling is configured for the consenting verified test participant; further calls are on hold until the participant confirms readiness. Use synthetic case data only.

## Setup

Use Python 3.14, a local PostgreSQL installation, Node 22+ and pnpm. The currently tested dependency versions are pinned in `requirements.txt` and `dashboard/pnpm-lock.yaml`.

From this directory:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p runtime
initdb -D runtime/postgres -A trust -U claim911 --no-locale -E UTF8
pg_ctl -D runtime/postgres -l runtime/postgres.log -o '-p 55432 -h 127.0.0.1' start
.venv/bin/python scripts/bootstrap.py --runtime runtime
cd dashboard
pnpm install --frozen-lockfile
pnpm build
```

Local trust authentication is for a single-user development machine only. Do not expose this database or use that authentication in a deployed service. Bootstrap writes separate role tokens and an institutional signing key with file mode 0600. It refuses to overwrite existing configuration. Do not commit runtime files or paste their contents into chat.

Start services in separate terminals from this directory:

```sh
CLAIM911_SIM_CONFIG="$PWD/runtime/simulator.json" .venv/bin/python -m uvicorn simulator.app:create_app --factory --host 127.0.0.1 --port 8111
CLAIM911_CORE_CONFIG="$PWD/runtime/coordinator.json" .venv/bin/python -m uvicorn coordinator.app:create_app --factory --host 127.0.0.1 --port 8110
# Start a separate worker only when the calling configuration is deliberately ready:
# CLAIM911_CORE_CONFIG="$PWD/runtime/coordinator.json" .venv/bin/python -m coordinator.worker
# While outgoing calls are on hold, use observation only:
# CLAIM911_CORE_CONFIG="$PWD/runtime/coordinator.json" .venv/bin/python -m coordinator.worker --observe-only
```

From `dashboard/`:

```sh
pnpm start -p 3110
```

For this chat's running installation, the virtual environment and private runtime are in the workspace's `work/venv` and `work/claim911-runtime` directories rather than this source folder.

## Reproduce the case

1. In the institution portal, use the evaluator role token to seed a wrong-route case. Record its case ID.
2. Use the hospital role token to inspect its case and submission history. Download dispatch evidence.
3. Use the claims role token to search the final request. It is absent from the correct queue.
4. Log into the Claim911 dashboard with the operator token and create an incident for that case ID.
5. Record the synthetic caregiver's consent. Add manual hospital/claims conversations and attributed statements. Keep these explicitly labeled as manual reconstruction.
6. Upload the original hospital submission JSON as `dispatch`. Link it to the hospital `DESTINATION` statement. Record a hospital `SUBMITTED` statement and claims `NOT_RECEIVED` statement for the same final reference.
7. Propose a correction and record approval of the displayed exact action.
8. The hospital participant submits the corrected packet through its own portal. Claim911 has no hospital submission credential.
9. Download the corrected submission from hospital history. Use one submission object, adding `submission_id` equal to its `id`. Upload it as a dispatch document.
10. Read the signed acknowledgment through the claims portal. Paste one `{envelope, signature}` object into the dashboard verifier and select the corrected dispatch file.
11. Verify that routing resolves and the insurance decision remains pending. The original attempt must still exist.

The manual reconstruction is an environment/coordination proof, not a substitute for the required real-call demonstration.

## Tests

The simulator must be running on port 8111 for coordinator route checks. Integration tests create fresh synthetic cases; they do not reset existing cases.

```sh
CLAIM911_SIM_CONFIG="$PWD/runtime/simulator.json" CLAIM911_CORE_CONFIG="$PWD/runtime/coordinator.json" .venv/bin/python -m pytest tests -q
```

See `docs/CASE.md` for source versus reconstruction boundaries.

## Security and current limitations

The dashboard currently represents a local operator workspace, not separately authenticated production caregiver accounts. Uploads are private API-served PostgreSQL blobs, limited to 10 MiB, and begin unverified. PDF files are downloaded for inspection; text/JSON and images can be previewed. Recordings have not been captured or played back. Call-job leasing, scoped context/statement tools and webhook inbox processing are implemented and tested with a mock provider. Inbound binding, provider polling reconciliation, automated cross-call orchestration and live tool configuration remain to be completed and verified.

No production approval, insurer partnership or real patient access is implied.


## Approved product redesign

The new local product surfaces live in `product/`, backed by the role-scoped `experience/` API. Operational and sandbox profiles use separate databases. The legacy source is preserved for read-only evidence review. See `docs/REDESIGN_STATUS.md` for verified behavior and remaining MVP gates. The audio sandbox runtime is isolated under Python 3.12 with exact dependencies in `requirements-audio.lock`; installing it does not prove audio workflow completion.
