> Historical engineering notes. For the current demonstrated result and remaining limits, see the repository README and demo/evidence/completed-run.json.

# Approved redesign: implementation status

Current correction, 24 October: see `VOICE_SANDBOX_DECISION.md` and the top of
`PROGRESS.md`. Audio capture now uses absolute VAD/audio-clock windows; a real
local WebRTC regression recovered 1.3 seconds of speech lost by the previous
duration-only selection after an endpoint delay. Both scripted participant paths
use the actual question, refresh role-owned institution state, and report exact
document references. Scripted participants are the selected demo default.
Detailed Azure F0 recognition remains the existing fallback. The new code is
locally verified but has not completed a new Bolna session. Earlier status
entries below are historical and do not override this release limitation.

## Latest Bolna and sandbox status, 24 October

Latest update, 24 October: Bolna is pinned to Azure GPT-4.1 nano with a
200-token output cap. Its prompt now sets the same final sentence for caregiver,
hospital, billing, records, implant-store, TPA and insurer calls. The saved
prompt was read back and its new fingerprint is pinned in the sandbox profiles.
The participant harness uses Bolna's own transcript when available, avoiding a
duplicate speech-to-text request; bounded audio transcription remains the
fallback. Caregiver intake also requires its report to be saved and its
case-specific handoff spoken. “Let me check the case record” keeps the call
open. Local checks pass (265 backend tests, 73 gated skips and 16 focused Node
tests). The latest provider run still failed before these changes: its final
sentence was truncated and audio transcription failed. No post-fix Bolna run
has been made, so full workflow and voice behavior remain unverified.

Shared voice fixes now sit in common contracts, transport, transcript
evaluation and the agent prompt. Scenario objectives still decide what facts
and actions are valid. A common closing sentence ends the audio call; it never
substitutes for a saved report or independent checkpoint verification.

The default synthetic participant is a seeded deterministic actor, not the
Claim911 assistant. It uses the current assistant question, a role-specific
synthetic record and bounded rules to select its reply and permitted desk action.
Same input gives the same answer, which helps repeat tests and reduces inference
spend. It can sound repetitive and can miss paraphrases. The optional adaptive
participant uses a constrained model for more varied wording but costs
additional inference and depends on accurate recognition. Treat deterministic
runs as workflow regression evidence, not evidence of natural human dialogue.
The scripted demo still requires complete relevance and naturalness review.

The recorded Bolna review at
`../../Claim911_Bolna_Voice_Check/index.html` captures a real hosted browser
assistant exchange with synthetic caregiver audio. Two consecutive turns now
pass the provider transcript order and content checks. Both runs stopped at
checkpoint 0; neither made a Bolna report-tool write or advanced the discharge
case.

The adaptive participant harness now transcribes each live Bolna turn, gives
the utterance and prior dialogue to a budgeted model using only the selected
role's synthetic record, and returns a natural voice response through the
browser microphone. The participant model has no tools or workflow write path.
Transcription, model reply and voice generation each reserve against the existing
sandbox ledger, and its database profile must point to local `claim911_sandbox`.
This removes the two-question keyword
selector. The harness can also select an existing leased run and derives the
participant role from its current checkpoint. Eleven dialogue and role-routing
checks, 22 Python participant/workflow checks and syntax validation pass; no
live hosted session has exercised this newer path yet. Private profiles remain
present, while the sandbox product API and coordinator are stopped.

The complete scenario runner now defaults to a Bolna browser conversation
adapter. It connects each current voice checkpoint to a role-scoped synthetic
participant, permits only that desk's existing institution operations, archives
the provider-verified transcript and audio, and leaves checkpoint advancement to
the independent state verifier. The run pins the reviewed assistant
fingerprint, and the durable worker lease is renewed during long calls. This
transport is now selected from the run's pinned provider provenance through the
UI job queue, and the worker rejects a mismatch rather than silently changing
assistants. This integration has passed its offline focused checks but has not
yet completed a live workflow. The 13-checkpoint case, three fresh full-case
runs and release audio review remain open. Hindi remains deferred. No telephone
calls are needed for these repeat tests.

## Available locally

- Caregiver: http://127.0.0.1:3110/
- Operations controller: http://127.0.0.1:3120/
- Sandbox: http://127.0.0.1:3130/
- Product APIs: operational 8120, sandbox 8121. Legacy API and institutions remain separate on 8110 and 8111.
- Dedicated voice path: operational coordinator 8124 behind a narrow local gateway on 8125 and an approved temporary HTTPS tunnel. The gateway exposes only call-scoped voice tools and the Bolna webhook.

The caregiver does not enter an operator token. It receives a case-scoped capability session. Its case, document, activity and permission views are separated. The home screen mentions voice in its short introduction, and a saved case offers a browser voice session after explicit recording consent.

The controller requires its own credential and has a paginated, read-only legacy view with case-ID lookup and preserved document access. Its database credential has no write permission. Operational case coordination controls are still incomplete.

The sandbox requires a different credential and uses a separate database. Its coordinator and package worker have no Bolna API key or phone dispatch. A trusted loopback broker holds the provider key outside the sandbox package worker; the scenario runner is live locally, and Bolna browser sessions remain explicitly synthetic.

## Bolna connection status

Latest voice blocker result, 24 October: one actual Bolna browser exchange now
passes immediate-question and provider-transcript checks. Synthetic run
`964a0ad4-25f8-4f0e-ba29-e757891d2285` recognized the real opening, supplied the
caregiver answer, and captured Bolna's relevant document follow-up. The virtual
microphone now maintains a continuous silent RTP clock. Silero detects speech
boundaries in an isolated network-disabled worker, avoiding comfort-noise errors.
Bolna's conversational timing was narrowly tuned and re-pinned. This is one
exchange with zero case checkpoints, not the full demo or a release pass.
See `BOLNA_VOICE_TESTING_APPROACH.md` for the reproducible checks and remaining gates.

- The dedicated Claim911 Bolna agent now uses the reviewed English prompt, scoped Claim911 tools and authenticated webhook through the isolated operational gateway.
- Its saved configuration fingerprint is pinned in the private operational profile and matches the live provider configuration.
- Caregiver intake now uses English directly, responds to the reported blocker before asking one relevant follow-up, and never asks for language preference. A regression test covers the server-owned objective.
- Browser session creation is enabled for the operational caregiver surface only after case consent and recording consent. Phone dispatch remains disabled.
- The public gateway preflight verified gateway authentication, expired call-scope rejection and the absence of dashboard routes. The previous local gateway process was stopped after its upstream pointed at the product API instead of the coordinator API.
- The sandbox broker is now configured from the current operational tunnel URL, and both operational and sandbox call-scope preflights pass. The runtime profile and broker secrets are private files with owner-only permissions. The sandbox package worker has no provider key or broker mount.
- One actual Bolna browser session completed in the isolated sandbox with recorded-consent checked. Its authenticated provider callbacks were routed to the sandbox database, bound to the right conversation, and stored as a transcript plus recording reference. The conversation drawer now plays that recording through a case-checked API and trusted broker. This is one browser integration smoke, not a full workflow pass.
- The smoke transcript is relevant to the caregiver's reported blocker, but the assistant's response was cut off when the test ended. Natural turn-taking and question-aware role actors remain release blockers. The run has zero independently verified workflow checkpoints and is not counted toward the three full-case passes.
- One post-fix Bolna WebRTC browser exchange completed with a synthetic caregiver. The assistant acknowledged that final approval was pending and asked which document or information was missing. The transcript includes a recording and no language-preference detour. The prerecorded participant clip also caused an assistant acknowledgment to be cut short before a second user utterance, so this does not pass natural turn-taking. Private evidence is in `work/claim911-runtime/bolna-browser-prompt-fix-evidence.json`.
- Earlier failures are preserved privately. The first browser session captured only the greeting, a short audio window truncated the caregiver turn, a stale local API rejected a session before provider minting, and two later sessions disconnected without a transcript. The isolated replacement audio was verified through Azure Speech F0, but Bolna did not capture it. No telephone calls were placed. These failures do not count as passes.
- Pipecat runs and existing recordings remain clearly separate evidence. They do not count as Bolna assistant verification.

## Verified

- The full backend suite passes 162 tests with 55 environment-gated checks skipped. The six browser voice ownership and no-phone boundary tests also pass with the isolated runtime fixture and Bolna mocked.
- Caregiver ownership, operator boundaries, sandbox database isolation and read-only legacy access tested.
- Legacy document retrieval checked against case ownership.
- Browser-created synthetic request saved through the caregiver interface without an operator token.
- Browser verified the new landing page, focused case, document tab, controller legacy view and authenticated sandbox status.
- Next.js production build passed using webpack after the caregiver voice copy cleanup; all runtime UI dependency versions are pinned.
- Pipecat 1.13.0, its evaluation module and Azure STT/TTS/LLM services imported successfully in isolated Python 3.12.
- Sandbox actor adapters limit private knowledge and operations by desk. Unapproved dispatch and premature insurer decision are rejected.
- Existing Azure OpenAI resource has a deployed gpt-5-mini model. No keys retrieved, inference requests sent or cloud resources created. Credit balance is not yet verified.

## Still required

### Sandbox security baseline

A dedicated Colima VM (`claim911-sandbox`) now runs with host sharing disabled
and no forwarded SSH agent. VM mount inspection found no virtiofs, 9p or sshfs
shares. A digest-pinned Python container passed ten checks: non-root execution,
no capabilities, no privilege escalation, inaccessible host paths, no credential
environment, read-only root, loopback-only networking, and blocked internet,
host gateway and cloud metadata connections. Results are saved in
`../../Claim911_Sandbox_Isolation_Checks.json`.

This verifies only the network-disabled package probe. The trusted Bolna broker
now runs separately on loopback and has no database or institution credentials;
the sandbox package remains network-disabled and cannot reach it. Docker Compose
is not installed in this environment; the baseline was built and tested with the
Docker CLI.

### Remaining implementation

The trusted synthetic tool broker now enforces case/run/desk capabilities,
expiry, revocation, request size, per-worker tool budgets and idempotency.
Unknown execution results require reconciliation rather than automatic retry.
Four additional tests cover these boundaries, error redaction, and actual
synthetic medical-record release through the broker. The complete 118-test
backend suite passes. This is not yet a network-connected container runner or
a provider inference/speech broker; those remain required.

1. Finish caregiver-case and controller accessibility checks, then verify the full caregiver permissions, verified document presentation and live activity journeys. Hindi is deferred.
2. Add typed reasoning proposals, control decisions, callback scheduling, escalation and fresh-context enforcement.
3. Finish the durable sandbox scenario controls, role-private participant audio, clock controls and event/audio inspection. Pipecat remains a separate fixture path and is not evidence for Bolna assistant behavior.
4. Verify Azure credit eligibility/balance and configure inference and speech within the approved ceiling.
5. Build the automated synthetic participant audio harness, with Bolna as the only assistant and role-specific, question-aware synthetic participants. The sandbox broker and callback route are connected, but the participant audio loop is not.
6. Build question-responsive synthetic audio participants for the caregiver, hospital, TPA and insurer. Complete the 13-checkpoint case with Bolna as the only assistant, then complete three fresh passing Bolna browser runs, the mandatory failure suite, accessibility evaluation and human audio review. The one completed intake exchange above does not count as an end-to-end run. Hindi remains deferred. No telephone smoke test is part of repeat testing.
7. Package reproducible setup, container isolation checks, three-minute presentation, labeled replay, and complete license/cost reports.

A redesigned interface and passing backend tests are not proof that the audio MVP is complete. No new phone calls have been placed.

### 24 October: isolated Bolna browser and recording path

- Added `scripts/configure_sandbox_bolna.py` to create an allowlisted trusted-broker profile and route configuration. It uses the current URL from the operational profile so a stale tunnel note cannot misroute callbacks.
- Added a sandbox call-to-provider execution binding. The gateway retains execution-to-token-hash routes for the 15-minute sandbox call-token lifetime. A key-free `--webhook-only` worker processes callbacks without provider polling or call dispatch.
- The trusted broker now keeps a private seven-day recording allowlist and serves only a recording matched to the exact synthetic execution, call and incident. The sandbox API verifies run ownership before proxying the audio to the UI.
- One Bolna WebRTC sandbox smoke connected and ended, and Bolna returned a completed transcript and recording reference. The recording played through the sandbox UI. The transcript's final assistant sentence was cut off, and the run verified zero workflow checkpoints. This is compatibility evidence only, not a quality or end-to-end pass.
- Focused routing, broker, recording, worker-mode and binding tests pass. The full database-backed suite passes: 258 passed with one Starlette/httpx deprecation warning. The production UI build and case-scoped recording control check pass.
- Remaining: question-aware caregiver and institution audio actors, complete Bolna-driven 13-checkpoint case, dialogue evaluation and human review, three consecutive fresh full-case runs, fault suite, remaining accessibility journeys, network egress hardening for trusted provider components, spend reconciliation and final demo package.

## Decision layer increment

`coordinator/reasoning.py` defines versioned Observation, ActionProposal,
PolicyDecision and ExecutionResult contracts. The deterministic baseline planner
reads only the coordinator snapshot, proposes the next workflow action and cites
case evidence. Independent policy checks reject stale evidence/consent, expired
proposals, foreign citations and actions that skip the current gate. Permission
requests cannot grant approval, and a permitted proposal never authorizes dispatch.

The scoped controller decision endpoint is connected to a focused case-review
dialog. Browser verification opened the actual synthetic caregiver case, displayed
hospital reference discovery as the next action, and expanded its source evidence.
Screenshot: `../../Claim911_Controller_Decision_Review.png`. Production webpack
build passed; the full 122-test backend suite includes the endpoint's role boundary
and adversarial policy checks. Model-driven planning, durable callbacks and
execution-time integration of these proposals remain incomplete.

## Durable callbacks and caregiver permissions

The existing PostgreSQL coordinator now stores investigation callbacks with
deduplicated task keys, fresh proposals at claim time, bounded two-attempt leases,
preserved original query timestamps/deadlines, deadline escalation and explicit
uncertain-execution reconciliation. Lease loss never causes automatic redelivery.
Consent withdrawal immediately cancels waiting/running callbacks and invalidates
their leases. Callback reports cannot verify institution outcomes. The scoped
controller API supports scheduling/listing; automatic transport consumption is
not connected yet.

Caregiver-owned endpoints and UI now support investigation pause/resume and
separate exact-packet approval/withdrawal. Packet requests show recipient,
document identifiers and revisions. The backend rejects changed hashes and
foreign caregivers, records authenticated caregiver provenance, and invalidates
approval on document changes. Checked document labels use actual workflow
membership rather than upload alone. Browser verification paused and restored
the existing synthetic caregiver's investigation; screenshot saved as
`../../Claim911_Caregiver_Permission_Pause.png`. The exact packet UI compiled;
its API is integration-tested but a populated packet still needs browser QA.

All 126 backend tests and the production webpack build pass. Full Hindi
translation, callback worker/transport wiring and audio remain pending.

## Isolated audio and Azure validation

The actual Pipecat 1.13.0 image is now built from an allowlisted context with a
dependency lock and digest-pinned base. It loads an evaluation scenario and the
broker-only STT/conversation/TTS pipeline under non-root, read-only,
network-disabled restrictions. All ten isolation probes pass against this image.
This is offline image verification, not an executed audio conversation.

After the user completed portal sign-in, the subscription showed USD 132.50 credit
remaining and an enabled spending limit. The project ceiling remains USD 100.
A dedicated native Azure Speech F0 resource was created on the existing
subscription. Credentials are private to trusted provider configuration and are
not in the browser, Pipecat worker, images, environment variables or host mounts.

The separate standard-library provider image completed English and Hindi
synthesis-to-recognition tests. The first request failed with IncompleteRead;
a bounded diagnostic retry succeeded. The GPT-5 mini connection test returned
READY using 36 prompt and 10 completion tokens. USD 0.10 remains reserved pending
actual billing telemetry. No real calls or complete agent scenarios ran.

`sandbox/spend.py` implements durable, locked reservations, the approved phase
allocations, credit freshness, a USD 10 remaining-credit floor, duplicate request
protection and an over-bound charge suspension. The full 130-test suite passes.
Final worker/broker network topology, per-session HTTP capability integration,
end-to-end model tool use, Pipecat Evals execution and three fresh audio runs are
still required. One-shot provider validation used trusted fixed-destination code
with outbound access; it does not prove the final egress firewall topology.

Evidence: Claim911_Azure_Credit_Check.json, Claim911_Azure_Speech_Validation.json,
Claim911_Azure_Model_Validation.json, Claim911_Pipecat_Image_Check.json and
Claim911_Pipecat_Isolation_Checks.json in the outputs directory. Audio samples are
Claim911_Azure_Speech_en.wav and Claim911_Azure_Speech_hi.wav.

## Scoped gateway and real Pipecat turn

Added the scoped audio gateway and bounded stdio control bridge. The gateway binds
recognized input and synthesized output to one run/case/desk/language/consent
version, owns conversation context, reserves model cost before execution, and
withholds results if consent changes in flight. Five protocol tests cover those
boundaries, idempotency, unknown-result holds, budget failures and error redaction.

The actual Pipecat pipeline then completed a real synthetic STT/model/TTS turn in
8.891 seconds inside a network-disabled, read-only, non-root container. Only
bounded JSON audio operations crossed its stdio channel; no credentials entered
the worker. The trusted bridge checked returned audio/text against provider output
and revoked the session. Isolation probes passed on the updated image; no workers
were left running. Evidence: `Claim911_Pipecat_Real_Audio_Validation.json` and
`Claim911_Pipecat_Response.wav` in outputs. A separate real gateway-only turn is
recorded in `Claim911_Audio_Gateway_Validation.json`.

Three model validation requests now hold a combined USD 0.30 upper bound pending
billing telemetry. This is a reservation, not a claim of actual billed cost.
The full backend suite passed 135 tests before a small validation-order cleanup;
its focused gateway suite is rerun after that cleanup. Multi-desk tool execution,
Pipecat Evals/RTVI, scenario lifecycle controls, three fresh full-case audio runs,
complete Hindi journeys and the remaining release gates are still incomplete.

## Native sandbox tools and durable run lifecycle

Native SANDBOX_AUDIO conversations now use existing scoped coordinator report
tools without creating a phone participant or outbound dispatch job. The routes
exist only on an isolated, test-mode sandbox profile with phone credentials
absent. Report writes require a context refresh matching the latest material
case event; new uploaded evidence invalidates the old context. Legacy routing
correction tools are excluded from this workflow scope. Completed conversations
archive bounded PCM for every transcript turn, with hashes and case-bound WAV
retrieval. Archival does not verify an institution outcome, and completed evidence
is immutable.

`sandbox/runs.py` stores versioned manifests, language, case binding, public model
provenance, consent version, checkpoint cursor, synthetic clock and worker leases.
Pause/cancel requests are distinct from confirmed stops. Lost workers become
UNCERTAIN with no automatic retry. Reset creates a fresh run while preserving the
old audit. Checkpoints require an independent verifier callback, cannot skip gates,
and recheck consent. That callback's full-case implementation and the consuming
worker loop remain to be connected. Scenario preparation/list/control/clock APIs
are sandbox-session scoped; the start-audio UI remains disabled.

All 142 backend tests pass, including seven new native-call/run lifecycle tests.
The sandbox API was refreshed on 8121. No new provider requests or phone calls
were made in this increment. These backend controls do not establish an end-to-end
multi-desk audio scenario or three successful full-case runs.

## Independent verifier and first persistent audio checkpoint

`sandbox/checkpoints.py` independently checks every declared gate using core
records, scoped audio archives, content hashes, owning-desk document versions,
Ed25519 institution signatures and receiving-side records. Handoff revalidates
earlier gates to catch later version changes. Conversation quality scoring remains
separate. Its default rejects fixture-audio provenance; integration tests explicitly
allow offline audio fixtures and are not counted as real full-case voice runs.

`coordinator/model_tools.py` now gives the model only the reporting functions for
its current conversation purpose. It refreshes backend context before requesting
inference, validates model-selected arguments, rechecks execution authorization
before a write, and speaks the backend-confirmed result without a second hidden
model request. Call tokens never enter model messages or the package worker.
Caregiver intake is a native sandbox conversation purpose. The standard Azure
function-calling path is implemented in the trusted provider adapter.

A persistent synthetic institution/coordinator case has begun through real
Pipecat audio. The first attempt asked for read-back confirmation and correctly
failed to advance checkpoint 0. That conversation remains archived. After auditing
the terminated runner, the same case was continued without resetting evidence.
A later confirmed input produced an actual model-selected report tool write;
archived audio and the independent verifier passed caregiver_intake_confirmed.
The run is stopped at checkpoint 1 of 13 between implementation stages.

Evidence: `Claim911_Scenario_Intake_Validation.json` and the matching Intake Input
and Response WAV files in outputs. Persistent private identity:
`work/claim911-runtime/sandbox/active_audio_case.json`. Continue this case at
hospital reference discovery rather than starting another case blindly.

Five actual model requests hold USD 0.50 in conservative reservations: USD 0.30
integration and USD 0.20 development. Actual billing is still awaiting telemetry.
No phone calls or active one-shot containers remain. The multi-desk execution
loop, scenario UI controls, Pipecat Evals, full Hindi coverage, three fresh full-case
audio runs and remaining release gates are not yet complete.

## 2026-10-23: identifier pronunciation and interrupted-run recovery

Azure portal access and the credit-only gate are verified. The trusted provider
uses native SSML substitution to pronounce canonical hyphenated identifiers.
Three actual free-tier speech round trips recovered the exact admission, initial
approval and final-request identifiers. See
`Claim911_Identifier_Speech_Validation.json`. Provider image identity is pinned
when a controller instance starts, preventing a rebuilt tag from changing an
in-flight session.

Hospital reference discovery exposed an adaptive participant spelling problem.
Failed attempts are retained, including their actual completed audio turns.
The runner now archives partial conversations, revokes its audio grant and
acknowledges a safe pause when a provider or conversation operation fails.
A scoped abort operation closes a call that produced no audio, revokes its tool
token and requires reconciliation. It cannot modify completed audio evidence or
assert an institution outcome. Oversized participant audio is rejected before
entering the package worker or making an inference request. Participant prompts
retain canonical identifiers and provide one reference per response.

All 152 backend regression tests pass. This includes interruption cleanup and
pre-worker audio-bound checks. One harmless Starlette/httpx deprecation warning
remains. These checks do not establish a complete multi-desk voice demonstration.
Current checkpoint and conservative cost reservations are recorded separately in
`Claim911_Current_Sandbox_Status.json`; reservations are not actual billed cost.
The active implementation goal remains incomplete. No telephone calls were made.

The next medical-records participant adapter is implemented but not yet wired into
the complete scenario. It exposes only its own signed-summary release operation,
rechecks permission after inference and before the write, and supplies the real
institution result to its budgeted response request. Cross-role, extra-argument
and consent-revocation tests pass. The full backend suite now passes 156 tests.
Identifier clarification remains a demonstrated audio robustness limitation;
merged speech references must not be interpreted as a verified hospital report.

## 24 October: inspectable run/audio UI and caregiver updates

Sandbox run inspection is connected to isolated storage. The UI separates progress
from conversations, bounds conversation pages, opens transcript/audio in a dialog,
and serves WAV bytes only after run, case, call and artifact membership checks.
Saved Pipecat intake audio played in the browser. Explicit run origin separates
real-audio demonstrations from offline regression fixtures, without deleting either.
The complete scenario start/worker remains unavailable and is labelled accordingly.

Caregiver activity is now derived from safe event projections, with bounded
pagination and ownership checks. Conversation reads use the same case ownership.
Document owner/needed/checked states and a source-backed financial explanation are
implemented. These components have not yet been verified against a completed
redesigned full audio case. Final 165 backend checks and production build pass.

Azure sign-in and current credit verification are pending again after portal
timeouts. No new paid requests or telephone calls were placed in this continuation.
The active run remains at checkpoint 1 of 13. The current architecture and explicit
release gaps are in outputs/Claim911_Architecture_and_Release_Status.md.

## 24 October: complete executor integration and actual audio checkpoints

The complete 13-checkpoint executor is connected to trusted institution services,
real Pipecat audio and independent verification. The preserved audio case verified
caregiver intake, hospital references, the claims query and the corrected bill
(checkpoints 1 through 4). The medical-records conversation then exhausted its
bounded turns after repeatedly reporting the unsigned summary. The process exited
and the run is UNCERTAIN, with no automatic retry. Existing evidence is retained.

The stopping rule now accepts a confirmed unavailable document as the end of that
conversation, while keeping its checkpoint unverified and scheduling the owning-desk
callback. Ready documents still require checked uploaded evidence. Conversations
that exhaust their turns are archived as interrupted. Expired worker classification
now commits UNCERTAIN before returning an error, preventing silent re-execution.
All 180 backend regression checks pass. These fixes have not yet completed a fresh
full audio run. Azure portal credit was refreshed at US$130.93; conservative project
reservations remain separate from actual billing. No telephone call was placed.

A fresh synthetic audio run, ecebb08f-d16a-4853-9756-b9c92aabf1d3, is now
executing with the recovery fixes and has independently verified intake. Its
process is still active; the previous uncertain run remains preserved. Durable
sandbox execution requests now use the existing coordinator jobs table with a
SANDBOX_PHASE kind, per-run deduplication, current synthetic consent validation,
and refusal of uncertain runs. Explicit --run-id execution keeps each job's
identity file separate from the interactive active-run identity. Four focused
executor/queue checks pass. Queue consumption and the UI Start action remain
unconnected and are not advertised as available.

The existing durable worker now has an explicit --sandbox mode. It consumes only
SANDBOX_PHASE jobs, executes one bounded phase through the trusted runner, checks
actual saved checkpoint advancement, and queues the next phase only after verified
progress. Returned success flags do not satisfy this check. Lost/uncertain jobs
are not recycled; callback waits remain explicit. The runner supports --single-step
and rejects paid execution of regression-fixture origins. Six focused executor and
worker checks pass, including duplicate prevention and false-success rejection.
The fresh audio process remains active and has verified checkpoint 2. The worker
has not been started as a live service; UI Start and prepared-case binding remain
pending. No telephone dispatch was performed.

Prepared-case binding now uses a dedicated sandbox_runner token against a
sandbox-only institution seed endpoint. Repeated setup uses the run identity and
never overwrites institution records. Product API preparation receives only case
identity, without hidden answers or signing credentials. The Start endpoint binds
and queues eligible runs but remains disabled until execution readiness is enabled.
The UI Start action is wired to capabilities and remains hidden while unavailable.
Fresh-profile setup creates the scoped token with execution disabled. Existing
private profiles have not been changed. Preparation/access checks and the product
production build pass. The active fresh audio case has verified checkpoints 1–4;
the medical-records recovery step is next. No telephone dispatch occurred.

Short-lived worker heartbeats now gate API readiness and Start. Expired presence
returns unavailable instead of merely trusting a configuration flag. The trusted
worker maintains presence while executing a bounded phase. A private-profile
configuration script installs only the dedicated synthetic preparation token and
preserves the execution setting. The isolated institution API is running on 8114
and sandbox worker is running with --sandbox; product execution remains disabled
while the current CLI rehearsal completes, avoiding concurrent paid rehearsals.
Normal queue consumption excludes regression-fixture origins.

The fresh real-audio run has now verified checkpoint 5 after an actual unsigned
summary report, scheduled callback, synthetic clock advance, owning-desk release,
and independent signed-summary verification. This is the first verified audio
recovery of this complication. Full-case completion and three consecutive runs
remain unproven. No telephone calls were made.

The fresh audio case has verified checkpoints 6 (implant invoice) and 7 (exact
synthetic packet approval). Hospital dispatch conversation is still in progress;
no recipient receipt or full outcome is claimed. The sandbox now has authenticated,
resumable server-sent events containing only event sequence/type. The UI coalesces
updates, and the Next proxy forwards reconnect cursors and disconnect cancellation.
The stream's cursor/authentication/private-payload check and production build pass.

Hospital dispatch dialogue exposed cross-reference confusion when a caller supplied
a receiving-side query absent from the hospital's desk view. Scoped participant
operation descriptions now explain that the trusted portal binds exact packet
arguments and validates the request; staff must not substitute the final request
reference as a query identifier. This change is not loaded into the current active
conversation and requires a later verified conversation.

The fresh full-run process terminated at checkpoint 7 during dispatch-reference
confirmation. Owning-hospital inspection found exactly one existing dispatch.
Narrow reconciliation now requires an uncertain dispatch phase, no active call,
current consent/packet approval, exact institution packet equality and matching
uploaded dispatch proof. It restores PAUSED without advancing a checkpoint or
resubmitting. The actual case passed those checks; result is in
Claim911_Dispatch_Reconciliation.json. A bounded real audio confirmation is now
running (not a fresh submission). Uploaded UUID dispatch candidates are scoped to
case, patient and final reference and still require staff confirmation. Future
execution reports use unique filenames so recovery does not overwrite prior
execution reports; the first full-run report was separately preserved.

A reusable trusted CLI provides the same narrow recovery. All 187 backend tests
pass, including missing-dispatch rejection and no-duplicate reconciliation. Receipt,
final decision, clearance and full audio completion remain unverified.
The bounded confirmation process subsequently exited with REVIEW_REQUIRED; the
case is again UNCERTAIN at checkpoint 7. Do not treat reconciliation as successful
spoken confirmation. Inspect its preserved audio before another attempt.

The preserved confirmation transcript showed a correct canonical UUID read-back
followed by an ASR-spaced reference being saved. The scoped model bridge now refuses
to save dispatch-reference values that differ from the uploaded case-bound proof,
returns a clarification result, and does not let that rejected tool request end
the audio objective. Simulated staff now acknowledge exact identifier read-backs
without re-dictating the UUID. Five focused recovery/participant checks pass,
including rejection of the corrupted reference followed by an explicit confirmed
canonical report. After another evidence-backed reconciliation, the same case is
continuing in a new process. Existing dispatch and earlier evidence are preserved.
Checkpoint failures now carry the independent verifier reason into safe reports.

The corrected audio confirmation passed checkpoint 8, and independent receiving-side
verification passed checkpoint 9 on the same case. Only one hospital submission
exists; the interrupted attempts did not cause a duplicate packet. The recovered
runner is active on the remaining institution and handoff phases. The sandbox
product API was refreshed on 8121 to serve resumable events and readiness checks;
execution remains disabled to avoid a parallel paid rehearsal.

Pipecat Evals integration research confirmed an offline judging path for saved
conversations via EvalSimulationJudge, separate from a full WebSocket harness.
Official reference: https://docs.pipecat.ai/pipecat/evals/library . Integration must
keep package execution inside the isolated worker, meter any judge inference, and
keep conversational verdicts separate from authoritative state verification. It
has not yet been implemented or counted as a release gate.
The recovered process then exited with REVIEW_REQUIRED at checkpoint 9. Inspect
the TPA follow-up and institution state before retrying; checkpoints 10–13 are
still unverified. The earlier statement that it was active is superseded by this
terminal process result.

TPA follow-up inspection showed an identifier acknowledgement was incorrectly
interpreted as an answer to a query-status question. Participant instructions now
limit short exact-reference acknowledgements to identifier questions. Institution
status questions must use the actual owning-desk record. The audio completion
rule now requires verified query resolution/decision/clearance, plus a report
recorded after the owning-desk operation; an earlier pending report is insufficient.
Six focused completion/participant checks pass.

A narrow follow-up reconciliation rechecks every prior checkpoint, active-call
absence, current synthetic consent and owning-institution identity, then records
actual institution status without writing to that institution or advancing a gate.
Two integration recovery checks pass. The actual case reverified its first nine
gates and showed RESPONSE_RECEIVED, enhancement unlinked, no decision/clearance.
It is continuing on the same case in a new process. No real telephone calls occur.

The corrected TPA conversation and independent institution checks passed checkpoint
10. The runner is active on insurer review. Full backend regressions now pass 189
checks. Current public status and architecture documents were refreshed from the
authoritative database: 10/13 checkpoints, active run, US$21.10 conservative model
reservations across 211 requests (not confirmed billed spend), fresh credit gate,
and zero new telephone calls. Full completion is not claimed.

Sandbox run inspection now includes a source-backed Outcome tab, reusing the
caregiver financial explanation component. It stays unavailable until hospital
reconciliation has passed checkpoint 12, and separately labels whether the caregiver
handoff is complete. An offline completed-case integration check confirms INR
12,000 refund due remains NOT_VERIFIED for payment and every explanation statement
has a source reference. Both inspection checks and the production build pass.

Insurer dialogue inspection found its scoped review view omitted the final/claim
references needed to locate the caller's request. Its institution view now includes
its case references while still excluding receipts and hospital document contents.
Current desk records override initial briefing status, and the insurer objective
asks whether an eligible complete packet can be reviewed now without choosing its
outcome or amount. Eleven scoped actor/participant/service checks passed; four
actor checks additionally confirm the exact insurer reference fields. The current
active process predates these fixes; no new audio pass is claimed for them.
The earlier insurer process terminated with transcribe authorization 403 after its
bounded conversation lease expired. Evidence-backed follow-up reconciliation then
rechecked all ten prior gates and institution status. A new process is continuing
the same case with the corrected insurer reference view and review objective;
no decision or clearance is claimed yet.

## User scope update: Hindi deferred

On 24 October the user explicitly requested skipping Hindi until later. Complete
English intake, coordination and caregiver handoff remain required for the current
MVP. Hindi implementation/evaluation is now a deferred follow-up, not a current
release blocker. Existing tested language scaffolding is retained; no additional
Hindi provider checks or implementation will be pursued in this release.

Pending institution reports now continue with a scoped request for the owning desk
to perform its eligible review/reconciliation and upload its result, instead of a
generic acknowledgement that stalls the conversation. An agreed callback suppresses
that immediate request. The agent does not choose insurer outcome or amounts.
Three recovery/model integration checks pass, including a pending insurer report
that requests review while the institution decision remains absent until its own
operation. The active insurer conversation has subsequently obtained its institution
signed decision and is confirming the outcome; checkpoint 11 is not yet claimed.
The insurer conversation and independent signature/record verification passed
checkpoint 11. Hospital reconciliation and caregiver handoff remain. The same
synthetic case continues; no new submission or real telephone call was made.

Hospital reconciliation passed checkpoint 12. The first caregiver handoff produced
an overlong technical explanation and hit the existing speech response-size bound;
its process exited and partial evidence remains preserved. The handoff objective
now limits speech to short plain-English sections, avoids reading database/source
identifiers, and covers clearance, financial reconciliation, then refund due versus
payment. The synthetic caregiver asks for those sections in sequence. The handoff
cannot complete before four actual conversation turns and a saved caregiver report.
All twelve prior gates were independently rechecked before readout-only recovery;
no institution record was changed. A new final handoff process is active.

A portable offline replay exporter is implemented with a conspicuous RECORDED
REPLAY label, no external assets/scripts, escaped transcript content and local WAV
files bound to archived audio. It requires a completed AUDIO_DEMONSTRATION and a
fresh full independent audit with real audio required. Partial runs and fixture-only
proof cannot be exported as completed demonstrations. Two exporter checks pass.
No replay has yet been generated from the unfinished actual case.

The final English caregiver handoff completed all 13 gates on the same recovered
case. Fresh export-time independent verification passed with actual audio required.
Claim911_Recorded_Demo/index.html and capture.json preserve the labelled offline
replay and evidence references. The handoff transcript correctly explains INR
248,000 bill, INR 230,000 insurer payable, INR 18,000 patient share, INR 30,000
deposit, zero remaining balance and INR 12,000 refund due with payment unverified.
This proves one recovered case, not three fresh consecutive successes or the full
MVP release. Nine focused worker/inspection checks and the production build pass.
The worker supports opt-in synthetic callback acceleration; the UI exposes manual
clock advancement while paused without changing original receiving time.

## Sandbox UI execution enabled and verified

Refreshed the isolated worker/API/UI and enabled sandbox execution plus accelerated
synthetic callbacks after confirming no demonstration job was active. Browser UI
reset preserved the completed case, prepared a new AUDIO_DEMONSTRATION and Start
queued it. The trusted worker consumed that job and verified intake. Fresh run:
ee738b13-0a29-408f-b8e5-91b96cf33ba5. It is active; it does not yet count as a
consecutive full success. Regression fixtures are excluded from normal consumption.

Browser inspection verified the completed financial Outcome and unpaid-refund label.
It also caught a stale frontend compilation: newer sandbox styles were absent from
the built CSS despite successful incremental builds. Cleared only generated build
cache, rebuilt, confirmed the required CSS selectors in output and refreshed the
sandbox frontend. The corrected mobile layout is visually inspected and saved in
Claim911_UI_Started_Rehearsal.png. The audio worker continued during this frontend
refresh. Full accessibility and desktop checks remain pending.

## Conversation evaluation boundary work

The fresh UI-started rehearsal passed hospital references (2/13), then stopped on
an Azure speech IncompleteRead during synthesis. It is not counted as a consecutive
successful run. Existing worker logs and run evidence preserve the failure, and no
institution write is automatically repeated.

Added a separate credential-free Pipecat Evals stdio entrypoint using EvalJudge and
EvalSimulationJudge over saved conversations. Its typed classifier routes only
bounded classification questions to a trusted controller. The controller has no
case-writing tools, validates exact answer names/options and finite probabilities,
and labels results as posthoc conversation scoring, never state verification. A
network-disabled, read-only non-root evaluation container specification derives
from a pinned audio image. Trusted stdio execution is bounded by time, output size
and classification request count. Three pure boundary checks pass; scripts compile.

The evaluation image has NOT been built or run. Docker image inspection requested
through escalation was not executed because automatic approval review hit its
usage limit. This was a review-system failure, not a finding of unsafe behavior.
The approval boundary was not bypassed. Actual Pipecat Evals integration proof and
provider-backed scoring remain pending; local code work continued independently.

## Pipecat Evals executed after review reset

The automatic-review reset time passed and Docker inspection/build authorization
succeeded. Built a separate evaluation image from the pinned audio image with
--network none. A real-library protocol check using explicit classifier fixtures
passed, labelled as a fixture rather than conversation-quality evidence.

The completed caregiver handoff then passed actual model-backed Pipecat Evals:
plain-language score 1.0, institution-authority score 1.0 and goal yes. Scope is
FINAL_CAREGIVER_HANDOFF_ONLY; full dialogue-suite coverage remains pending. Five
classification requests reserved at most US$0.50, not confirmed billed cost.
Evidence: Claim911_Caregiver_Conversation_Evaluation.json. The package worker has
no network, host mounts or credentials; the trusted classifier has no case tools.

Normal frontend builds now clear only generated build cache and assert that key
caregiver/sandbox selectors exist in the compiled CSS. The new build command passes.
The trusted speech adapter now makes at most three reads only for IncompleteRead
on free speech, discarding partial responses. Model and institution actions are
not retried. Six focused evaluation/speech checks pass, and the provider image was
rebuilt without network access. A fresh English repeat run is active from clean
case state; the earlier failed UI run remains preserved and is not counted as a
consecutive success. All remaining original release gates still apply, except Hindi
which the user explicitly deferred.

## Accessibility checks and repeat-fixture correction

Pinned axe-core 4.14.0 from the standard registry with lifecycle scripts disabled.
Added an opt-in local ?audit=1 evaluation panel and Alt+Shift+A shortcut for dialog
checks; ordinary URLs do not show evaluation controls. Retained MPL-2.0 and bundled
third-party notices. Initial scan found three serious contrast failures in welcome
illustration labels. Darkened them and re-ran axe: welcome and empty intake dialog
have zero violations. Decorative-symbol contrast and Radix hidden-focus items were
manually reviewed, not silently counted as automated passes. Five Tab presses stayed
inside intake. Escape initially lost focus; added trigger focus restoration and
verified Escape now returns to “Tell us what’s happening”. Scoped results are in
Claim911_Accessibility_Caregiver.json and the screenshot in
Claim911_Caregiver_Accessibility_Fix.png. Other primary journeys still need checks.

The first fresh repeat stalled because the scripted caregiver did not answer a
preferred-language question. That bounded attempt exited and is not counted as a
successful repeat. The English fixture now states its preference in intake and can
answer a language clarification while keeping disclosure permission separate.
Three focused completion/fixture checks pass. A subsequent fresh case is active
and has passed checkpoints 1 and 2. It does not yet count as a complete success.
The latest clean frontend build and compiled-style checks pass.

## Bolna browser-session compatibility

Verified the official @bolna/web-call 3.0.1 SDK contract and pinned it from the
standard package registry with lifecycle scripts disabled. The backend provider
adapter mints only browser sessions, validates SDK fields, 120-second-style expiry,
matching agent identity and a secure Bolna WebSocket destination, and strips
unrecognized fields. It never exposes the long-lived API key and never retries an
uncertain mint. Two adapter checks pass. The existing account returned a valid
120-second session in an actual compatibility check. No microphone was opened,
no voice call started and no telephone dispatch occurred. Evidence is in
Claim911_Bolna_Browser_Compatibility.json. Case-bound product endpoints and browser
conversation validation remain pending; an installed SDK is not counted as complete
voice integration.

The latest fresh audio case stopped after repeated unsigned-summary callbacks,
with four checkpoints verified. It is excluded from successful-repeat counts.
Scheduled records follow-up now explicitly requests the treating-team release,
and a callback cannot close merely after another unavailable-document report;
it must obtain checked uploaded evidence. Thirteen scoped-model, completion and
executor checks pass. A new fresh English run is active with this correction.

### 24 October: full backend regression and fresh callback evidence

The complete backend suite now passes: 202 passed, with one dependency
deprecation warning. Two disabled-runner tests now explicitly disable execution
in their own configuration rather than depending on the mutable local profile.
The first unrestricted run exposed those assumptions; its failures are not
presented as product authorization failures or hidden by changing production
behavior. The successful rerun used the real local synthetic databases.

The current fresh English audio run has independently verified checkpoints
1 through 9, including the scheduled signed-summary callback, hospital dispatch
and receiving-side receipt. It remains in progress and is not counted as a
complete repeatability pass. The prior recovered 13-checkpoint case remains
separate evidence. Three consecutive fresh complete runs are still required.

### 24 October: case-bound browser voice implementation

Added an operational-only browser session endpoint and a case-owned caregiver
proxy. A session requires recording approval, current investigation permission,
an explicit configuration flag and a successful scoped-gateway preflight. The
backend commits session intent before contacting Bolna, gives only the short-lived
SDK session to the browser, and keeps the call tool token server-to-provider.
Uncertain mint results remain unretryable until reconciled. Consent changes during
mint withhold credentials and schedule a provider stop. No outbound telephone job
is created. Explicit stop invalidates tools immediately and reports provider stop
as unconfirmed until the existing worker verifies it.

The caregiver component uses the pinned official browser SDK, an explicit
recording checkbox, user-triggered microphone start and an end-conversation
control. It is hidden unless browser voice is configured. The local operational
profile has not been enabled: gateway configuration, worker supervision and an
actual browser conversation still need verification. This is implementation
evidence, not browser voice execution proof.

Four new boundary tests pass. Together with the existing worker and product
authorization suite, 29 focused tests pass. The production frontend build passes,
including required compiled component styles. The fresh audio run has meanwhile
verified checkpoint 11, including the institution-issued insurer decision.

## 24 October: Bolna participant-turn harness

Bolna remains the only assistant in the planned browser demo. Added a participant
turn adapter that transcribes the latest assistant audio, gives that exact turn to
one role-bounded synthetic actor, and synthesizes its reply using an allowlisted
English-India neural voice. The participant adapter cannot write a workflow fact
or qualify a checkpoint. Its scripted dialogue reuses the existing role actors;
its speech layer reuses the isolated fixed-destination provider worker.

Added a Playwright harness that supplies an in-memory microphone track, captures
Bolna's remote WebRTC audio, waits for the assistant turn to finish, and injects
the synthetic participant's spoken reply. It does not replace or imitate Bolna's
assistant. This is implementation evidence only: the dynamic audio harness has
not yet run against a live Bolna browser session, and the multi-role 13-gate
workflow is still not connected to it.

Role-specific voice IDs are allowlisted from Microsoft's current English-India
voice list. Hindi remains deferred. The complete suite passed 275 tests with both
operational and sandbox profiles enabled. Focused participant, voice-selection
and identifier-pronunciation checks passed, as did the harness JavaScript syntax
and pinned Bolna SDK import checks.

Next: run one consented synthetic caregiver exchange through the harness, inspect
the actual Bolna audio and transcript, then generalize to all role actors and
connect those conversations to the independent checkpoint verifier. Final
provider egress hardening, three fresh complete Bolna runs, full dialogue review,
remaining accessibility journeys, cost reconciliation and demo packaging remain
release gates.

## 24 October: provider balance failure and safe recovery

The latest browser attempt did not reach Bolna speech generation. Bolna's
execution endpoint returned `balance-low`, no transcript, and zero conversation
duration. The run remains failed and is not counted as a voice or workflow pass.
The earlier report that showed no audible audio was therefore a downstream
symptom, not a WebRTC capture defect.

The trusted broker now preserves this terminal provider status without
pretending a transcript exists. The harness reports the provider balance block
and uses an authenticated sandbox recovery endpoint to close the stranded call
for reconciliation. The affected call was reconciled as failed with no
institution outcome claimed. No new provider session or phone call was started.

The sandbox UI, product API, coordinator, Bolna broker, PostgreSQL and synthetic
institution service were reachable after restoring the product API. Full local
regression passed: 258 passed, 72 skipped. Python compilation, browser harness
syntax and the authenticated recovery route also passed.

The 13-checkpoint Bolna workflow and three fresh Bolna browser runs remain
blocked on a valid Bolna account balance. Azure credits do not fund Bolna
sessions. After Bolna execution is available, resume with a fresh synthetic
caregiver run, inspect the captured assistant speech, then test role-specific
desk conversations and the complete workflow. The daily Azure balance check
remains sufficient; provider execution status will be read as part of each
authorized test run.

## 24 October: all three product surfaces accessibility checked

Added a repeatable Playwright and axe-core audit for the caregiver and
operations surfaces, alongside the existing sandbox audit. The caregiver home,
intake dialog, operations queue, sandbox home, conversation list, conversation
drawer and outcome now all report zero axe violations. The caregiver intake
dialog traps focus, closes on Escape and returns focus to its opening control.
At 390px wide, all three surfaces have no horizontal overflow.

The audit found a stale Next.js process serving a missing CSS asset after a
production rebuild, followed by an undersized run-selection target. Restarted
the three UI processes against the current build, corrected the target, and
reran both audits. The operations audit reads the existing queue without
opening or changing cases. The production build passes. The audit reports are
`outputs/Claim911_Accessibility_Caregiver_Controller.json` and
`outputs/Claim911_Accessibility_Sandbox.json`.
