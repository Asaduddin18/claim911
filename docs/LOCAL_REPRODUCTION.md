# Reproduce the local synthetic workflow

This procedure reproduces backend coordination, state and evidence checks from empty databases. It does not reproduce Bolna audio, certify a fresh machine or establish hackathon readiness. No provider credentials are needed.

## Prerequisites

- Local PostgreSQL with permission to create databases and roles.
- Python environment with the project's pinned `requirements.txt` installed.
- Project source, including tests and institution schema.
- A private JSON admin profile containing `admin_dsn`, pointing to loopback PostgreSQL. Keep it outside source control with restrictive permissions. Do not put passwords into command arguments or paste them into chat.

Use an empty private runtime directory and a unique lowercase alphanumeric suffix. Existing databases, roles and mismatched runtime namespaces are rejected rather than silently reset or rotated.

## Create isolated storage

From the Claim911 source directory, using the configured Python environment:

```text
python scripts/bootstrap_profiles.py --runtime /private/runtime/claim911-clean --admin-profile /private/config/postgres-admin.json --suffix rehearsal1 --operational-port 8313 --sandbox-port 8314
```

This creates separate operational and sandbox databases, per-environment database roles, API credentials and distinct institution issuer keys. Coordinator profiles hold public verification keys rather than institution signing keys. Calling is disabled. Repeating the same setup retains existing matching private configuration.

No provider profile, tunnel, Bolna broker or voice worker is part of this local proof.

## Start synthetic institutions

Use separate terminals with the configured Python environment:

```text
CLAIM911_SIM_CONFIG=/private/runtime/claim911-clean/operational/simulator.json python -m uvicorn simulator.app:create_app --factory --host 127.0.0.1 --port 8313
```

```text
CLAIM911_SIM_CONFIG=/private/runtime/claim911-clean/sandbox/simulator.json python -m uvicorn simulator.app:create_app --factory --host 127.0.0.1 --port 8314
```

Choose unused loopback ports and keep them consistent with bootstrap. Never point a clean-storage rehearsal at an existing institution service.

## Verify

First run the network-denied simulator contracts:

```text
python scripts/check_simulator_local.py --output /private/reports/local-contracts.json
```

Then run the local institution/database integration suite:

```text
CLAIM911_PROFILE_ROOT=/private/runtime/claim911-clean CLAIM911_SIM_CONFIG=/private/runtime/claim911-clean/sandbox/simulator.json CLAIM911_CORE_CONFIG=/private/runtime/claim911-clean/sandbox/coordinator.json python -m pytest -q tests/test_scenario_executor.py tests/test_checkpoint_verifier.py tests/test_workflow_services.py tests/test_callbacks.py tests/test_caregiver_progress.py tests/test_product_boundary.py --tb=short
```

The full executor test must reach all 13 checkpoints using explicitly offline call fixtures, recover the unsigned summary and independently verify institution evidence. Queue tests cover duplicate dispatch, expired work and uncertain execution. Product checks cover ownership, exact permission and cancellation. A clean runtime intentionally has no legacy-reader attachment, so that check is skipped rather than represented as verified legacy access.

Keep the generated private profiles and test evidence for inspection. Stop the two rehearsal servers when finished. Do not delete or reset the main project databases.

## Evidence obtained on 25 October 2026

The clean-storage rehearsal passed 32 checks with one expected legacy-reader skip. Two completed fixture runs reached checkpoint 13. Read-only inspection verified that the coordinator could not read institution tables and that the sandbox role could not connect to operational storage. Two bootstrap safety tests and idempotent configuration reuse also passed.

Recorded local evidence (historical local artifact, not included in this public release).

The host reused its installed Python dependencies and existing PostgreSQL service. Fresh dependency installation, complete frontend provisioning and a full Bolna run are still separate release requirements.
