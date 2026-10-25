# Claim911 product surfaces

Three local applications share components but enforce different roles through server-selected proxies and backend session scopes.

Use pinned dependencies from pnpm-lock.yaml. The tested build command is:

```sh
node scripts/build.mjs
```

Start separate processes from this directory:

```sh
CLAIM911_SURFACE=caregiver node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3110
CLAIM911_SURFACE=controller node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3120
CLAIM911_SURFACE=sandbox node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3130
```

The proxy uses operational product API 8120 for caregiver/controller and sandbox API 8121 for the sandbox. The Bolna voice gateway runs separately on loopback port 8125 and routes scoped operational calls to loopback port 8124 and scoped sandbox calls to loopback port 8126. See docs/VOICE_RUNBOOK.md for current sandbox validation. CLAIM911_API_URL is an optional server-only override. No provider or operator secret is included in browser bundles.

Run each API with CLAIM911_PROFILE_CONFIG pointing to its private coordinator.json and PYTHONPATH pointing to the claim911 source directory:

```sh
python -m uvicorn experience.app:create_app --factory --host 127.0.0.1 --port 8120
```

Create isolated profiles using scripts/bootstrap_profiles.py --runtime PRIVATE_RUNTIME, then scripts/bootstrap_legacy_reader.py --runtime PRIVATE_RUNTIME. These commands preserve the legacy database and do not rotate existing credentials. Sandbox calling must remain disabled and must contain no Bolna key.

Current implementation and pending acceptance gates are documented in ../docs/REDESIGN_STATUS.md.

For the bounded caregiver voice check, first create the English synthetic audio
through the isolated Azure Speech F0 broker with
`python ../scripts/prepare_bolna_smoke_audio.py` from this directory, then run
`python ../scripts/run_bolna_browser_smoke.py` from the workspace root with the
operational profile available. The harness uses Chromium's fake microphone,
starts one Bolna WebRTC browser session, stops it through the case-scoped API,
reconciles only that execution, and marks its case as synthetic. It does not
place a telephone call. The report is private to `work/claim911-runtime`; a
connected session without a complete participant turn and relevant assistant
reply is a failed smoke test.

For local accessibility evaluation, append `?audit=1` to a surface URL and choose **Run accessibility check** after opening the intended view. This uses pinned axe-core 4.14.0 and WCAG A/AA rules. The evaluation controls are absent from normal URLs. Automated checks supplement keyboard, responsive and visual verification. The repeatable sandbox journey audit is `node scripts/a11y-sandbox-smoke.mjs`; it uses the private sandbox workspace credential, reads existing synthetic runs and writes its report under `outputs/`.
