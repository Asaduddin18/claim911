> Historical engineering notes. For the current demonstrated result and remaining limits, see the repository README and demo/evidence/completed-run.json.

# Claim911 implementation status

Updated 24 October 2026. Overall goal remains incomplete. Institution records and outcomes are simulated.

## Current approved direction: adaptive people, deterministic institutions

The first adaptive audio rehearsal `5016b5cf-6f01-478e-ac74-62c5375173bc`
connected but stopped at checkpoint zero. Its caregiver response answered the
actual question. Bolna's ten-second idle check reprompted during synthetic
response preparation; delayed VAD draining then merged separate audio bouts
and exceeded the absolute capture-window bound. The failed recording and
transcript are preserved, with no checkpoint pass.

Capture now runs as a serialized background producer while the conversation
consumer waits on model and speech requests. It snapshots each finished utterance
immediately into a bounded queue. Standalone participant subprocesses are
asynchronous too. Two new local producer/consumer tests pass. The real local
WebRTC loopback also proves queued PCM survives after its original rolling-buffer
window expires, while unavailable windows still fail. 26 Node checks pass.
The dedicated sandbox timing profile uses 1200ms endpointing, a 45-second idle
check, a 60-second silence cap and a 300-second provider cap. It preserves the
model, voice and scoped tools. Provider readback and sandbox pin refresh are
being completed before another audio run. No operational pin is promoted.

Fresh text suite `Claim911_Participant_Text_Fresh_Evaluation.json` now passes all
10 independent scenarios across all seven roles. It used 10 bounded participant
requests and 20 text-judge requests, with no audio, Bolna session or institution
write. The corrected caregiver persona passes alongside language selection,
enhancement reference, wrong readback, unsigned summary, revised bill, implant
reference, TPA linkage, pending insurer decision and unpaid refund checks.

Each case is scored as its own conversation, with the participant as the output
under test. Strict numeric response schemas prevent malformed choice scores.
The audio runner now requires a fresh passing report with matching scenario,
participant implementation and provider-image hashes before it can start an
adaptive Bolna session. Literal versus exactly spelled identifier equivalence
also has a local voice-contract check; different codes remain rejected.
24 Node checks pass. Final backend regression is running before voice rehearsal.

The first complete voice rehearsal will use the plan's existing rehearsal cost
allocation. Development and rehearsal reservations remain separate under the
same approved overall ceiling. No top-up or paid-tier fallback was added.

The user approved replacing phrase-matching demo participants with bounded
adaptive role players. The existing scoped `DeskParticipant` is reused for every
desk and the caregiver. Role records remain private to their participant;
caregiver knowledge has a read-only adapter. Explicit allowed institution tools,
zero caller-chosen arguments and consent checks remain authoritative. Tool-call
envelopes are validated before any action. Invented identifiers and internal
field names are rejected. Fixed scripted actors remain available for regression
tests, while the full Bolna demo runner now defaults to adaptive participants.

385 backend and 23 Node checks passed after initial integration. Additional
targeted checks pass for the multi-role evaluation contract and strict structured
judge responses. The existing Pipecat Evals worker was expanded from its old
three-criterion handoff limit to a shared bounded twelve-criterion contract and
rebuilt offline. The provider adapter now supports closed numeric JSON schemas
for scoring, without adding tools or destinations. No extra framework or paid
service was introduced.

The first text-only run generated all ten role responses and preserved them in
`Claim911_Participant_Text_Evaluation.json`. Its initial evaluation failed at the
old worker contract. A saved-response scoring attempt also failed on malformed
choice output; neither is a pass. One caregiver answer incorrectly implied
independent verification. The family-member persona now explicitly forbids that
claim. Saved responses are being scored with strict schemas before the corrected
persona is run afresh. This evidence tests participants only, not Bolna or audio.

Azure management verification matched the deployed speech credential and F0 SKU
and established the last resource-write interval. 138 eligible speech holds,
USD 13.80 of conservative reservations, were settled to zero with saved proof.
Model holds, older ambiguous records, spending ceilings and resource settings
were unchanged. Successful new speech requests use the fresh profile-bound proof;
missing or stale proof keeps their hold. Budget tests now use connection-private
temporary tables and cannot depend on or change the development ledger balance.

No new Bolna audio run has been started during this participant redesign yet. Full
13-checkpoint validation, three consecutive fresh runs on one configuration and
human audio review remain open.

## Latest voice gate

The mini validation `356bd4bf-8fa6-46b9-adcd-1db9dd842a1f` also passed
caregiver intake. It stopped during hospital reference discovery after reaching
the bounded participant-turn limit. Mini asked the right reference questions;
the scripted participant missed “enhancement request reference,” then treated
the assistant's earlier reference mentions as the current request. Its final
readback also had uncertain audio recognition. No hospital checkpoint passed.

Shared participant parsing now selects the latest explicit question, retains
context for bare readback confirmations, and normalizes optional “request”
wording for every reference family. Polite action requests use one shared grammar
across institution roles. Added lossless letter/digit/hyphen normalization and
required completeness for a combined readback. A near identifier is never fuzzy
corrected. The shared Bolna prompt now asks for alphanumeric codes to be spelled.
48 targeted backend checks pass, including wrong and missing readback rejection;
the preceding full suite passed 367 checks. No new speech model was introduced.

The shorter prompt passed Bolna caregiver intake on run
`bac5b4bb-2e84-43eb-be3d-dd13376fa3ff`. It then failed hospital reference
discovery: the nano assistant repeated hold/verification announcements instead
of obtaining the remaining references. Checkpoint 1 remains verified; checkpoint
2 was not awarded. The harness had also answered hold announcements as if they
were questions. Shared turn handling now waits on hold announcements for every
role, keeps genuine questions actionable, and stops after repeated nonprogress.
Targeted transport and prompt tests pass.

Restored the previously configured Azure GPT-4.1 mini assistant, preserving the
200-token output bound, voice, scoped tools and shortened prompt. Complete
provider readback was verified before sandbox pins were updated. Operational
pins remain unpromoted. A fresh two-checkpoint validation is in progress; the
nano intake pass is historical evidence and does not count toward the three
required full runs on the new model configuration.

## Current continuation: session lifecycle and verification

361 backend regression checks pass with all isolated runtime profiles enabled.
The sandbox accessibility audit was refreshed on 24 October: four inspected
views report zero axe violations, conversation focus and dismissal pass, and
the 390px mobile layout has no horizontal overflow. Caregiver and controller
checks were also refreshed in this continuation.

Shared closing detection now normalizes spoken brand spacing and contractions.
Saved Bolna closing audio passes live Azure recognition and both closing checks;
tool preambles are ignored across all roles. Local Node voice checks total 22.
This is not proof of a complete provider workflow.

The interrupted mint for run `71d9b91c-25b9-48df-ac5b-c0b5735065e4` was
reconciled through Bolna's read-only history and execution endpoints. Execution
`3cd925d0-8e04-48a1-9b91-e166cd9ca5a4` matches the exact synthetic call,
is terminal failed, and has zero conversation time. The run remains UNCERTAIN;
no checkpoint was awarded. Evidence is `Claim911_Mint_Reconciliation.json`.

The broker now journals each mint stage without storing ephemeral credentials,
and duplicate attempts for the same call cannot mint again. A successful mint's
execution ID is saved before callback registration, so a later gateway failure
is reconcilable. The API timeout now exceeds the broker's bounded configuration,
mint and callback operations. An already-held uncertain run is idempotently
preserved when its worker reports the same failure, retaining the original error.

The following fresh attempt was withheld at CALLBACK_ROUTE_FAILED. The private
journal preserved its provider execution ID; read-only reconciliation confirmed
it terminal failed with zero conversation time. The callback tunnel hostname had
expired. Added an authenticated callback-registry readiness probe before minting:
an unavailable or mismatched public gateway now prevents any provider session
request. Renewed the tunnel, preserved all nonendpoint agent settings, verified
the complete provider readback, and updated only sandbox approval pins. The live
readiness probe returns 200 with the expected sandbox scope. These additional
checks pass locally, including immutable endpoint renewal and exact terminal
execution binding. A reusable `scripts/reconcile_bolna_mint.py` preserves terminal
evidence without releasing review holds or awarding checkpoints.

Fresh run `81534306-40b3-43b6-9181-57d47e8fa60b` connected, recorded its
caregiver report, spoke the shared closing, and ended. It remains a failure at
checkpoint zero: extra intake questions and an unsupported statement that the
concern had been reported to the hospital. Provider debug logs confirm the
correct objective and spoken outcome reached the assistant. The closing detector
and gateway worked; assistant instruction adherence did not pass.

Moved shared voice behavior to `coordinator/voice_prompt.py` and shortened the
common prompt to 3,724 characters. Fresh objectives own role procedures; the
common prompt defines truthfulness, permissions, report semantics and closing.
The same Azure GPT-4.1 nano model, output bound and voice remain selected. Added
a post-call rejection for unsupported intake claims of institution contact.
Scripted investigation offers now cover a semantic family of checking a reason,
rather than requiring the literal phrase “ask the hospital.” Targeted backend
checks pass and 23 Node voice checks pass; the preceding full backend suite
passed 364 checks. Fresh run `bac5b4bb-2e84-43eb-be3d-dd13376fa3ff` passed
`caregiver_intake_confirmed`, checkpoint 1, with the shorter prompt. The same
case is continuing to hospital reference discovery without changing its reviewed
configuration. The previous failed cases remain preserved.

Three complete consecutive provider runs and full audio review remain release
requirements. None of the above is a complete-case pass.

## Latest verified state after the bounded Bolna intake

357 backend regressions pass with all isolated profiles enabled; 20 Node voice
contract checks and the local WebRTC capture regression pass. The provider run
`421aaba5-eade-429c-bc29-4985767e8e4b` correctly heard the caregiver question,
supplied a relevant scripted answer, and saved the caregiver report. It still
failed release validation with zero checkpoints because the common closing
sentence was omitted. The run and its audio remain preserved as failures.

Live execution-transcript polling repeatedly returned 503 and was removed from
the participant response path. Existing Azure F0 STT handles live recognition;
Bolna's transcript remains required for post-call verification. A conflicting
short caregiver ending was corrected in the common prompt and tool result.
Successful report responses now include the shared closing instruction.
The report gateway also preserves confirmed dispatch references and callback
times, which its prior summary-only schema omitted. The provider prompt/tool
change was read back and pinned for the sandbox. Operational pins were not
promoted. Refresh the trusted sandbox services before another provider run.
The revised close and complete case remain unverified. No further paid run was
started after the user asked to review the tradeoffs.

## Current capture and scripted-participant correction

The latest local WebRTC regression reproduced the production endpoint wait and
proved that absolute audio-clock capture retained 1.3 seconds of voiced audio
lost by the previous duration-only tail selection. The captured range is now
independent of the 1.6-second wall-clock endpoint delay. Unavailable audio
windows fail explicitly. Both scripted paths require the actual heard question;
the older standalone path answering prewritten expected questions was removed.

Scripted participants remain the selected demo default. Desk records refresh
each turn, document owners provide exact released identifiers and revisions,
and claims status follows current institution records. Unsupported caregiver
questions request clarification. The final caregiver can receive each short
handoff section. Claims follow-up requests institution-owned resolution when
the verified received response remains pending. A participant failure now asks
the browser to end its session and save diagnostics before a bounded hard stop.

The existing Azure Speech F0 adapter supplies role voices and fallback STT;
it now returns service-ranked detailed recognition candidates and confidence.
No new speech model or participant LLM was added. The isolated adapter image
was rebuilt without provider calls, and its restricted egress topology passed.
See `VOICE_SANDBOX_DECISION.md` for alternatives and tradeoffs.

These changes have not yet completed a Bolna provider session or any of the
three required fresh full-case runs. They are local evidence, not release proof.
The entries below preserve earlier implementation history.

## Latest voice and cost update, 24 October

- The dedicated Bolna assistant is pinned to Azure GPT-4.1 nano with a 200-token
  output cap. The live provider readback matched the reviewed configuration.
  Its shared closing prompt is now updated and read back. The new fingerprint is
  pinned across the sandbox coordinator, broker and product profiles. No call
  or phone dispatch was made for this prompt edit.
- The synthetic participant harness now uses Bolna's own assistant transcript
  when it is available. This skips a duplicate speech-to-text request and uses
  bounded audio transcription only when provider text has not arrived. Scripted
  role responses remain the default, avoiding a separate participant LLM call.
- Every Bolna role now receives the same final line after its verified result:
  “Thanks, that's all I need for this call.” The sandbox ends on that line.
  Caregiver intake also requires its case-specific handoff and a saved report;
  a tool preamble such as “Let me check the case record” keeps the call open.
- Local verification: 265 backend tests passed, 73 environment-gated tests
  skipped, and 16 Node dialogue/audio tests passed. One existing Starlette
  deprecation warning remains.
- The latest actual Bolna run connected and ended but failed dialogue
  verification: its transcript stopped at “Thanks, I understand. Claim911,”
  while local speech recognition also failed. It verified zero case
  checkpoints and is not a pass. The transcript-based optimization and explicit
  close detector were added after that run and have not yet been tested against
  another Bolna session.

### Common fixes and purpose-specific rules

Common behavior lives in shared voice contracts and is applied to every role:
the latest Bolna transcript supplies assistant text when available, the audio
transcriber is a fallback, consecutive audio bouts are joined into one turn,
the same final sentence closes the browser call, and every conversation must
pass transcript checks. Purpose-specific objectives still own their facts and
tool permissions. For example, caregiver intake closes only after its report is
saved and its handoff is spoken; a hospital document call uses its own uploaded
proof check. The common close line never marks a workflow checkpoint complete.

The current default participant is a seeded, deterministic role actor. It reads
only the synthetic record for its desk, responds to the latest recognized
question through role-specific rules, and uses only that desk's allowed
operations. The same case and question produce the same response. This makes
failure diagnosis repeatable and avoids an extra participant-model request.
Its limitation is that wording is less varied and rule matching can miss an
unexpected paraphrase, so its audio alone is not proof of human realism. The
optional adaptive actor uses a separate role-bounded model and permitted
institution tools; it varies its wording, costs extra inference and can still
drift if speech recognition is wrong. Scripted participants remain the selected
demo path; naturalness and relevance still require full audio review.

## Verified local workflow

- Separate hospital, claims and coordinator PostgreSQL permissions, including denied cross-role writes.
- Separate initial preauthorization and final discharge authorization references.
- Hospital dispatch history, corrected revision submission, scoped claims lookup, Ed25519 recipient receipts and independent verification.
- Intake idempotency, consent versions, revocation, uploaded document provenance, exact correction approval and receipt-backed routing resolution.
- Full gateway/coordinator integration with mocked telephony for success, access refusal and withheld receipt. Only the hospital service submits corrections; a missing receipt never closes the incident.
- Next.js dashboard: incident states and timeline, transcripts, uploaded proof/bills/documents, attributed evidence, correction approval, receipt verification, next-step guidance and a test-fixture filter.
- Browser institution rehearsal: claims submission denied; hospital revision 2 independently appeared in claims queue and produced a signed simulated receipt.
- Latest full suite: 74 tests passed. Latest dashboard production build passed.

## Verified real voice behavior

Dedicated Bolna agent: `4392053e-ad9a-4bde-900d-1ae28886846b`.
Live rehearsal incident: `16eb4664-7ea3-4db3-af62-438798594f33`.

- User verified their own number and approved synthetic calls, recording, and the restricted Bolna/Cloudflare gateway connection.
- First attempt ended NO_ANSWER. Second attempt completed, lasting 114.2 seconds.
- Real transcript and a hospital statement from the voice tool persisted.
- The conversation confused a spoken initial reference with final authorization. Participant clarified in chat: PREAUTH-077 meant initial approval. A labeled manual clarification superseded the incorrectly scoped statement; original transcript remains unchanged. A later corrected live call has now confirmed final submission separately.
- Real recording metadata imported from `telephony_data.recording_url`. Audio retrieved through authenticated backend: 458784 bytes, audio/mpeg. Browser player loaded, played and paused it.
- Recording redirects are limited to the provider and observed provider recording bucket. The Bolna API key is not forwarded to storage.

## Current runtime behavior

- Dashboard and institution services bind to loopback; only the restricted voice gateway uses the approved temporary Cloudflare tunnel.
- Outbound hold is persisted and enforced by queue API, worker dispatch and controlled-call script. Follow-up participant readiness is pending.
- Observation-only worker processes existing statuses, webhooks and stop commands without outbound dispatch. Stop it before integration tests sharing the webhook inbox, then restart it afterward.
- Uncertain dispatch cannot automatically redial. Operator recovery checks execution identity and the original call-binding token before linking an execution.
- Consent withdrawal invalidates scoped tools, cancels undispatched jobs and queues provider stop requests. Only matching provider confirmation marks cancellation; inability to confirm remains visible. Provider documentation covers queued/scheduled stopping, so active-conversation termination is unproven.
- Identical statement retries reuse evidence. Changed references stale prior approval even without an explicit superseded ID. Active correction tools reject stale approval.
- Negative/unclear structured values do not establish routing evidence. Proposals cannot omit contradictory current evidence.

## Voice preference update

At the participant’s request, the dedicated agent now uses ElevenLabs Raju - Natural Conversationalist, listed by Bolna with an Indian accent, at 0.9 speaking speed. The API update succeeded and the saved voice ID/name/speed were read back and verified. This change has not yet been heard on a live call. Calls remain held pending readiness.

## Next live test

The revised dedicated agent was saved and read back. Its voice tool now carries explicit PREAUTHORIZATION versus FINAL_AUTHORIZATION scope. The prompt requires clarification of request type and exact reference read-back, does not treat initial approval as final submission, and does not infer submission timestamps from the current clock. Integration checks pass; revised conversational behavior needs an answered follow-up.

## Corrected live hospital result

The Raju test completed. The participant explicitly confirmed FINAL_AUTHORIZATION and HOSP-FINAL-1042, submitted one hour ago. The saved voice-tool statement uses that exact reference and request type. Transcript and consented recording were captured; authenticated audio retrieval returned 390816 bytes of audio/mpeg. Guidance advanced to CLAIMS_LOOKUP using the saved hospital assertion. The separate claims simulator lookup currently returns zero matches for the same patient/reference/type. Claims-role readiness is pending.

## Live incident dispatch proof

Hospital revision 1 for the live case was imported into the dashboard as hospital-original-dispatch.json (document 04867b05-a0f7-47b0-b805-3d397e4dc832). Browser verified its JSON preview and UPLOADED_UNVERIFIED label. No destination assertion or recipient receipt was manufactured; claims-call readiness remains pending.

## First live claims result

The claims call completed with transcript and recording, but no claims statement was saved. The agent tried an out-of-role hospital submission operation, which the backend denied, and ended while clarifying lookup scope. No discrepancy or receipt was invented. Context queries now include request_type on every carried-forward statement; the dedicated agent was updated for short claims-only questions and immediate recording once queue/reference/absence are confirmed. All 74 tests pass. Revised claims behavior remains unproven; calls held pending retry readiness.

## Successful live claims retry

The shortened retry completed and saved a claims-attributed NOT_RECEIVED statement for FINAL_AUTHORIZATION HOSP-FINAL-1042. The incident changed to DISCREPANCY_OPEN against the real hospital SUBMITTED assertion. Transcript captured and consented recording retrieved successfully (220032 bytes). Guidance now requests HOSPITAL_FOLLOWUP for the destination; original dispatch proof is already uploaded as unverified. No correction proposal or approval yet. Calls held pending hospital-role readiness.

## Hospital follow-up correction

The first live hospital follow-up completed without recording a destination or proposal; its transcript shows repeated intake questions and no destination response. The backend now supplies an explicit per-call objective in both initial provider data and fresh tool context. The dedicated agent prompt gives that objective priority, directing destination follow-up to use existing submission/non-receipt evidence instead of restarting intake. Full suite passed 74 tests; revised live behavior remains unproven. Source-conversation links were also built and browser-verified against the real claims assertion.

## Actual-model text regression gate

Bolna Agent Studio exposes Chat with agent for the current dedicated agent. It was exercised against isolated synthetic incidents with BOLNA_MOCK telephony and real scoped backend tools. No phone calls were placed. The model asked directly for destination, saved document-linked evidence, proposed correction and refused approval bypass. A refusal test caught a genuine missing ACCESS_REFUSED write and unsupported human-follow-up promise. The corrected prompt was retested in a fresh incident: ACCESS_REFUSED persisted and state became HUMAN_REVIEW with no actions/receipts. Both runs, including the failure, are retained in outputs/Claim911_Conversation_Testing.md and linked evidence. Tokens were expired and cleared from UI. Remaining text regressions must pass before requesting more participant calls.

## Remaining completion gates

1. Obtain claims-role readiness and verify the matching claims-desk lookup in a real call. Revised reference handling and separate final-request confirmation are now proven by the Raju hospital call.
2. Complete real claims lookup and hospital follow-up from collected facts, including an unscripted correction.
3. Upload hospital dispatch proof, propose an evidence-backed correction, and record exact caregiver approval.
4. Ask hospital to perform correction and independently verify the recipient receipt against corrected dispatch. Insurance decision must remain separate.
5. Verify transcripts/audio for subsequent calls and real refusal/missing-receipt failure rehearsals.
6. Complete inbound caregiver intake through an authorized provisioning path. No inbound number was found and no number purchase is authorized. Current phone route is outbound only.
7. Verify real uncertain-dispatch recovery and stop behavior if those conditions occur; current coverage is mocked integration evidence.
8. Audit the full evidence chain before declaring completion. Local operator authentication is a demo limitation; independently authenticated caregiver approval is not implemented.

## Evidence artifacts

- `outputs/Claim911_Verification_Status.md`: requirement-by-requirement audit.
- `outputs/Claim911_Verification_Snapshot.json`: credential-free current-state snapshot.
- `outputs/Claim911_Real_Call_Recording.png`: real recording player browser check.
- `outputs/Claim911_Institution_Browser_Receipt.json`: signed synthetic receipt from institution browser rehearsal.
- `outputs/Claim911_Manual_Verification.json`: eight-gate manual API reconstruction.

No mocked or manual conversation counts as a real provider call. Do not mark the goal complete from passing tests, the manual resolved case, or one answered hospital call.


23 October: 76 backend checks passed. Actual hosted-agent text retest for unknown final submission passed six backend outcome checks, including HUMAN_REVIEW and no unauthorized correction or receipt. Added hospital-only SUBMISSION_UNKNOWN handling and stale-action invalidation. Scoped webhook regression processing to execution IDs; known callbacks take priority over unmatched events. Phone calls remain on hold.


Complex discharge environment: implemented separate hospital/claims case stores, role-filtered desk views, institution document release, reference-bound dispatches, independently signed recipient receipts, enhancement linking, dedicated insurer decision authorization and hospital reconciliation. Live local API rehearsal passed 18 operations, with zero agent conversations or phone calls. Backend suite: 84 passed. Agent orchestration, caregiver packet approval and dashboard integration for this scenario remain pending. The prior routing case remains intact.


Complex coordinator milestone: query linked to an attributed claims conversation and uploaded query record; three desk-owned document tasks; current packet validation; approval bound to packet hash and consent version; independent Ed25519 receipt verification against hospital dispatch. Revisions invalidate approval, wrong admission and unsigned summary are rejected, and revoked consent blocks work. Added Discharge workflow dashboard with evidence links, packet review, approval and receipt state. Running-service manual rehearsal c90b5168-a8c1-4054-842d-c81f7775162d has five documents and one exact signed receipt, with insurance PENDING. Explicitly MANUAL_RECONSTRUCTION, zero agent conversations or phone calls. Browser checks confirmed patient ID, collected tasks, verified receipt and pending decision. Backend: 88 passed; dashboard build passed. Complex voice objectives/tools, query/ enhancement follow-up, final insurer decision and discharge/refund tracking in the coordinator remain pending.


Complex final institution evidence milestone: added distinct hospital and insurer Ed25519 issuer keys (coordinator holds public keys only), signed TPA query completion/enhancement linkage, signed insurer decision, and signed hospital reconciliation. Coordinator verifies issuer, case, query, packet hash, amounts and cross-event bindings. Replaying earlier checkpoints cannot regress later states. Denial remains DENIED and produces PATIENT_BALANCE_PENDING rather than invented clearance. Full running-service manual rehearsal 8b8cee32-5c9e-4348-979d-79f69b0b482a reached DISCHARGE_CLEARED with eight evidence documents, insurer AUTHORIZED and INR 12,000 refund due; refund payment remains NOT_VERIFIED. No agent conversations or phone calls in this rehearsal. Backend suite: 91 passed. Dashboard production build passed and browser verified decision, clearance and refund states. Complex voice objectives, tool integration and real-agent execution remain incomplete.


Complex voice integration: added eight purpose-specific call scopes, call-bound query discovery, hospital document reporting and non-verifying desk updates. Document readiness does not collect missing proof; existing uploaded proof is identity/hash/signature checked. Packet submission calls bind the exact approval hash at queue, dispatch and tool use; changes cancel pending dispatch or disable in-flight tools. Staff unavailability/callback reports are retained without scheduling an automatic call. Added portal complex call purposes and source-linked desk report visibility. Dedicated Bolna agent configured with six scoped tools and max_tokens 500. Backend: 94 passed; dashboard build passed. Hosted nested-JSON query tool test failed without saving a query. Replaced provider-facing interface with plain fields; local gateway checks pass, but hosted retest and reconnect both lost chat connection before save. Plain-field hosted behavior remains UNVERIFIED. No phone calls; outbound hold preserved; test token expired.


Hosted query discovery now verified: incident c606b30e-919f-410a-9c46-cd57c3cf72d1, eight outcome checks, correct query and three needed-document tasks, no packet approval or receipt, decision PENDING. Five exact visible message turns imported via test-only hosted-text evidence endpoint and labeled BOLNA_TEXT_SIMULATOR. Added immutable test-only transcript import that cannot replace real call transcripts. Full backend suite passed 95 checks.

Hosted billing follow-up exposed an actual scope error: after requesting bill-v2 upload, the agent asked billing whether the records-owned discharge summary was ready. Saved three visible turns and screenshot; backend state verification did not run because automatic permission review hit the account usage limit. Local fix removes cross-desk signature language from unrelated document objectives and filters document-call context to its assigned kind and reports. Two offline scope regressions pass. Fix is not deployed or hosted-retested; full backend rerun remains pending. The browser token field was cleared; do not claim manual backend token revocation. No telephone calls were placed.


Permission review resumed after account usage reset; the full suite initially passed 97 checks. Preserved failed billing conversations as hosted-text evidence. Added auditable VOICE_TOOL_USED events and an explicit document tool-result completion rule. Diagnosis found the public Cloudflare tunnel had disappeared while its process kept retrying: Cloudflare reported Tunnel not found and DNS failed. Renewed the previously approved gateway-only tunnel, verified authentication/scope enforcement and dashboard-route exclusion, and updated the dedicated Bolna agent.

Hosted billing retest now passed on the same synthetic incident c606b30e-919f-410a-9c46-cd57c3cf72d1: actual REPORT_DOCUMENT audit, bill-v2 for INR 248000 linked, two other documents still NEEDED, no packet approval, no receipt, insurance PENDING. Eight outcome checks passed; exact three-turn hosted transcript imported and token expired. Earlier false-completion and outage traces remain labeled failures. Added read-only public-gateway preflight; a real dispatch is cancelled before provider contact if tunnel/scope checks fail, with a visible reason. Backend suite: 101 passed. Current public preflight and dashboard build passed. Calls remain on hold. Remaining complex hosted/real voice phases are incomplete.


Same-case hosted records follow-up: six checks proved the unsigned-summary blocker remained pending. After the synthetic hospital signed and uploaded its record, the agent generated summary-signed_v1 instead of the spoken summary-signed. Backend did not silently substitute it. Added explicit REFERENCE_CONFIRMATION_REQUIRED with same-admission uploaded candidates; the agent requested confirmation, and the staff reply separated identifier from version. Correct signed summary then collected; eight final data checks passed. Retained the wording defect where the agent incorrectly attributed its generated suffix to staff. Exact-identifier schema guidance and neutral mismatch wording are deployed; wording retest pending.

Hosted implant-store follow-up: exact implant-invoice identifier and admission-matched proof collected, with nine outcome checks. Agent refused a request to self-approve/resend the packet or invent insurer approval; backend approval and receipt remained absent, decision PENDING. All three documents are now collected on incident c606b30e-919f-410a-9c46-cd57c3cf72d1. Exact packet exported as outputs/Claim911_Complex_Packet_Review.json and .md; approval remains NOT_APPROVED. Added plain-language spoken_outcome to avoid reading internal status codes; deployed prompt change needs hosted wording verification. Latest full backend suite: 101 passed. All new conversations are hosted text with explicit provenance; zero phone calls this phase.


Packet-ready dashboard verified in the browser: all three document tasks collected, separate caregiver approval unchecked, no verified response receipt, no insurer decision. Fixed stale polling errors by separating transient connection notices from action-validation errors; successful polls clear only connection notices. Production build passed and the reloaded portal showed no stale Failed to fetch notice. Exact packet approval, hospital submission and downstream voice phases remain pending.


Synthetic caregiver approval provenance implemented and deployed to the local core API. The approval endpoint accepts SYNTHETIC_REHEARSAL_FIXTURE only for test incidents, records a separate source and actor, and never represents a real caregiver decision. Real BOLNA packet-submission calls are blocked at scheduling, worker dispatch and call-tool access when approval comes from this fixture. Added integration coverage for non-test rejection, mock-to-real conversion, in-flight denial and real scheduling rejection. Full suite: 102 passed; dashboard production build passed. Dashboard includes an explicit fixture approval label; updated browser rendering still needs verification.

On the same hosted complex case c606b30e-919f-410a-9c46-cd57c3cf72d1, independently reread the current packet and compared its contents, hash and consent version to the saved packet review. Recorded a labeled synthetic caregiver role approval only. Evidence: outputs/Claim911_Complex_Synthetic_Approval.json. The earlier packet review remains the pre-approval snapshot. Current next step: HOSPITAL_SUBMISSION_AND_TPA_RECEIPT. No receipt exists; decision PENDING. Outbound hold remains true, no calls scheduled or placed. Hosted packet submission, downstream follow-ups, wording regressions and the bounded real-call proof remain pending. Core runtime session 36406, PID 29925.


Same-case submission phase: public gateway preflight passed. Prepared a mock-only PACKET_SUBMISSION call, but Bolna hosted chat showed Chat could not start on three attempts. Saved visible connection-failure screenshot. Initial DOM editor read appeared truncated; clipboard copy of the complete editor proved valid JSON with all 6157 characters, so truncation was editor virtualization, not established input corruption. No hosted conversation or dispatch statement was invented. Mock call 9c3219f3-0320-493b-aac9-017b0f9d3303 marked FAILED, call token expired, and connection-failure event saved. Browser token field cleared.

Continued the same case with explicitly labeled INSTITUTION_API_REHEARSAL: hospital dispatched only the approved packet; uploading dispatch left receipt absent; tampered claims receipt rejected; independently signed receiving-side receipt verified. Eight checks passed. Query completion and enhancement linkage remain unverified, insurer PENDING, discharge clearance absent. Next: TPA_QUERY_AND_ENHANCEMENT_FOLLOWUP. Evidence outputs/Claim911_Complex_Same_Case_Receipt_Rehearsal.json. This does not prove hosted submission coordination. Dashboard restarted session 58997 and browser verified fixture approval label, exact receipt status, pending insurer and downstream checkpoints; screenshot outputs/Claim911_Complex_Receipt_Portal.png. Calls remain on hold; zero telephone calls this phase.


Hosted TPA follow-up remained unavailable after page reload: chat could not start. Diagnostic local context retrieval returned HTTP 200 with correct TPA_QUERY_FOLLOWUP purpose. This is not a provider tool-call success. Added operator-authenticated test-only POST /calls/{cid}/text-failure for CONNECTION_NOT_STARTED: immutable event, FAILED state, token expiry, no fabricated transcript; rejects real-call mode, non-test incidents and existing transcript/report evidence. Regression proves next mock call can be queued after a failed attempt. Full backend suite 103 passed. Endpoint deployed; core session 54650 PID 32239.

Same-case TPA institution checkpoint verified via explicitly labeled INSTITUTION_API_REHEARSAL. Eight checks passed: tampered resolution rejected, upload alone not verified, signed ANSWERED and enhancement linkage accepted, original receipt timestamp preserved, insurer remains PENDING and discharge absent. Evidence outputs/Claim911_Complex_Same_Case_TPA_Checkpoint.json. Current next step INSURER_REVIEW. Hosted TPA coordination remains unproven. Portal visibly shows signed query/enhancement confirmation and no verified insurer decision; screenshot outputs/Claim911_Complex_TPA_Checkpoint_Portal.png. Hosted connection failure screenshot saved, token field cleared, failed mock token expired. No phone calls; hold preserved.


Same complex case reached DISCHARGE_CLEARED using signed institution API checkpoints. Twelve checks passed: exact insurer decision AUTHORIZED INR 230000, INR 248000 final bill, INR 18000 patient share, INR 30000 deposit, INR 12000 refund due and payment NOT_VERIFIED. Altered decision and false refund-paid records rejected. Evidence outputs/Claim911_Complex_Same_Case_Final_Checkpoints.json. Hosted insurer/discharge coordination and live voice remain unproven.

Corrected full rehearsal script to create a test incident and record SYNTHETIC_REHEARSAL_FIXTURE approval rather than operator caregiver attestation. Fresh rehearsal ebe71ee9-9b54-4804-b13b-c564c7274914 reproduced all institution gates with eight documents and zero phone calls. Evidence outputs/Claim911_Complex_Reproducible_Rehearsal.json. Added dashboard source-record buttons for signed TPA, insurer and hospital checkpoints, using their verification-event document IDs. Build passed; browser opened correct signed hospital record and displayed final arithmetic and payment-unverified status. Screenshot outputs/Claim911_Complex_Final_Checkpoints_Portal.png. Dashboard session 51453. Current-case audit reread both live records: complex has seven hosted-text conversations and two failed mocks, zero live calls, one verified receipt; original routing case has six BOLNA attempts, remains DISCREPANCY_OPEN with no receipt. Completion remains unproven.


Initial complex hospital discovery implemented. Intake reference_known=false ignores any supplied final reference and starts UNCONFIRMED_FINAL_REFERENCE. Claims discovery is blocked until the hospital confirms distinct initial, enhancement and final IDs. New HOSPITAL_REFERENCE_DISCOVERY purpose and call-bound claim911_report_references tool retain admission, submission uncertainty and source call as REPORTED_FROM_CALL, never verified receipt. Conflicting reports cannot silently overwrite; claims admission/enhancement mismatches require clarification. Fresh claims context carries the hospital report. Missing references can be reported as blockers. No hospital-table read by the coordinator. Dashboard supports unknown-reference intake and source-linked hospital reference display. Mock gateway integration covers role, duplicate refs, immutable replay, unknown submission and cross-call memory. Full suite 104 passed; dashboard build passed. Backend session 89635, gateway 98130, dashboard 62421. Dedicated Bolna agent update returned HTTP 200 and readback verified seven scoped tools, the existing voice preferences and gateway callback. This verifies configuration only, not hosted tool execution. Browser verified the intake reference field disappears when marked unknown; screenshot outputs/Claim911_Unknown_Reference_Intake.png. Hosted and real voice tests of this initial stage remain pending. Calls remain on hold.


Caregiver handoff implemented: deterministic caregiver_summary exposes source-attributed reported query, independently verified receipt, TPA closure, insurer decision and hospital reconciliation. Pending/missing gates remain explicit. It never promotes a spoken approval/payment claim; denial and balance-pending outcomes are preserved, revoked consent returns only the hold explanation. Added CAREGIVER_COMPLEX_UPDATE purpose with caregiver-only participant binding, explanation objective, question/human-help reporting and no claims-fact or decision writes. Complex call controls now support consenting caregiver participants. Portal shows the summary with source conversation, receipt and signed-record links. Current synthetic case summary verified via running API: five attributed statements, INR 12000 refund due, payment unverified. Artifact outputs/Claim911_Caregiver_Verified_Summary.json and screenshot outputs/Claim911_Caregiver_Update_Portal.png. Full backend suite 107 passed; dashboard build passed. Core session 67508 PID39209, dashboard62949. Hosted/live handoff and voice intake remain unverified; no calls placed and outbound hold preserved.


Hosted connectivity resumed for a fresh initial hospital discovery, root cause of earlier connection failures still unknown. Fresh case 47939ba3-6922-4df2-be0a-4410c6a9c5ec began with UNCONFIRMED_FINAL_REFERENCE. Actual claim911_report_references write saved three distinct hospital references and reported final dispatch, with no proof, receipt or insurer approval invented. Nine outcome checks passed; nine exact visible hosted turns imported, token expired. Model did not fetch claim911_context before questioning despite prompt instruction; preserved as a compliance limitation rather than claiming a complete protocol pass. Artifacts outputs/Claim911_Hosted_Hospital_Discovery_Transcript.json, _Results.json and .png.

On the same fresh case, actual hosted claims agent carried forward the hospital-discovered final request, obtained the missing exact original receiving timestamp, confirmed query/references/document set and used REPORT_QUERY. Nine outcome checks passed; seven exact visible turns imported and token expired. Three document tasks remain NEEDED, enhancement unlinked, insurer PENDING, no approval or response receipt. No false NOT_RECEIVED assertion. Artifacts outputs/Claim911_Fresh_Hosted_Claims_Transcript.json, _Results.json and .png. Portal shows hospital references with source conversation and the claims query with its separate source, original clock and missing tasks; screenshot outputs/Claim911_Fresh_Hosted_Handoff_Portal.png. This is hosted text, not a telephone demonstration. Calls remain on hold. Next continue document and downstream hosted phases on this fresh case.


Approved redesign implementation started. Read Sites skill and local preview guidance; this is local-only work. Preserved legacy evidence hashes and inventory in outputs/Claim911_Redesign_Baseline.json; cancelled the mock billing test interrupted by the user pause without inventing a transcript. Created separate operational/sandbox databases, unique role credentials and distinct issuer keys. Product API uses scoped HttpOnly capability sessions, caregiver case ownership, operator authentication and separate sandbox authentication. Sandbox startup rejects Bolna credentials/live calling. Added read-only legacy DB credential and controller evidence/document endpoints; no write grants.

New Next.js product surfaces on 3110/3120/3130 use Tailwind, official shadcn-generated Button, Radix Dialog/Tabs and Lucide. All runtime UI dependencies pinned. Calm light caregiver home, focused consented intake, case journey, document upload and separate tabs implemented. Browser created synthetic Ananya case without operator credentials; no automatic coordination or voice claimed. Subtle voice-first eyebrow and voice/text copy verified. Controller legacy evidence is paginated and read only; sandbox start disabled until runner is connected. Screenshots in outputs/Claim911_Redesign_*.png. Source and detailed pending gates in docs/REDESIGN_STATUS.md.

Full backend suite passed 114 tests including ownership, scope, database isolation, read-only legacy access and role-private actor adapters; last added legacy document case binding also passed the four profile-boundary tests. Production webpack build passed. Turbopack/PostCSS tried to bind a disallowed local worker port; webpack is the tested build command. Isolated Python 3.12 audio environment installed Pipecat 1.13.0 with azure/evals/webrtc extras; frames, evals, Azure STT/TTS/LLM imports passed, dependency lock saved. Versioned sandbox manifest defines roles, faults, checkpoints and limits. Actor adapters prevent wrong-desk operations, unapproved dispatch and premature insurer decisions; insurer-only review API added. No audio conversations or inference yet.

Azure CLI read-only discovery found an enabled MSDN-category subscription and existing eastus OpenAI deployments gpt-5-mini and text-embedding-3-small. No keys retrieved, no inference sent, no cloud resources created; available credit balance not yet verified. All phone calls remain on hold. Operational API session54491, sandbox API79032; frontend sessions are being refreshed after the latest build. Audio runner, reasoning/control completion, actual voice and Hindi evaluation, accessibility suite and final release gates remain incomplete.

Sandbox security continuation: previous goal turn made verified progress by creating a dedicated no-host-share Colima VM and passing ten network-disabled container checks. Added trusted sandbox/broker.py, with private capability issuance scoped to one run/case/desk, expiry/revocation, bounded tool budget and request size, idempotent replay and uncertain-result reconciliation. No arbitrary URL proxy or HTTP mint endpoint. Integration test exercised real synthetic medical-record tools without exposing institution credentials to a worker. Full regression suite now 118 passed. Provider/speech broker, final container network topology and audio runner remain disconnected and unverified. No inference spending or phone calls. Current known product sessions: API8120 session30555, API8121 session79032, caregiver66104, controller6562, sandbox10912. These are references, not fresh liveness evidence.

Decision-layer increment: added strict versioned Observation/ActionProposal/PolicyDecision/ExecutionResult contracts and deterministic evidence-based next-action planner. Policy rejects changed context/consent, expired or timezone-less proposals, unknown evidence citations and gate-skipping actions. No proposal authorizes dispatch or institution adjudication. Controller-only /v2/controller/cases/{id}/decisions is connected to the operational case-review dialog. Browser verified actual synthetic Ananya case, hospital reference discovery action and expanded intake/consent observations; screenshot outputs/Claim911_Controller_Decision_Review.png. Full 122-test suite and production webpack build passed. New live sessions: operational API95416, caregiver37079, controller36719, sandbox3979. Audio runner, provider broker, model-driven planning and durable callbacks still pending. No calls/inference.

Durable callbacks and permission increment: PostgreSQL workflow_callbacks now persists bounded two-attempt investigation callbacks, exact task deduplication, original receiving timestamp/deadline, fresh claim-time proposals, leases, uncertain-result holds, reconciliation and escalation. Consent withdrawal immediately cancels waiting/running leases; no callback report can verify institution outcomes. Controller APIs schedule/list only policy-approved investigations; automatic transport consumption still pending. Caregiver UI/API now pauses/resumes investigation and separately approves/withdraws exact document packets, showing recipient and document versions. Backend provenance AUTHENTICATED_CASE_CAREGIVER, stale hash rejection and case ownership verified. Doc checked state comes from workflow evidence membership. Browser paused/resumed existing synthetic Ananya case; screenshot outputs/Claim911_Caregiver_Permission_Pause.png. Full126 backend tests and webpack build pass. Updated live sessions operational42303, caregiver33997, controller57692, sandbox31133. Sandbox API8121 still older process79032, do not assume it has latest migrations/endpoints until refreshed. Audio/model/spend gates unconnected, no calls/inference.

Audio/provider increment: user completed Azure portal sign-in. Actual subscription overview verified132.50USD remaining from150USD starting credit, billing2026-10-19to2026-11-18, spending limit enabled; projectceiling remains100USD. Created native SpeechServicesF0 in dedicated synthetic sandbox resourcegroup, no new subscription or paidtierfallback. Existing gpt-5-mini deployment keys and F0 key stored only privatework/claim911-runtime/azure/provider.json0600, excluded fromimages/browser/Pipecatworker. Actual isolated Pipecatimage built from14KBallowlistedcontext, pipeline/evalscenario loaded withnetworknone/nonroot/readonly; all10boundarychecks passed onactualpackageimage. No host audio package execution. Added bounded broker-only PCM/STT/conversation/TTS processors, but livebroker/Evals transport unconnected. Separate trustedstdlib-only providerimage passed English/Hindi speech roundtrip; firstIncompleteRead failurepreserved, boundeddiagnosticretrysucceeded. Modelconnectiononly returnedREADY,46tokens(36prompt10completion), committedUSD0.10reservation held awaitingbillingtelemetry. Requestidentity privateazure/model-validation.json preventsblindrerun. sandbox/spend durablelockedreservations phasecaps creditfreshness6h remainingcreditfloor10USD and overboundcharge suspension tested. All130backendtests pass. Pipeline/provider checksdoNOTprovefullagentworkflow; finalrestrictednetworktopology and per-sessionbroker remainpending. Evidence outputs/Claim911_Azure_*.json/wav and Claim911_Pipecat_*.json. No telephonecalls.

Scoped audio increment: previousgoalturnmadeverifiedprogresswithAzurecreditcheck,F0speechandmodelconnection. Added sandbox/audio_gateway.py withprivategrantissuer only, run/case/desk/language/consentversion binding, contextownedbybroker, strictrecognizedutterance->model->exactresponseTTS sequence, expiry/revocation includinginflightresultwithholding, perrequestidempotency,20turn/60requestcaps, budget-before-model hooks anduncertainresultnoretry. Full135backendtests passed; fivefocusedgatewaytests passedaftervalidationordercleanup. Added run_stdio.py inactualPipecatimage and sandbox/stdio_control.py trustedbridge: worker staysnetworknone and receivesnofilemounts,noproviderkeys,nocapability,nodbcredential. Boundedstdin/stdoutonly, maxoutput/requestcount/duration, uniqueownedcontainercleanup, PCM/textmustmatchtrustedprovideroutputs. Offlineframefixturepassedbeforeactualspend. Realgatewaychainpassed157tokens; actualisolatedPipecatpipelinepassed159tokens in8.891sec, inputsyntheticTTSfixture, outputfocusedmedicalrecordsquestion. No institutiontools orfullcaseworkflow executed. Bothsessionsrevoked; noone-shotworkersrunning. Added outputs/Claim911_Audio_Gateway_Validation.json/_Response.wav and Claim911_Pipecat_Real_Audio_Validation.json/_Response.wav; tenisolationchecksrepassedexactupdatedimage. Reproducibleone-shot script outputs/claim911/scripts/validate_audio_pipeline.py refusesexistingvalidationidentity. Privateidentities azure/audio-gateway-validation.json and pipecat-validation.json preventblindrerun. Totalmodelreservationsnow0.30USD pendingactualbillingtelemetry. PipecatEvals/RTVI, adaptiverolecallers, fullmultidesktools/scenariolifecycle andremainingreleasegatespending. No phonecalls. Productserversunchangedthisincrement.

Nativeaudio/runlifecycle increment: previousgoalturnmadeverifiedprogressactualisolatedPipecatSTT/model/TTS. Added coordinator/sandbox_calls.py installedonlyenvironment=sandbox,test_mode=true,noBolnakey/livecalls. OpenednativeSANDBOX_AUDIOcallsIN_PROGRESSwithscopedtools, no participants/outboundjobs. Freshcontextmaterialeventsequenceenforcedbefore native reference/workflow/statementwrites; newevidenceinvalidatesoldcontext; nativelegacyroutingproposetooldenied. Completedtranscripts requireboundedPCMperturn, case-boundhashedimmutablearchive andWAVretrieval; no institutionoutcomeverificationfromarchive. Addedsandbox/runs.pydurablemanifest/modelprovenance/consentversion/checkpoint/clock/lease state. Pause/cancelrequested distinctfromackstop; lostworkerUNCERTAIN noauto retry; resetpreservesoldrun; checkpointstrictsequence andindependentverifycallbackmandatory. Fullverifiercallback/consumingworkerlooppending. SandboxAPIv2prepare/list/control/clock scopedtosandboxrole; preparationdoesnotexecuteaudio. All142backendtests pass(sevennewnativecall/runlifecycle). RefreshedsandboxAPI8121, new sessionrecord in next entry. No cloudrequests/calls thisincrement; priorreservationsstill0.30USD upperbound awaitingbilling. ProductUIunchangedaudio-startdisabled.
Sandbox API8121 refreshed session85093, process70466. Other product/legacy services were not restarted. Full scenario verifier, role-private adaptive dialogues, faults, final full-case evaluations and product release gates remain incomplete.

Checkpoint/tool increment: independent sandbox/checkpoints.py verifies13gatesfromcore/audiobyteshashes/owningdeskrecords/issuerEd25519/receiverrecords/financialarithmetic. Finalhandoffrechecksallpriorgates; defaultrequiresPIPECAT_STDIOprovenance, contracttestsallowexplicitAUDIO_FIXTUREandarenotrealE2Eruns. Nativecallsnowrecordprovenance andexposecaseboundartifactmetadata. AddedCAREGIVER_INTAKEpurpose/reportevent. ScopedToolModelrefreshescontext, exposesonlypurposevalidfunctionschemas, validatesarguments, rechecksrunleaseauthorizationbeforewrite, andspeaksbackendconfirmedresult; nocalltokeninmodelorworker. ProviderAzureModelstandardfunctioncalling+singleparallel-disabledtoolcallpathupdated,builtimage. Integratedtestsnegativeunsignedsummary,dispatchwithoutreceipt,changedownerrecord,rolewrongtool/stalecontext. Addedboundedconversationshelperwithadaptiveactorcallbackandknownincompleteresultatturnlimit. Persistentactualcase: runb3bdbc87-2753-4a8e-8946-a2f2520d9a43 incidentb6edc0f8-0d27-4d4a-bd51-7204a1480af3 institutioncaseinprivateactive_audio_case.json. Firstnativeintakeactualmodelaskedreadback,noREPORT_UPDATE; verifierrefusedadvanceandrunner61339terminatedexit1, archivedcall6b43db1a-c44c-4181-beab-7d38239f51f1 preserved. Auditedterminalrunner/allcallscompleted, pauseackoldlease; explicitcontinueonSAMECASErun16407passednativeintakeviaactualmodelselectedclaim911_report_update, call201ab45d-f2f6-4a36-9a4d-c6ff8445ed1d, realPipecat/audioarchiveverifiedcheckpoint1. CurrentrunPAUSEDbetweenimplementationstages; GOALremainsactive. Nexthospitalrefscheckpoint2. ActualcontinuationreportedonePipecatturn; adaptiveactorcallbackimplementedbutnotneededonthatturn. Fivepaidmodelrequestreservations0.50USDheld(0.30integration+0.20development), telemetryunreconciled. No one-shotcontainersremaining/no phonecalls. Artifactoutputs/Claim911_Scenario_Intake_Validation.json andInput/Response.wav. Sourceoutputs/claim911/scripts/start_sandbox_audio_case.py defaultrefusesexistingidentity; --continue-intakeonlypausedcursor0, doNOTuseoncheckpoint1. Full146regressionsplus2focusedconversationtests passed; finalfull148runpendingresultnextentry. Fullmultideskloop/evals/UI/Hindi/finalgatesstillpending.
Final full regression suite result:148passed (no provider calls in that suite). No frontend changes/build this increment. Live product processes were not refreshed; scripts used current-source isolated TestClients and persisted sandbox records. Backend scenario UI still advertises runner unavailable, accurately.

### 2026-10-23: reviewed hospital audio failures and recovery

- Verified native identifier pronunciation with three exact real speech round trips.
- Pinned the trusted provider image identity for each execution session.
- Preserved interrupted hospital conversations and reconciled the stale lease.
- Added safe interruption handling, a scoped no-audio abort operation, and a
  pre-worker 20-second participant audio bound.
- Passed all 152 backend regression checks. No real calls were placed.
- Full scenario, three fresh successful audio runs, Pipecat Evals, complete Hindi,
  browser voice validation, sandbox controls and final release packaging remain open.

### 2026-10-24: run inspection and caregiver evidence UI

- The last real-audio attempt stopped at the reply boundary with HTTP 503. It
  remains archived at checkpoint 1 of 13. No uncertain request was automatically
  repeated. Structured diagnostics now preserve the operation/status and redact
  provider account details, rather than reducing failures to an opaque worker EOF.
- Provider message validation now supports the scoped participant tool-result
  exchange. Other-desk operations, unmatched tool results and extra arguments are
  rejected. The new provider source has not yet been rebuilt/validated through a
  live institution operation.
- Added a repeatable role-private scripted desk adapter alongside adaptive actors.
  Captured declarative-request phrases have offline coverage. The corrected full
  hospital/claims audio path remains unverified.
- Implemented sandbox run details, explicit scenario origin, independent checkpoint
  states, transcript drawers, and case/run/call-bound WAV routes. Real browser
  playback of the preserved intake succeeded. Screenshot:
  outputs/Claim911_Sandbox_Audio_Inspector.png. Verification fixtures remain
  separate from the default audio demonstration list.
- Replaced caregiver placeholder activity with owned, paginated event projections
  and conversation routes. Added institution document ownership/readiness, a
  source-backed outcome component, and a financial breakdown that keeps refund
  due separate from payment. Full rendered outcome needs a completed case.
- Final backend regression: 165 passed, one harmless Starlette/httpx deprecation.
  Product webpack production build passed. No inference or telephone requests
  were made during this continuation. Provider reservations remain held pending
  billing reconciliation.
- Azure portal sign-in expired. Two fresh portal attempts timed out. Requested
  user sign-in and retained the Azure handoff tab. Six-hour credit freshness gate
  is stale, so new inference remains disabled pending refreshed evidence.
- Current product sessions: operational API8120 session29404 PID99014; sandbox
  API8121 session20615 PID99186 (refresh pending latest list ordering only).
  Caregiver3110 session98592, controller3120 session32811, sandbox3130 session80139.
- Architecture and full outstanding release audit saved as
  outputs/Claim911_Architecture_and_Release_Status.md. Goal remains active.

Final preview refresh: sandbox API8121 is session99465 PID2373. Frontend sessions
remain caregiver98592/controller32811/sandbox80139. Browser verified the refreshed
Progress/Conversations tabs, five-item conversation pagination, current real-audio
run selection and recorded intake playback. Final full suite remains 165 passed.
Conservative provider reservations total USD 5.90; this is not confirmed billing.

### 2026-10-24: Bolna-led evaluation pattern and sandbox routing groundwork

- Rechecked current saved evidence before the release answer. Bolna browser session
  compatibility passed with a 120-second ephemeral session. One synthetic Bolna
  browser exchange completed and was recorded, but a scripted second participant
  utterance interrupted the assistant acknowledgment. This is not a natural-turn
  or full-workflow pass.
- Confirmed a separate saved synthetic Pipecat run passed all thirteen independent
  state checkpoints. Its report explicitly says conversation quality was not
  evaluated, so it does not satisfy the approved Bolna-led demo gate.
- Added `docs/BOLNA_VOICE_TESTING_APPROACH.md`, matching common practice with fast
  scripted tests, slower real-audio checks, adaptive role-bounded participants,
  and independent state verification. It records where Bolna Web-Call, Playwright,
  pytest, Pipecat Evals and axe-core fit, including that Pipecat assistant runs do
  not prove Bolna behavior.
- Added optional sandbox-token routing to the existing public voice gateway. Tokens
  with the `sbx_` prefix can route only to a separately configured local sandbox
  coordinator, while other tool tokens keep the operational upstream. Sandbox
  webhook routing uses a distinct downstream secret and fails closed if missing.
  Added sandbox-scope preflight and tests. This is code groundwork only: the
  sandbox coordinator target, trusted Bolna session broker and run lifecycle are
  not connected yet.
- Verification: three sandbox gateway routing tests, four gateway preflight tests,
  and five local-upstream boundary tests pass. Full suite was not run in this
  increment. No provider session, inference request or telephone call was made.

### 2026-10-24: conversation mismatch evaluation gate

- Added `sandbox/dialogue_quality.py` for post-call scoring that is explicitly
  separate from checkpoint verification. It records the assistant transport,
  role, quality scores, deterministic intake-topic mismatches and whether any
  critical dialogue checks failed.
- Reused the existing typed, tool-free evaluation classifier. The judge receives
  only the bounded transcript and role-specific synthetic facts. It cannot invoke
  institution tools, verify case state or make a run checkpoint eligible.
- Added a deterministic guard for the previously observed language-question and
  consent-answer mismatch. A high model score cannot override that mismatch.
- Added tests for provenance, bounded transcript shape, no-tool evaluation,
  independent state-verification status and the known mismatch.
- Focused verification: 16 tests passed. The full database-backed regression
  suite and connection of this evaluator to run artifacts remain pending. No
  provider session, model request or telephone call was made.

### 2026-10-24: sandbox Bolna session route

- Connected the sandbox controller to the trusted local Bolna broker. It binds a
  fresh run to the isolated synthetic institution case, opens one caregiver
  intake call with `BOLNA_WEBRTC` provenance, fetches its current scoped context,
  and sends the short-lived call token only from the sandbox API to the broker.
- The route accepts only a loopback broker on port 8127, verifies the expected
  assistant fingerprint and sandbox case binding, and returns only the ephemeral
  browser session. A Bolna-configured run cannot also be started through the
  separate Pipecat worker. Added a consented browser voice check in the sandbox UI.
- This path is not enabled in the current private runtime: sandbox broker URL,
  broker token and reviewed fingerprint are absent. No provider session was
  minted, and no phone call or model request was made. The browser check does not
  yet run role-specific participant actors, archive provider audio by turn, score
  dialogue quality, or advance checkpoints.
- Verification: full backend suite passed, 246 tests. Product production build
  passed. Focused sandbox, gateway and broker suite passed, 32 tests. One existing
  Starlette/httpx deprecation warning remains.
- Extended the deterministic role participant to all seven synthetic roles. Each
  reply now answers from only its own current record for billing, medical records,
  implant store, insurer, caregiver, hospital insurance and TPA. Missing owner
  facts produce an explicit uncertainty response. Twelve focused actor and
  document-turn tests pass.
- Tested the possibility of a local macOS speech-recognition loop using synthetic
  speech. The machine reports that Speech recognition is not authorized, so no
  permission prompt was opened and no network speech fallback was used. The Bolna
  browser SDK exposes connection and call lifecycle events, not a streaming
  transcript event, so automated adaptive replies still need a permitted local
  or credit-verified speech-to-text adapter.

### 2026-10-24: release regression recheck

- Re-ran the complete database-backed suite against the isolated local sandbox
  database: 246 passed, with one Starlette/httpx deprecation warning. The default
  execution sandbox cannot reach the local database, so the verification used the
  approved local test-service access. An initial restricted run produced database
  connection errors and is not counted as product failures.
- Updated the architecture and progress records to match the verified test count.
  This regression validates backend behavior, not live Bolna compatibility or
  dialogue quality. No Bolna session, phone call, or paid inference request was
  made during this recheck.

### 2026-10-24: sandbox accessibility and responsive release check

- Added a repeatable Playwright and axe-core audit for the running sandbox UI.
  It uses a short-lived sandbox session, reads existing synthetic runs, and
  checks the home, run conversation list, conversation drawer and outcome.
- The first scan found low-contrast status text and outcome labels. Darkened
  those colors and fixed conversation-dialog focus restoration. The final audit
  reports zero axe violations on all four views, traps keyboard focus in the
  dialog, closes it on Escape and returns focus to its opening row. The 390px
  mobile view has no horizontal overflow.
- Evidence: `outputs/Claim911_Accessibility_Sandbox.json` and
  `outputs/Claim911_Sandbox_Mobile_A11y.png`. The production build passes. The
  existing sandbox UI server was refreshed after the build and all referenced
  CSS and JavaScript assets return HTTP 200.
- Extended the Playwright and axe-core coverage to the caregiver home and intake
  dialog and the operations queue. All audited views now report zero axe
  violations. The intake traps keyboard focus, closes on Escape and restores
  focus to its opening control. All three surfaces fit a 390px viewport without
  horizontal overflow. The controller check reads the existing queue without
  opening or changing cases.
- A stale Next.js process served a missing CSS asset after the production build.
  Restarting all three UI surfaces loaded the rebuilt stylesheet; the sandbox
  audit then exposed and helped correct undersized run-selection targets. The
  final audit was rerun against the refreshed servers.
- Evidence: `outputs/Claim911_Accessibility_Caregiver_Controller.json` and
  `outputs/Claim911_Accessibility_Sandbox.json`. Repeat with
  `node scripts/a11y-caregiver-controller-smoke.mjs` and
  `node scripts/a11y-sandbox-smoke.mjs` from the product directory.

## 24 October: semantic recognition gate and current verification

The adaptive caregiver attempt c446e333 ended cleanly with captured reply and common closing. It remained failed at checkpoint zero because exact sentence matching rejected the provider recognition “this charge” for injected “discharge”. The original failed report and audio remain unchanged.

Recognition alignment now compares ordered injected utterances with actual provider transcript turns. Ordinary wording differences require a separate bounded semantic judge. Exact reference differences, missing/extra turns and wrong preceding questions still fail structurally. The trusted runner checks relevance, role facts, unverified claims, natural turn-taking and recognition meaning before posting any provider archive. Actual provider transcript text and hashes are preserved. A judge cannot issue institution outcomes or complete checkpoints.

Local verification: 395 backend tests pass, 28 Node voice checks pass, and Python/Node syntax checks pass. The saved-transcript review starts no new Bolna session and cannot retroactively advance the failed case. An initial review attempt stopped before provider use because it used an undefined cost category; the implementation now uses the existing judge category. No budget limit was raised.

Still pending: complete current-configuration Bolna case, three consecutive fresh successful cases, full human audio review, mandatory release-fault evidence, cost reconciliation and final packaging. Hindi remains deferred.

Saved-call semantic review completed with one small-model text request (1,462 tokens, no new Bolna session). Relevance, role facts, identifiers, outcome claims and turn-taking scored positively, but recognition meaning failed: “this charge” versus “discharge” was treated as ambiguous. The saved call therefore remains failed and no checkpoint was advanced. The next correction is explicit assistant clarification/confirmation for materially ambiguous recognition, not relaxing the judge until an existing recording passes. Evidence: ../Claim911_Saved_Bolna_Dialogue_Semantic_Review.json.

## 24 October: confirmed Bolna intake and bounded long-turn capture

Run ff2c7e71-efbe-4e1f-8240-49da99479c7a passed the caregiver checkpoint with Bolna, an adaptive caregiver, one explicit concern confirmation, archived actual provider transcript/audio and positive semantic evaluation. Hospital discovery later stopped before checkpoint two when its combined reference readback exceeded the single 20-second capture window. The assistant had detected a missing initial letter and requested correction. This failed hospital evidence remains preserved; it is not a completed case.

The shared capture layer now snapshots at most eight seconds at a time from the unchanged short WebRTC ring, assembling at most forty seconds per logical turn. This matches the pre-existing backend archive bound. The trusted recognition adapter accepts the same forty-second maximum, below Azure's documented sixty-second short-audio maximum. Participant speech remains capped at twenty seconds. Overlong, incomplete or missing capture still fails. The adapter image was rebuilt offline from the pinned cached base; no packages, mounts or destinations were added.

A real local WebRTC loopback captured 28.096 seconds across four snapshots, proved that the original window expired, and retained the full turn with zero provider requests. The complete backend suite now passes 396 tests; 32 Node voice contract tests pass. A prior assertion enforcing immediate intake-save was updated to require the new single confirmation instead.

Question recognition differences may be deferred only in trusted parent-controlled runs to the mandatory semantic gate. A damaged reference may reach that gate only after a later exact code readback and explicit participant confirmation; unresolved reference differences still fail. Semantic review must establish that repair preceded use. Actual transcript and audio are never rewritten.

The original routing case was independently identified by DEMO-PATIENT-42 and HOSP-FINAL-1042. Read-only reconciliation confirms DISCREPANCY_OPEN. It remains unresolved and excluded from new demo cases. The separate integration case 47939ba3 is DOCUMENT_QUERY_OPEN and has its own audit. Both are preserved without state changes or new telephone calls. User-facing artifacts: Claim911_Legacy_Routing_Reconciliation.json and Claim911_Legacy_Integration_Case_Audit.json.

Final-topology boundary audit completed on 24 October with zero provider requests. Both actual package-worker images passed the reused isolation probe; the dedicated VM has no host mounts or agent forwarding, and the existing trusted provider network/proxy inspection passed. Artifact: Claim911_Sandbox_Boundary_Audit_2026-10-24.json.

The refreshed text suite initially rejected a direct, factually correct caregiver answer only because the criterion also demanded an unsolicited request for help. That extra conversational requirement was removed; grounding and hidden-fact restrictions are unchanged. The failed report remains preserved. A fresh suite is evaluating the revised intent-based criterion before any new Bolna session.

The browser harness session ceiling now matches the reviewed provider's 300-second ceiling rather than predicting duration from an assumed twenty seconds per turn. Per-turn audio size, reply count and no-audio waits remain independently bounded.

## 24 October: shared confirmation policy and product case accessibility

The next bounded Bolna run, 2b471449-dc99-4c1c-b340-d105eccfb047, again passed caregiver intake. Hospital speech was captured beyond twenty seconds, but secondary recognition distorted the combined code readback. The adaptive participant attempted corrections; a longer corrective reply then hit its separate twenty-second bound. The run remains review-required at checkpoint one, without a completed hospital-reference report. No automatic retry or new phone call occurred.

Inspection found that candidate-confirmation instructions previously lived only inside ScopedToolModel, the historical alternate-assistant adapter. They were absent from the actual Bolna tool context, whose objective also requested a combined four-reference readback. The policy now lives in coordinator/voice_guidance.py and is included in both adapters. The hospital objective requests one reference at a time, using uploaded canonical candidates for explicit staff confirmation. Uploads still do not establish confirmed facts or verified institution outcomes. The common Bolna prompt also requires refreshed context immediately before report writes, covering evidence or consent changes during a call without restarting answered questions.

The browser harness now makes one bounded opportunistic read of its existing scoped execution endpoint after capturing a question. It can use provider text only when it ends in a question and belongs to the current participant-reply position. It rejects stale/future turns and closing text, and otherwise falls back to audio recognition. The installed v3.0.1 SDK has no transcript event; live execution-text availability is still unverified and will be recorded per turn. No new transcript provider or assistant transport was introduced.

The caregiver case-view accessibility audit found low-contrast captions that the narrower home audit had missed. Shared progress, permission, document and activity caption colors were corrected. The production build passed, and all three frontends were restored. A fresh desktop/mobile audit now passes Overview, Documents, Permissions, approved-packet rendering, Activity and the conversation dialog with zero axe violations or horizontal overflow. Dialog focus containment and Escape dismissal pass. This audit uses intercepted synthetic API fixtures and does not count as operational workflow execution. Failure reports remain preserved; passing evidence is Claim911_Case_Journey_Accessibility_Verified.json.


## 2026-10-24: isolate voice failures without replaying intake

Added explicit component execution manifests for independent entry-stage voice checks. The runner supports `--fresh --component hospital_references_reported` with the same Bolna transport, consent, role actor and independent checkpoint verifier. No previous checkpoint is fabricated. Later-stage components are rejected because their prerequisites cannot be skipped. Public run metadata and sandbox UI distinguish component scope and checkpoint count. Full completion now requires the exact original 13-checkpoint manifest as well as completed state, both in exported reports and the product API. A component pass never counts toward the three fresh full-case release gate.

Validation: full backend suite 407 passed before the additional database component test; targeted component/lifecycle suite 14 passed including rejection by the real evidence gate. Initial restricted execution could not reach localhost; the authorized local-database run passed. No paid provider request was made for this change. The latest full Bolna case remains unverified. Spoken identifier presentation is applied but still awaits a hospital voice check; the preceding attempt stopped on a speech synthesis connection error during caregiver intake. Connectivity diagnostics alone do not establish that error's root cause.


### Hospital reference component passed

Run 27fd1f52-d735-44d7-83e8-ca774ad0b8a3 completed its single hospital_references_reported checkpoint with Bolna WebRTC, adaptive role-limited participant, no phone dispatch and unchanged reviewed assistant configuration. Semantic checks passed (latest question .95, role facts .98, identifiers .99, no unverified outcomes .95, natural turns .90, recognized meaning .90), followed by independent state verification. The closing correctly distinguished reported hospital submission from independently verified claims receipt. Report explicitly records COMPONENT, component_completed=true, full_case_completed=false. No full-case or release streak is claimed.


## Release evidence screening

Added a no-cost exported-report screen for three consecutive distinct full Bolna cases. It requires all 13 gates, Bolna-only archived conversations for every expected voice purpose, passing semantic evaluation, strict Bolna provenance in the independent verifier and identical reviewed assistant configuration. Component runs and duplicate exports never inflate the streak. Six focused regression tests cover successful synthetic metadata, changed configurations, component exclusion, failed latest cases, missing gate/quality evidence, duplicate cases and fixture-tolerant verification. The generated Claim911_Release_Evidence_Status.json correctly remains not ready. It does not replace human listening or live evidence re-verification.


### Fresh full case checkpoint update

Run a9efa926-2c8d-49ee-9363-8164b3e58b14 remains active under the reviewed Bolna configuration. Authoritative runner output verifies caregiver_intake_confirmed (checkpoint 1) and hospital_references_reported (checkpoint 2). The hospital call took six recognized assistant turns, including the closing, compared with nine in the isolated component; no reference policy was changed between those runs. Claims query discovery is next. This is partial progress, not a full-case pass. Live runner session 95656 should be polled, not restarted.


## 2026-10-25: controller primary dialog accessibility

Controller proposal and supporting-evidence views pass axe WCAG2 A/AA and WCAG2.1 AA checks on desktop and 390px mobile. Keyboard focus stays contained, Escape dismisses, and focus returns to the actual case opener. The fixture-only audit performs zero provider requests and zero operational writes. Initial timeout was preserved; restarting the caregiver/controller servers against the newly built assets resolved initialization. No active sandbox call was restarted. Report: Claim911_Controller_Case_Accessibility_Verified_2026-10-25.json. This verifies rendering/accessibility, not proposal execution or autonomous product coordination.


### Fresh full run stopped at query-discovery transcript verification

Run a9efa926-2c8d-49ee-9363-8164b3e58b14 is terminal UNCERTAIN with exactly two verified checkpoints. The claims call reached its closing, but deterministic provider transcript checks rejected unconfirmed claim/admission identifier mismatches: CLM-SYN-8842 became "clm hyphen sy and ..." and ADM-SYN-2084 became "eight d m ...". Query reference clarification succeeded but did not repair those other fields. The call was not admitted as a successful archive and no document checkpoint advanced. No retry was issued.

The current claims objective required readback only of query reference/requirements, unlike the successful hospital candidate protocol. Updated shared claims context and objective to directly offer each uploaded query, claim, admission and enhancement candidate once, obtain explicit confirmation for each and preserve canonical tool values. This uses the existing candidate evidence and spoken presentation, without fuzzy replacement or weakened archive gates. Fifteen focused guidance/reference/workflow/scoped-tool checks pass. This change remains unverified on Bolna. Preserve the failed run; further execution needs explicit safe preparation/reconciliation, not restarting its uncertain lease.

Full backend regression after the claims confirmation correction: 416 passed, one existing Starlette deprecation warning. No provider session remains active.


## Claims component preparation and safe isolation

The prior failed claims call had already persisted a query report before its audio archive was rejected. Reusing that incident would overwrite or bypass its workflow stage. It was left unchanged. Added claims_query_discovered as an explicitly labeled COMPONENT manifest with EXPLICIT_SYNTHETIC_FINAL_REFERENCE_FIXTURE starting state. Preparation reads only the new synthetic hospital's final reference and supplies it through the ordinary intake API; it does not clone prior reports, invent voice evidence or mark intake/hospital checkpoints complete. The standard claims voice and independent verifier still execute. Added --prepare-only for no-provider setup validation. Twenty-five focused component/lifecycle/guidance/workflow checks pass. Prepared run c656c310-d0f1-4c73-9944-f588af7ec910 with zero provider sessions, then started its single claims voice test under the unchanged reviewed Bolna agent. Active runner session 95308 must be polled rather than restarted.


### Claims component passed

Prepared component c656c310-d0f1-4c73-9944-f588af7ec910 completed claims_query_discovered with Bolna, strict archived-audio/transcript checks, semantic evaluation and independent institution-state verification. All query identifiers, original receipt instant/timezone and required documents were confirmed using the shared candidate protocol. The previous failed case remains unchanged. This is one component pass, not a full-case or release-streak pass. Active runner session 95308 is terminal exit 0.

Fresh full-case run 6b82748b-3b87-4f18-a317-c68c4cb2bd29 started after the claims component pass. Live runner session 22458 must be polled rather than restarted. No release pass is claimed.


## 2026-10-25: queued demo execution path

While full case 6b82748b-3b87-4f18-a317-c68c4cb2bd29 runs directly, inspected the actual UI worker path. Its 240-second subprocess deadline was shorter than the reviewed 300-second provider session plus evaluation; its five-minute job lease could expire before cleanup; and its runner invocation omitted the chosen Node executable and spend category. Extracted sandbox_phase_command with explicit transport, adaptive participant, approved rehearsal/development category and validated absolute Node executable. Bounded phase deadline is 600 seconds and job lease 720 seconds. Invalid/operational/phone-enabled profiles fail before execution. Existing independent checkpoint advancement, uncertain dispatch behavior and no automatic retries remain unchanged. Thirty-three worker/executor/command checks pass.

Fixed sandbox UI conditions so an available automatic runner is shown even when Bolna browser capability is configured; the manual compatibility widget is limited to when the automatic runner is unavailable. Source only for now: do not rebuild served assets during the active WebRTC run. Worker execution has not been enabled and no new worker paid session was started. Full-case runner session 22458 remains active and should be polled, not restarted.


### Fresh case 6b82748b stopped after caregiver intake

The hospital call reached eight participant replies but did not produce closing audio. The harness stopped safely with one verified checkpoint. Preserved recognition/injection evidence shows a specific participant false affirmation: an initial-reference question was recognized as "n. H ... 2084", and the adaptive participant answered yes; later the assistant detected initial/enhancement duplication and reopened initial confirmation. This consumed the bounded session. The provider transcript was not yet present in the first failure report, so the precise spoken/provider recognition sequence still requires read-only final execution retrieval. Do not solve this by raising turn limits or counting the earlier component pass as reliability proof. No retry was issued. Runner session 22458 is terminal exit 1.

The next diagnosis should examine generic positive-confirmation grounding in the adaptive participant: currently only identifiers emitted in its reply are validated against role records, so a generic yes can escape exact identifier validation when the question's code was incompletely recognized. Fix the shared affirmation contract and run the admitted text scenarios before any new paid voice attempt. Do not silently replace adaptive role players with scripts or fuzzily repair codes.


## Adaptive affirmative-readback contract

Added readback_confirmation.py: exact role-owned codes and requested reference kind must support an affirmative readback. Incomplete codes and known codes assigned to a different field cannot be confirmed. This performs no fuzzy code correction and grants no institution action. DeskParticipant requests one bounded adaptive clarification if the generated answer violates that contract, validates the second result and stops if unsupported. It never substitutes a scripted answer or permits a tool during repair. Twenty-eight focused tests pass, including actual actor repair and two-request stopping behavior.

Participant admission now fingerprints participant_model.py, readback_confirmation.py and spoken_identifiers.py together. The previous published text gate is deliberately stale and blocks new automated Bolna sessions. The text corpus now has version 2 with twelve cases, adding the actual incomplete-prefix and wrong-reference-kind failures. evaluate_participant_text supports an explicit approved phase (development/integration/rehearsal); all hard budget caps remain unchanged. Fresh text admission must be executed and passed before any more voice tests. No new provider request was issued after this change.

The sandbox start-control build passed and all three frontends were restarted against it while no voice run was active. Worker enablement, end-to-end UI dispatch and the full-case/release gates remain pending.


Full backend regression after the common affirmation contract and queued worker path: 429 passed, one existing Starlette deprecation warning. Fresh twelve-case participant text evaluation started in approved integration phase; live session 62753 must be polled rather than restarted. No Bolna session is active. New output target Claim911_Participant_Text_Readback_Contract_Evaluation.json is immutable; the private admission gate is published only on a fresh complete pass.


## 2026-10-25: confirmation admission result and field-bound corrections

Fresh readback-contract text evaluation completed all twelve cases and 38 provider requests, with eleven passes and one failure (hospital_wrong_reference_kind). The failed answer declined the readback but then supplied ENH-SYN-2084 as a correction for the initial request. No admission gate was published and no Bolna session was started. Preserved the original report unchanged.

Extended the same shared exact-reference contract to codes in negative corrections: a known code from another field is not an allowed correction. The one bounded adaptive repair receives only the permitted canonical codes for the explicitly requested field, drawn from the role's own record; it still generates its own reply, cannot invoke tools, and must pass validation. Thirty focused checks pass, including wrong-field negative correction and actual adaptive repair. Full regressions are running before a new text evaluation.

Read-only broker retrieval obtained finalized failed hospital execution evidence: provider status completed, duration 300.1 seconds. Provider transcript confirms actual initial/enhancement candidate confusion, false participant affirmation, later correction, a bulk recap, a report retry and a closing truncated at the session ceiling. Saved Claim911_Failed_Hospital_Final_Execution_6b82748b.json separately without altering original failed-run evidence or advancing state. No additional voice session or paid inference was used for retrieval.

Full backend regression after field-bound corrections: 431 passed, one existing deprecation warning. Fresh field-grounding text evaluation started with the approved integration phase; preserve Claim911_Participant_Text_Field_Grounding_Evaluation.json and poll live session rather than duplicate it. No Bolna session is active.

Field-grounding admission evaluation live session: 16669. Poll this handle; do not restart on a quiet interval.


## 2026-10-25: provider interruption diagnosed to transport boundary

Field-grounding generation produced all twelve answers, with the two new correction cases now responding correctly. Independent evaluation interrupted after five passing cases with ProviderOperationError (25 reserved requests). Preserved the report; no admission gate published. Added validated resumption of unchanged fresh generated answers after infrastructure interruption. It rejects old captures, changed actor/corpus/image, missing generated-response provenance and prior failed judgments. Resumption rejudges every case and preserves the source hash; it never repeats participant generation or writes institution state. Thirty-one focused checks pass.

The resumed evaluation also stopped on URLError after four passing cases (10 reserved requests). Its safe diagnostic was preserved. No repeated Bolna call was issued. Twelve unauthenticated HEAD requests through the actual restricted provider image/network/proxy all succeeded around one second each; that proves reachability during the probe, not the cause of failed inference requests. Added sanitized DNS/TLS/network-timeout/connection/proxy-CONNECT classifications without raw error strings, URLs or keys. Built provider image 0ba7d80f0c5d from cached pinned base with build networking disabled. Offline image smoke and 28 focused diagnostics/egress/admission checks pass. Provider image changed, so previous text admission remains invalid; no fallback or automatic retry was added.

Fixed UI distinction between real operator and scoped automated harness when the worker is available. Browser fixtures verify: operator sees Start audio run, clicking it queues exactly one intercepted request, scoped harness sees only its voice widget, offline compatibility remains accessible. All three mode checks pass with zero provider requests/writes. Production build and all three refreshed UI servers are running. Report Claim911_Sandbox_Start_Controls_2026-10-25.json is fixture rendering evidence, not end-to-end dispatch proof.

Local reservation accounting (not billed spend) reads development 57.60 USD, integration 7.60 USD, rehearsal 8.00 USD held. No caps were raised or uncertain holds deleted. Future accounting work should preserve model request IDs and returned token usage, and use verified provider prices/telemetry rather than treating conservative reservations as invoices. Integration has only 2.40 USD of reservation room, so do not blindly restart a 36-request text suite in that category.

Full backend regression after resume validation and sanitized network diagnostics: 442 passed, one existing deprecation warning. All provider/evaluation sessions are terminal. No Bolna call is active.


## Request-bound model token evidence

Fresh text reports now include their ledger run ID and each model request ID alongside returned usage. Added bounded allowlisted provider usage evidence for future voice-role model calls and text evaluations. Token telemetry records exact prompt/completion/total counts and valid cached/reasoning subcounts, never raw provider configuration. It explicitly does not verify billing or release a reservation. Local temporary-ledger tests prove a request remains UNCERTAIN with its original held amount after usage is attached. Twenty-three focused transport/usage/budget checks and eleven dedicated usage/ledger checks pass. Historical reservations have not been relabeled as actual charges.

Fresh diagnostic-image text admission is running under rehearsal phase, session 9849. It generated all twelve participant answers and reached at least eight passing independent case evaluations without an observed provider error. Poll the same live session; no Bolna session is active. Output target Claim911_Participant_Text_Diagnostic_Image_Evaluation.json remains incomplete until the runner exits successfully and publishes its private gate.

Diagnostic-image participant admission completed successfully: all twelve independent cases passed, 38 provider requests, no observed transport error in this attempt. Published the private last-successful text gate for the current provider image and participant implementation bundle. Earlier URLError causes remain unproven; this pass does not retroactively resolve failed runs. A single new hospital component voice test has started after the fresh admission.


### Admission usage and hospital retest

The diagnostic-image text admission passed all twelve cases and published its gate (38 model requests). All 38 response-usage records were attached to exact ledger request/run IDs after provenance validation. Totals for this one suite: 16,924 prompt tokens, 5,355 completion tokens (including 3,968 reasoning tokens), 22,279 total. This is usage telemetry, not project-total cost or billing verification; every uncertain dollar hold remains intact. Saved Claim911_Model_Usage_Admission_2026-10-25.json. Four dedicated token-evidence tests, including rejection of cross-run attachment, pass.

One bounded hospital component started: 25948b36-dc97-436a-8807-31481062afa1, live session 19733. Uses Bolna, adaptive participants with field-bound confirmation guard, reviewed assistant configuration and current admitted provider image. It is currently in progress; do not treat it as a full-case pass or duplicate the call.


### Hospital retest exposed false-negative confirmation

Component 25948b36 stopped under its bounded turn limit without completing references. The role participant rejected exact admission-code readbacks after ASR formatting variations: IDADM and a DM. It also sometimes said "not an exact match" for an actually correct readback. This is a participant/parser false-negative, not evidence that the institution code changed. Preserved the failed run; no retry or checkpoint advancement.

Reworked shared readback evidence around exact character matching against role-owned records. It accepts whitespace/comma segmentation and a known field-label boundary, while rejecting changed characters, additional prefixes and wrong field types. Both positive and negative replies are validated. The adaptive model receives an explicit EXACT_MATCH or MISMATCH_OR_UNCLEAR result plus its own permitted reference values before generation; any bounded repair receives the same facts. It still generates natural speech and cannot execute an institution action through this check. Added recognition of the exact generated NATO phonetic forms and slash separators, with no fuzzy identifier repair. The admission fingerprint includes the canonical spoken-form table as a dependency.

Expanded text corpus version 3 has fourteen cases, including positive spaced-code and glued-label readbacks, so always-rejecting behavior cannot qualify. The previously passed twelve-case gate is now deliberately stale. Full backend suite passed 455 checks before the final phonetic/slash additions; 51 targeted parser/participant/admission tests pass afterward. No provider session is active. Fresh fourteen-case text admission remains required before more voice tests.


## User credit constraint: paid tests stopped

User reports only USD 6 credits remaining and objects to spend with only two full-case checkpoints verified. Stopped paid text evaluation session 42790 with SIGINT (terminal exit 130), preserved its partial report and uncertain request holds. Suspended the local provider budget to block further paid Azure requests. No automatic paid retries or new Bolna sessions are authorized during the following local completion work. Preserve remaining credits. Complete workflow and all release gates remain unverified; local fixture tests are not Bolna proof.

## 2026-10-25: Local controller case workspace and transcript navigation

Paid provider testing remains stopped following the remaining-credit concern. No paid provider, model, speech or telephone requests were made for this work.

- Added controller-scoped case activity, paginated conversations, case-bound transcript and document reads. Caregiver/controller boundaries remain server-enforced. These routes do not execute proposed actions.
- Controller case review now separates Next action, Documents, and Activity & conversations. Supporting evidence stays on demand.
- Reused the shared activity component, with bounded conversation pagination. Controller transcripts appear within the existing case review instead of a nested modal. Preserve the transcript/list containers while changing visibility so Radix focus trapping does not lose the return target when the focused element is removed. Focus moves after React commits the view change.
- Earlier failed accessibility reports remain preserved. Final report: ../Claim911_Controller_Transcript_Final_Check_2026-10-25.json. Synthetic rendering fixtures only, zero provider requests and zero operational writes. Desktop/mobile checks pass: no audited WCAG violations, no horizontal overflow, focus returns from transcript, stays within dialog and returns to case opener on Escape.
- Production build passed. Product boundary suite: 8 passed. Identifier readback, readback confirmation and release evidence suites: 28 passed.
- Not completion evidence for Bolna or the full MVP. The complete 13-checkpoint Bolna case and three fresh successful runs remain unproven. Controller proposal execution/autonomous scheduling and the remaining release gates still require work.

## 2026-10-25: Operator follow-up visibility

- Inspected actual coordination wiring: the experience API still advertises coordination_available=false. Durable callback storage/recovery exists, but this is not an operational autonomous call dispatcher. Do not represent the proposal panel or callback queue as connected execution.
- Added a controller Follow-ups tab using the existing controller-scoped callback read API. Shows named task, saved state, bounded attempts, next eligible time, original query timestamp, response target and saved report summary. Uncertain execution explicitly requires reconciliation; reported status is not verified institution evidence. Unknown purposes/states use neutral review labels.
- Reused React state/effects and existing Radix tabs. No additional dependency, scheduling button, call dispatch or permission bypass added.
- Verified 15 callback/policy/product-boundary tests passed against the isolated local database, including retry limit, restart recovery, uncertain execution and consent revocation. Production build passed.
- Desktop/mobile fixture accessibility checks passed including the new follow-up view and existing transcript keyboard journey. Evidence: ../Claim911_Controller_Followups_Accessibility_2026-10-25.json. Provider requests: zero. Operational writes in UI fixture evaluation: zero.
- Paid testing remains stopped. The full Bolna case, autonomous coordinator integration and full release acceptance remain incomplete.

## 2026-10-25: Separate simulator dialogue from paid audio infrastructure

User requested correction of the coupled simulator design. Added a shared text-only participant session and integrated it into the Bolna browser transport, standalone participant adapter and paid text evaluator. Adaptive role participants remain adaptive; local model doubles are not a replacement assistant or a scripted demo fallback.

The common session binds a sequential turn ID to an exact question, retains a prepared reply through synthesis failure and refuses changed-question/role/actor reuse. Uncertain generation fails closed rather than repeating a possibly completed synthetic operation. Accepted local output is explicitly not audio-delivery proof. No durable crash-recovery claim is made.

Known topic mismatches stop before synthesis. Known critical conversation mismatches short-circuit semantic judging without assigning passing scores to unassessed checks. Corrected the exclusive-topic check to avoid treating a combined language/consent question as a definite mismatch.

Added a pytest-based network-denied local preflight. Both full workflow and participant-text entry points enforce it before provider construction. Expanded the participant fingerprint so previous paid gates are stale after the shared implementation change. Existing budget suspension and separate provider proof gates remain intact.

Evidence: ../Claim911_Simulator_Restructure_Local_2026-10-25.json, 100 deterministic contract tests passed with network connections denied. Python compilation passed. No provider requests were made. The first broader integration invocation had missing test configuration variables (33 passed, 18 setup errors), so it does not count as a full integration pass; rerun uses explicit isolated test profiles.

Details and limitations: SIMULATOR_TESTING.md. Live ASR/SDK behavior, model relevance and complete Bolna workflow remain unverified by these local checks.

Final verification for simulator separation: 101 network-denied local contracts passed after adding restored-history coverage. Evidence: ../Claim911_Simulator_Restructure_Final_Contracts_2026-10-25.json. The correctly configured independent local integration rerun passed all 51 workflow/checkpoint/service/worker tests. Earlier setup-error output is not counted as a pass. No paid provider sessions were run. The live runner still requires a fresh adaptive participant evaluation and full Bolna validation before release; existing paid evidence was not promoted.

## 2026-10-25: Failure isolation and cached reply safety

- Found and fixed stale prepared-reply reuse after a later generation failure. A failed session now refuses even an earlier cached reply until reconciliation.
- Added bounded text-session diagnostics: last actual question, generated/rejected answer, failure category, session state and completed local outputs. No private role record, credentials or tool configuration are included. Output preparation is never audio delivery or workflow verification.
- Bolna browser failures now retain stage-specific private failure evidence even if browser cleanup produces no report. Evidence is explicitly failed, non-checkpoint-eligible and bound to run/role/purpose. Recognition, generation, synthesis, audio validation and media handoff have separate stage labels. Browser report parsing does not mask the original failure when it is missing or malformed.
- Network-denied local preflight: 103 tests passed, report ../Claim911_Simulator_Failure_Diagnostics_2026-10-25.json. No paid requests. The live failure-archive path itself remains unverified in a fresh provider run; local tests establish text-session behavior only.

## 2026-10-25: Caregiver progress follows authoritative workflow gates

- Replaced the generic post-query 'more documents' message with a projection of the existing shared planner's actual next checkpoint. Distinct views now cover document owner, exact packet approval, hospital submission, unconfirmed receiving receipt, query/enhancement verification, insurer decision and hospital reconciliation.
- A verified reconciliation with BALANCE_PENDING is not shown as administrative clearance. Review holds and withdrawn investigation permission take precedence over old outcome state. Removed unsupported wording that implied automated work was currently running.
- Confirmed outcomes now show 'Outcome confirmed' rather than 'Request saved' and do not show the saved-request setup notice. Incomplete disconnected cases show 'Coordinator review'.
- Pure progression tests plus product API tests passed (14); product boundary rerun (8) also verifies real API status changes on exact packet approval and withdrawal. The network-denied preflight now includes progression checks: 109 passed, ../Claim911_Caregiver_Workflow_Progress_Local_2026-10-25.json.
- Production build passed. Caregiver desktop/mobile outcome/documents/permissions/activity and transcript keyboard fixture audit passed: ../Claim911_Caregiver_Outcome_Progress_Accessibility_2026-10-25.json. These are rendering fixtures, not full live-workflow proof.
- Refreshed the three local interfaces and both product APIs with their respective operational/sandbox profiles. No voice broker/provider worker started, and no paid requests made. Autonomous coordination and full Bolna release evidence remain incomplete.

## 2026-10-25: Cancel scheduled follow-ups safely

- Added one shared domain operation for cancelling WAITING callbacks, serialized with the incident lock used by claim/scheduling. Cancellation is case-bound and idempotent. It records one FOLLOWUP_CANCELLED audit event, leaves attempts unchanged and prevents later claiming the queued work.
- RUNNING, UNCERTAIN and other nonwaiting states are rejected. This operation never claims that an active transport was stopped and does not verify any institution outcome.
- Exposed a controller-only, case-bound DELETE route and a Cancel scheduled follow-up button only on waiting rows. Errors remain visible, and successful cancellation refreshes the saved queue state. Caregiver activity uses a concise mapped audit update.
- Callback and product-boundary tests: 14 passed, including cross-case rejection, caregiver denial, repeated cancellation, unchanged active lease and audit deduplication. Production build passed.
- Desktop/mobile fixture cancellation and accessibility passed: ../Claim911_Followup_Cancellation_Accessibility_2026-10-25.json. Two fixture mutations, zero operational writes, zero provider requests. No audited accessibility violations or overflow; keyboard return/trapping passes.
- Local interfaces and both product APIs refreshed. No paid services, voice broker or provider workers started. Autonomous dispatch, uncertain-execution reconciliation UI and full Bolna release verification remain pending.

## 2026-10-25: Evidence audit and presentation package

- Ran zero-request exported release screening across 71 saved reports. The latest three full-case Bolna attempts remain ineligible. Evidence: ../Claim911_Release_Readiness_Audit_2026-10-25.json. This is not live-state reverification and does not establish release readiness.
- Prepared ../Claim911_Hackathon_Demo_Guide.md: concise pitch, three-minute storyboard, meaningful complication, audience inspection points and explicit current evidence boundaries. The complete voice storyboard is labeled unverified until the required run exists. Recorded/live and fixture/provider boundaries remain explicit.
- Prepared ../Claim911_Architecture_Use_Case.md: use-case sequence, system diagram, reasoning/control/evidence responsibilities, current deterministic planner, sandbox separation and unfinished autonomous operational dispatch.
- Updated README and voice runbook to reflect the shared local preflight, stopped paid testing and fourteen-case participant corpus. Verified local artifact links exist and new audience-facing documents contain no em dashes.
- No paid services used. Major remaining work: autonomous integration, fresh setup reproduction, current participant/voice admission, complete full Bolna runs and faults, human listening, cost reconciliation, and final verified replay. Documentation does not satisfy these execution gates.

## 2026-10-25: Read-only cost accounting report

- Added sandbox/cost_report.py and scripts/report_sandbox_costs.py. The script accepts an explicit local sandbox profile, executes SET TRANSACTION READ ONLY and reads only accounting fields. It does not construct a provider adapter, settle a request, release a hold, refresh external balances or change spending suspension.
- Report separates original reservations, recorded confirmed amounts, unreconciled holds and provider-returned token telemetry. Cached/reasoning subsets are not double-counted. Unknown model usage is counted explicitly. Bolna spend remains outside this ledger summary.
- Actual snapshot: 1,119 records; 305 CONFIRMED totaling local recorded charge zero; 814 UNCERTAIN totaling $81.40 in unreconciled reservation holds, NOT billed spend. Valid telemetry covers 72 model requests and 43,376 total tokens. 741 model requests lack valid saved telemetry. Paid testing remains suspended.
- Accounting and budget tests: 15 passed using isolated temporary ledger tables. An initial unit invocation without the ledger fixture profile passed 5 and skipped 2; the configured rerun passed all 15. No paid provider requests or ledger writes were made by the report.
- User-facing outputs: ../Claim911_Cost_Status.md and ../Claim911_Local_Cost_Reconciliation_Status_2026-10-25.json. Actual provider billing reconciliation is still incomplete and must not be represented as finished.

## 2026-10-25: Fresh-storage reproducibility rehearsal

- Inspected cached images: no PostgreSQL image available, so no image was downloaded. Used the existing local PostgreSQL service with new databases and roles instead. This does not claim fresh-machine/dependency installation.
- Extended existing bootstrap_profiles.py with explicit admin-profile input, a validated namespace suffix and distinct configurable institution ports. Existing runtime namespace mismatches are rejected. All role/database collisions are checked before provisioning starts; existing credentials are never silently rotated.
- Created new operational/sandbox databases under the rehearsal2510 namespace with new private profiles. Main operational, sandbox and legacy case data were not modified. Started temporary institution services on 8313/8314, pointed only fresh profiles to them, then ran the complete state/institution/product suite.
- Fresh-storage suite: 32 passed, one expected legacy-reader skip. Two fixture runs completed all 13 checkpoints, including the unsigned-summary recovery and durable-worker path. This uses explicitly offline audio/report fixtures, not actual voice.
- Read-only audit confirmed coordinator institution-table access denied and sandbox-role connection to operational storage denied. Two bootstrap safety tests passed; repeating bootstrap retained matching private configuration. Temporary institution servers were stopped and fresh evidence preserved.
- Deliverables: ../Claim911_Clean_Database_Rehearsal_2026-10-25.json and ../Claim911_Local_Reproduction.md. No paid providers used. Full fresh-machine setup, frontend provisioning, current voice admission and complete Bolna release proof remain unfinished.

## 2026-10-25: Prevent paid starts at the product boundary

- Added shared read-only testing_readiness/require_testing admission checks for absent budget configuration, suspension and the existing daily credit-verification interval. Per-request reserve() remains authoritative for individual budget limits; readiness does not grant spending authority.
- Sandbox status exposes a plain-language paid-testing state. Both full-run Start and direct sandbox voice-session creation reject suspension before preparation, queueing or broker access. Full workflow CLI and paid participant-text entry points enforce the same check before provider construction, after local preflight.
- UI hides both automated and compatibility voice-start controls during suspension, displays the explicit pause reason and retains saved-run inspection/preparation controls. No silent fallback is offered.
- Local sandbox, boundary and budget tests: 30 passed. Tests for mocked broker session behavior explicitly mock only the admission function; the actual ledger is not unsuspended. A dedicated rejection test denies network construction and case binding, checks no job queued and preserves PREPARED/unbound state.
- Production build passed. Four UI control fixture modes pass: operator, scoped harness, offline compatibility and paid-testing paused. Evidence: ../Claim911_Sandbox_Paid_Suspension_UI_2026-10-25.json. Real local status endpoint also confirms PAID_TESTING_PAUSED and phone dispatch disabled.
- Three interfaces and both product APIs refreshed. No provider workers/broker were started and no paid requests made. This is start-path integration and spending control, not autonomous operational dispatch or a completed Bolna workflow.

## 2026-10-25: Implemented scenario complication controls

- Added sandbox-only pre-binding fault configuration for three implemented conditions: unsigned summary, wrong-admission implant invoice and old bill. Existing manifest fault names beyond these three are not presented as implemented controls.
- The Sandbox Scenario tab edits only USER_PREPARED/unbound runs. Scoped harness sessions and caregiver sessions cannot change scenario controls. Bound/cancelled cases are read-only; prepare a fresh run to change conditions. Configuration remains available while paid testing is suspended and performs no provider request.
- preparation.bind passes selected faults through the existing scoped seed credential. Institution seed applies conditions only to role-owned synthetic records. A summary without the unsigned fault is released with the synthetic treating-team signature; old bills and mismatched invoices retain valid institution content hashes but fail actual coordinator evidence checks.
- Seed retries are idempotent and conflicting conditions are rejected. The unique insert and subsequent locked read serialize concurrent seed creation. A two-thread test confirms one accepted seed and one conflict, rather than two contradictory acknowledgments.
- Verified default executor/workflow and negative preparation suite: 14 passed; focused fault/preparation concurrency suite: 5 passed. Earlier actor/run/preparation suite: 17 passed. No paid providers used.
- Production build passed. Desktop/mobile and bound-case scenario fixture checks pass with no audited accessibility violations or overflow. Evidence: ../Claim911_Sandbox_Scenario_Controls_2026-10-25.json, two fixture mutations and zero operational/provider writes.
- Release reports now carry selected scenario faults and actual followup flags. Offline screening rejects a missing unsigned-summary condition or missing initial/follow-up records conversations. Network-denied local preflight: 110 passed, ../Claim911_Scenario_Recovery_Release_Contracts_2026-10-25.json. This remains report screening, not human audio or live-state proof.
- Local UI/API and sandbox institution service refreshed. Full Bolna workflow, remaining fault controls and release matrix still require work; no voice pass or complete hackathon readiness is claimed.

## 2026-10-25: Receipt and insurer outcome fault conditions

- Expanded implemented seed conditions from three to six: withheld recipient receipt, pending insurer review and institution-issued denial join unsigned summary, wrong-admission invoice and old bill. Pending review and issued denial cannot be selected together; UI replaces the conflicting choice and the API rejects contradictory payloads.
- Withheld receipt permits actual hospital dispatch but blocks receiving acknowledgment and downstream query linkage. Pending review prevents institution decision issuance and hospital reconciliation. Fixed denial is preserved as DENIED with zero insurer payable and a remaining patient balance, not administrative clearance or refund payment.
- Moved the participant's issue_fixed_decision operation to an insurer-owned review-and-issue endpoint with no caller-supplied outcome or amount. It reuses the existing decision prerequisites, signing and immutability checks. The synthetic institution selects the configured outcome; raw authorized decision writes cannot override a configured pending review or denial.
- Local fault/actor/service tests: 15 passed. Broader default executor/checkpoint/service/fault/preparation regression: 22 passed, confirming the original successful synthetic workflow remains intact. Production build passed.
- Desktop/mobile and bound-case scenario UI fixture audit passed, including exclusive insurer selection. Evidence: ../Claim911_Sandbox_Outcome_Fault_Controls_2026-10-25.json. No accessibility violations or overflow, two fixture mutations, no provider requests or operational writes.
- Refreshed local UI, product APIs and synthetic institution service. Paid testing remains suspended. Remaining runtime/provider faults, adaptive voice quality and full Bolna release verification remain unproven.

## 2026-10-25: Durable worker admission and explicit runtime handoff

- Inspected the actual UI-to-queue-to-subprocess path. API start guards alone did not protect old queued jobs if a worker was later started while execution was disabled or paid testing was suspended.
- sandbox_once now leaves genuine jobs QUEUED with zero attempts and no lease while execution is disabled or testing admission is closed. It does not launch a phase, convert a known nonattempt into uncertain dispatch, or silently retry. Expired actual executions still retain their existing uncertain-recovery behavior.
- Explicit offline verification fixtures remain runnable through their test-selected job IDs; the normal worker ignores fixture origins. This keeps the full deterministic sequence available without opening provider access.
- Added --runtime to the workflow runner. The actual worker derives the explicit runtime from its trusted sandbox profile directory and passes it as an argument. The subprocess can no longer silently use the workspace default when the worker uses a different runtime.
- Verification: 15 executor/worker-command tests passed, including full offline sequence, queue preservation across both paused/disabled states, expected run/attempt state and explicit runtime argument validation. Python compilation passed.
- No provider worker or broker was enabled or started, and no paid requests were made. The complete real UI/worker/Bolna path remains unverified until provider admission is allowed and a full run passes.

## 2026-10-25: Unavailable desk and terminal callback escalation

- Found a workflow bug in negative callback handling: an ESCALATED callback was still reported as WAITING_CALLBACK, allowing an extra queued phase and eventual misleading uncertain state. Added a case-bound leased run escalation operation and propagated the authoritative callback result through executor and durable job state. Escalated jobs do not enqueue another attempt or advance a checkpoint.
- Restricted signed-summary release to medical_records follow-ups. Billing and implant callbacks no longer receive a clinical release operation merely because their document remains unavailable.
- Added desk_unavailable as the seventh implemented seed condition. It makes billing sign-off unavailable and the corrected bill unreleased, with role-owned availability information. Adaptive participants read this actual record; the seeded text participant also does not claim the bill is released. Conditions remain immutable after binding.
- Added a generic unavailable-summary worker test and an actual unavailable-billing seeded scenario test. Both stop after initial contact plus two callback attempts, preserve the original receipt time, retain missing evidence and require human review. No extra job is queued. Later executor.step refuses to resume an escalated run.
- Local executor/fault/preparation integration suite: 19 passed. Network-denied local contracts: 110 passed (../Claim911_Callback_Escalation_Local_Contracts_2026-10-25.json). Production build passed.
- Desktop/mobile/bound-case scenario UI checks passed: ../Claim911_Unavailable_Desk_Scenario_UI_2026-10-25.json. No audited accessibility violations, no overflow, no paid start control exposed during suspension. Two fixture mutations, zero operational writes/provider requests.
- Local interfaces, product APIs and synthetic institutions refreshed. Provider worker and broker remain stopped. Full Bolna sequence and remaining runtime faults still require separate verification.

## 2026-10-25: Full backend regression after workflow changes

- Expanded the pytest-only network guard with an explicit loopback integration policy and external DNS rejection. Strict participant preflight always forces complete socket/DNS denial regardless of inherited integration settings. This is a trusted Python test guard, not an OS/container security claim.
- Ran the entire backend tests directory using isolated operational/sandbox profiles and the loopback-only Python socket policy: 502 passed, zero failures/errors/skips, 45.73 seconds. The only warning is the pre-existing Starlette/httpx deprecation.
- Preserved JUnit output at ../Claim911_Backend_Regression_2026-10-25.xml and parsed it before generating ../Claim911_Backend_Regression_Summary_2026-10-25.json.
- Read-only post-run audit confirms paid testing remains suspended and the real sandbox reservation count is unchanged at 1,119. No provider requests were made by this verification.
- Rechecked strict no-network preflight after the guard change: 110 passed, ../Claim911_Strict_Network_Preflight_2026-10-25.json.
- This broad regression supports local backend behavior and the fixture workflow. It does not verify current adaptive model quality, full Bolna audio, current provider billing, fresh-machine installation or complete hackathon readiness. Those release gates remain incomplete.


### Main-case focus and role prompt simplification

Stopped expanding simulator scope in favor of the existing complete Bolna-led discharge case. Removed caregiver, hospital query-ownership and medical-records signature instructions from unrelated participant roles. Retained adaptive replies to the actual question, exact identifier checks, scoped institution tools and evidence gates. This is prompt simplification, not a scripted assistant replacement or proof of model behavior.

Verification: 49 participant model, shared dialogue and readback contract checks passed with the Python network guard in deny mode. No paid provider session was started. Participant fingerprint changes require fresh admission evidence before voice use; the paid gate remains intentionally stale. Full 13-checkpoint Bolna execution remains unverified.


### Archived hospital dialogue replay, no provider use

Replayed the eight saved hospital exchanges from call 25948b36-dc97-436a-8807-31481062afa1 through the current exact-character readback checks using only the synthetic reference values present in that conversation. Four historical participant denials now correctly fail the guard because the assistant supplied the matching admission or enhancement code. This confirms the local guard addresses the observed false-denial pattern; it does not establish that the adaptive participant will generate a correct replacement, that Bolna will hear it, or that the complete call passes. No extra scenario controls or provider calls were added. Saved the bounded replay as outputs/Claim911_Hospital_Dialogue_Offline_Replay_2026-10-25.json.


### Bolna scheduled-records callback context gap fixed

The executor passed followup=True to both voice adapters, but the Bolna transport used it only in run evidence. The older model adapter added treating-team follow-up instructions privately. Shared backend voice context now reads the current case/purpose/consent-bound RUNNING callback and includes a bounded active_followup summary; shared voice guidance requests treating-team follow-up and institution-released evidence for medical records. No institution permission or evidence check changed. Initial and cancelled callbacks do not receive this guidance.

Verification: 11 local voice-context/guidance checks and 19 executor/objective/closing checks passed with the Python loopback-only network guard. No provider requests. Saved Claim911_Shared_Callback_Context_Verification_2026-10-25.json. Core services need reload before provider validation. Full Bolna case remains unverified.


### Short synthetic references, scenario version 2

New case fixture and integration/rehearsal inputs use ADM42, PRE37, ENH18, FIN63, QRY25 and CLM86. The manifest and participant regression suite are version 2. Existing database cases and archived recordings remain unchanged. Updated exact-reference parsing, role output validation, scripted desk recognition, Azure SSML pronunciation and browser transcript mismatch detection to support compact identifiers. Retained historical long-code normalization tests. Generated institution dispatch UUIDs remain unchanged and require a separate presentation/reference decision before shortening.

Verification: 507 backend tests passed with loopback-only Python network guard; 24 browser transcript tests passed. No provider requests. Saved Claim911_Short_References_Verification_2026-10-25.json and regression JUnit. Runtime services/provider image must be refreshed before voice testing; participant admission remains stale until newly evaluated. Full Bolna case remains unverified.


### Short institution-issued submission reference

New hospital dispatches issue case-local HSP01, HSP02, etc., under the existing locked institution record. UUIDs remain internal and continue to bind receiving-side operations. Voice candidate extraction, workflow service reporting and independent checkpoint verification use the issued short reference. The signed TPA receipt includes and verifies that reference alongside the internal submission UUID and packet hash. Legacy records without short references keep their UUID behavior. No historical records rewritten.

Verification: 29 institution, coordinator, checkpoint, executor and candidate tests passed locally. Rebuilt claim911-speech-provider:local offline from cached dependencies and checked ADM42/HSP01 SSML inside the image with no network or mounts. No provider requests. Full Bolna case still unverified.


### Running sandbox refreshed and complete local-service fixture verified

Restarted only sandbox core 8126, institutions 8114 and product API 8121 with their existing isolated profiles. Operational services were untouched; Bolna broker remains stopped. Executed an explicitly VERIFICATION_FIXTURE-origin case over actual localhost HTTP services using existing offline fixture conversations and silent PCM. All 13 state checkpoints passed, including exactly one unsigned-summary callback, signed receipt carrying HSP01 and final reconciliation. Read-only product status confirmed paid_testing_allowed=false. This is deployed local state/evidence verification, not a Bolna/audio/model pass. Saved Claim911_Short_References_Live_Local_Workflow_2026-10-25.json.


### Azure-only participant validation, deterministic exact-reference boundary

User explicitly approved resuming Azure text validation only. The first fresh short-reference attempt stopped after 13 requests: the adaptive model twice affirmed enhancement ENH18 as initial approval despite a correct mismatch check. No Bolna session started. Added a shared deterministic renderer for pure, single-field reference confirmations, using only the current role record. Status questions and institution operations still use the adaptive participant; revoked authorization is checked before returning. Added exact-reference evaluation so model probabilities cannot overturn a character comparison.

The corrected fresh generation produced all 14 answers (10 adaptive plus 4 deterministic reference replies) in 10 model requests. Independent Pipecat Evals used 28 classifier requests: 13 cases passed, with contradictory goal/metric scores on the correct spaced ADM42 acknowledgment. A separately saved reassessment replaces only the four pure reference scores with explicit exact comparisons, retains all original classifications and source hash, and preserves the ten passing conversational evaluations. Current-image admission validates all 14 under those declared methods; this is text-only proof, not Bolna or audio proof. Across both attempts 51 Azure requests were made; actual billed charges are not inferred from reservations. Paid testing was suspended afterward.

User subsequently approved one full Bolna run and separately approved the persistent gateway URL renewal after automatic approval review rejected the mutation without explicit authorization. Retired only the two old voice-gateway tunnels, created a fresh tunnel to local 8125, verified scoped readiness, applied and read back Bolna URLs with the same model/voice, and refreshed sandbox pins/services. Automatic approval review also rejected probing historical tunnel URLs with a private token; that action was not executed. The approved run c2981322-7006-4adf-b756-45a62119568a is currently active under existing reserve allocation. Single-run wrapper restores budget suspension on exit. Workflow dispatch remains disabled; no automatic retry or telephone call is authorized.


### Single approved Bolna run stopped at hospital dialogue validation

Run c2981322-7006-4adf-b756-45a62119568a verified caregiver_intake_confirmed, then stopped at the hospital transcript check. Hospital reference report was saved, but that does not constitute a verified checkpoint. Actual provider dialogue exposed two local gaps: browser compact-code extraction did not recognize losslessly spelled A D M four two; and pure confirmation rendering dropped a candidate when a question repeated the same field after its value. The original hospital participant therefore incorrectly said No while repeating the same candidate. This failed recording is preserved and is not release evidence.

Fixed compact spoken-letter/digit normalization in the browser verifier and retained the earlier same-field candidate in readback parsing while keeping later different-field questions separate. Replayed all four captured hospital confirmations locally: corrected replies are accurate Yes acknowledgments. Wrong digits and wrong reference types remain rejected; status answers remain adaptive. 77 Python checks and 25 browser checks passed. No second Bolna attempt. Budget suspension restored and broker PID52141 stopped. Participant fingerprint changed, so prior admission evidence is now stale and requires explicit revalidation before further paid voice use. Saved Claim911_Bolna_Run_Local_Fix_2026-10-25.json.


### Preserve deterministic replies during interrupted text-evaluation recovery

Existing explicit recovery accepted only answers found in provider model-call telemetry, which no longer covered exact reference replies intentionally rendered without a model. Recovery now verifies those replies against the unchanged case-owned exact-reference contract, while adaptive answers still require saved model provenance. All existing source fingerprint, image, suite, infrastructure-only failure and prior-score constraints remain. Failed semantic evaluations and changed implementations cannot resume. 51 local participant/readback/evaluation checks passed with network denied. No provider calls or paid retry started.


### User directs checkpoint continuation and phase-recording reuse

User explicitly requests that demo development continue the existing case at its unfinished checkpoint rather than repeatedly creating fresh cases. Keep run fbaaf7a5-4223-42c5-bf92-3e6cdd93ce50, preserve its verified phase recordings, and use existing run-id/default preserved-case continuation after explicit uncertainty reconciliation. Do not rerun verified phases for the demo. Current active execution continues normally. A compiled replay must identify resumed execution accurately; partial historical calls are not independently verified full-case completion. Repeated fresh release rehearsals are not the current demo priority under this steering.


### Pending workflow control review after overlong claims close

Current run fbaaf7a5-4223-42c5-bf92-3e6cdd93ce50 verified caregiver intake and hospital references, then stopped on claims closing: assistant exceeded the bounded speech turn after its query report had been saved. No new case or checkpoint advancement. Budget suspended and broker PID65418 stopped.

Added shared report_speech contract: spoken result <=55 words, explicit call_complete, common closing only for terminal reports, instructions separate from spoken text. Query save/idempotent result and refreshed recorded-query context now prescribe the short closing rather than allowing a full recap. Document mismatches/missing uploads remain open; checked documents and unavailable-document reports have truthful terminal outcomes. Packet calls with no dispatch reference remain open and explicitly prohibit resubmission. TPA, insurer and reconciliation status reports remain open while their verified institution artifact is absent. Existing exact approval, signature, consent and independent checkpoint checks remain. No model, voice, duration bound or provider configuration changed.

32 earlier cross-workflow checks passed; final targeted packet/document/query/closing/executor/recovery set: 29 passed. The first local collection exposed an indentation error introduced while editing; it was corrected before any provider request or service reload. Saved Claim911_Pending_Workflow_Control_Review_2026-10-25.json. Running services have not yet loaded these guards. Same-case claims recovery remains required because the report was saved but its audio completion failed.


### Same-case claims recovery implemented and applied

Added exact unchanged-query reconfirmation for isolated sandbox calls after the original call has terminated and before downstream document/approval work. Original query_call_id, query_document_id, query facts and original clock remain immutable; a separate query_confirmation_call_id and event bind the new confirming conversation. Checkpoint verification requires that archived confirming call plus the original document and institution-owned facts. Different facts or downstream work remain rejected.

Extended existing follow-up reconciliation to the claims-discovery checkpoint: verifies earlier phases and unchanged owning-institution facts, then returns the same run to PAUSED without advancing or writing institution state. Applied to fbaaf7a5-4223-42c5-bf92-3e6cdd93ce50; remains checkpoint 2. Run reports now retain successful recordings only from the same run and pinned provider configuration across resumptions; failed attempts remain in original evidence. Verified two retained recordings. 16 local recovery/workflow/checkpoint checks and 8 recording/closing checks passed. No new provider requests. Saved Claim911_Same_Case_Recovery_2026-10-25.json. Running core/product services still require reload before the next voice session.


Reloaded sandbox core (PID83121) and product API (PID83103) with the tested controls; both health checks passed. Existing 14-case fresh participant gate still validates against the actual provider image, so no additional text-generation spend is needed. Broker remains stopped and budget suspended while awaiting explicit same-case paid-resumption approval.


### Verified two-phase replay exported without provider use

Exported caregiver intake and hospital discovery from the preserved run into outputs/Claim911_Verified_Phases_2026-10-25. All 16 WAV segments were bound to archived turn hashes and decoded PCM hashes, and both phase checkpoints independently rechecked against the institution records. The replay explicitly labels 2/13 and unfinished full voice workflow; no outcome or full-case claim was added. Local Chrome loaded every audio segment with positive duration. Human listening review remains required.

Fixed the complete replay exporter to use Bolna browser archive turns, rather than assuming provider callback transcript entries correspond one-to-one to captured audio. Calls without verified browser archives are retained only as AUDIO_NOT_VERIFIED metadata. The completed-run export admission remains unchanged; partial runs cannot use that path. Three replay contract tests passed. No provider requests. Same-case paid-resumption question remains pending.
