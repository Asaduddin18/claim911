# Bolna sandbox validation

The assistant is the pinned Bolna agent. Demo participants use current role-owned
synthetic records, bounded adaptive replies and Azure Speech F0 voices. Azure recognition
reads the actual assistant audio. Bolna's final transcript is required separately
for post-call checks. A successful connection or a convincing conversation does
not establish institution receipt, approval, clearance or payment.

## Before a provider run

1. Start the isolated institution services, coordinator, sandbox API, trusted
   voice gateway and broker using their dedicated private runtime profiles.
   The package workers keep their existing network and filesystem restrictions.
2. Confirm the temporary HTTPS tunnel is alive. Its hostname can expire even
   when local services still work. The broker now authenticates a GET to
   `/voice/sandbox-readiness` before requesting any provider session. A failure
   withholds the mint. The response must identify `sandbox_callback_registry`,
   readiness and disabled phone dispatch.
3. For a renewed tunnel, use `scripts/update_bolna_dialogue_prompt.py` with
   `--runtime`, `--scope sandbox`, `--gateway-url` and `--apply`. It verifies the
   existing live fingerprint, changes only approved fields, reads the complete
   configuration back and updates sandbox pins. Restart the coordinator, product
   API and broker afterwards. Operational pins remain unpromoted by default.
4. Run the local regression suite with the isolated runtime profiles and the Node
   voice checks. Wrong-role access, altered packets, uncertain dispatch, wrong
   identifiers and missing evidence must fail locally before paid testing.
5. Confirm the daily credit verification and existing bounded reservations allow
   the run. No top-up, telephone dispatch or silent provider substitution is
   part of this workflow.

## Staged execution

Run `scripts/check_simulator_local.py` first. It exercises the shared participant/control contracts with network connections denied and does not require provider profiles. The workflow runner and paid text evaluator enforce this preflight before provider construction. This does not establish model or audio quality.

Then use `scripts/evaluate_participant_text.py`. Its default is a zero-request
inventory. `--execute-provider` runs the bounded fourteen-case text suite using the
existing small Azure model and Pipecat Evals. `--capture` can score a saved suite
without regenerating answers; that replay is not a fresh audio admission gate.
The fresh passing report binds the corpus, participant implementation and
provider-image hashes. The adaptive audio runner rejects absent, failed or stale
evidence before creating a session. These checks test the role players, not the
Bolna assistant. Both need separate evidence.

From the project root, run `scripts/run_sandbox_workflow.py` with the configured
Python runtime, `--fresh --transport bolna-browser --participant-mode adaptive`
and the configured Node runtime. During integration, `--until-checkpoint 2`
limits the first check to intake and hospital references. After a pass, continuing
without `--fresh` preserves that case and its verified checkpoints.
Use `--phase rehearsal` for the release rehearsals after the text gate passes;
this uses the existing rehearsal allocation rather than increasing any ceiling.

The assistant fingerprint cannot change partway through a counted full run.
The three release runs must each start fresh and complete all 13 checkpoints
with the same reviewed configuration. Partial passes and historical runs using
another model do not count. Review the complete audio before release.

## Failure and recovery

The broker's private SQLite `sandbox_bolna_attempts` table records stages and a
known execution ID without storing the ephemeral browser session or call token.
`MINT_UNCERTAIN` and `MINT_REQUESTED` require provider reconciliation.
`CALLBACK_ROUTE_FAILED` means a provider session exists but credentials were
withheld. `READY` means the callback route and scoped recording access were
secured. A duplicate call ID cannot mint again.

Use `scripts/reconcile_bolna_mint.py --runtime ... --run-id ... --call-id ...
--execution-id ...` to inspect a known execution. It requires a terminal provider
status, exact synthetic call/case binding and an uncertain local run. It appends
evidence only. It never advances a checkpoint, clears a review hold or starts
another session. Unknown execution identity requires read-only provider history
inspection first.

For a conversation failure, inspect the archived provider transcript, recognized
audio journal, participant replies and tool results together. The participant
waits through bounded hold announcements and ends media on the common closing.
The close cannot complete a checkpoint. Identifier normalization accepts literal
or individually spelled letters/digits and hyphens; it does not repair similar
codes. Missing or incorrect readback values cannot receive full confirmation.

Preserve failed recordings and run reports. Diagnose the common contract, add
the appropriate local regression, then verify it before another provider run.
Never treat a replay or offline fixture as live Bolna evidence.

## Recognition alignment

The browser precheck pairs actual provider user turns in chronological order and rejects changed identifiers or unexpected turn counts. In parent-controlled mode only, ordinary nonexact wording is explicitly deferred to semantic review. The trusted Python runner evaluates the actual provider conversation against role facts and injected utterances before archive submission. Low scores or unavailable evaluation stop the run. No provider transcript is rewritten, and passing dialogue does not establish institution state.

`scripts/evaluate_saved_bolna_dialogue.py` can review a failed saved transcript using role-bounded synthetic facts. It defaults to a zero-request inventory; `--execute-provider` permits one budgeted text judge. It never mints a session or advances the original case. Each output path must be new so failures remain inspectable.

The long-turn regression is `product/scripts/test-bolna-long-audio.mjs`. It uses only a local WebRTC pair, no provider profile and zero paid operations. It exercises incremental capture beyond the live ring duration and verifies the fixed per-turn bound. Run it after capture changes.

After a provider-image change, run a fresh text suite with `--publish-gate`. It preserves the immutable output report and publishes a private last-successful snapshot at `sandbox/participant-text-gate.json`. CLI and UI jobs use that snapshot by default. A stale image, source hash or failed suite still blocks admission; saved-capture evaluations cannot publish it.

Uploaded-candidate confirmation guidance is shared through coordinator/voice_guidance.py and returned in the real scoped context, not only the historical model adapter. All report writes need freshly fetched context, especially when an institution uploads a document during the call. One-reference confirmation avoids long, ambiguous bulk readbacks.

The harness records live_transcript_lookups. The v3 SDK provides no transcript event, so the scoped execution read is opportunistic with a four-second bound. Only a question at the exact current reply position is eligible. No current text means audio recognition is used; it is not evidence that the SDK supports live transcripts. Closing detection remains tied to captured audio to avoid early hangup from a transcript that arrives ahead of playback.


### Isolated entry-stage voice debugging

Use the existing workflow runner with `--fresh --component hospital_references_reported --phase rehearsal --participant-mode adaptive --transport bolna-browser` to test the hospital reference conversation without paying to repeat intake. All regular provider configuration, participant gate, consent and evidence requirements apply. The synthetic consent is explicitly fixture-supplied, not represented as a completed caregiver voice checkpoint. Component reports and UI are labeled COMPONENT and cannot establish full-case completion. Do not use this mode to claim a release pass; the full 13-checkpoint run and three consecutive fresh-case gate remain required.


### Screen the preserved full-case release streak

Run `python scripts/check_release_evidence.py --reports .. --output ../Claim911_Release_Evidence_Status.json` from the project root. This performs no provider requests. It checks the latest three distinct full Bolna cases, exact reviewed configuration consistency, all 13 independent evidence gates, every expected voice purpose, archived Bolna provenance and semantic conversation results. Component tests cannot qualify; failed full cases break the streak. Fixture-tolerant verification cannot qualify. Repeated exports of one case count once. This is screening of exported reports, not fresh verification of the database, signatures or recordings. Human audio review and the other MVP requirements remain separate gates.


A claims-only stage test can use `--fresh --component claims_query_discovered --prepare-only`. Its final request reference is an explicitly supplied synthetic starting fixture, not proof of a prior voice investigation. Inspect preparation, then execute that run with `--run-id <prepared UUID>` and the usual approved transport/phase. Historical failed query reports remain untouched. This component cannot count toward full-case completion or the release streak.

### Worker runtime and paused spending

The queued worker passes its private sandbox runtime explicitly through `--runtime`. Direct CLI invocations can also pass `--runtime /private/runtime/root`; the profile must remain isolated and phone-disabled. Genuine queued work stays queued without acquiring a lease or incrementing attempts while execution is disabled or paid testing is paused. Offline verification fixtures are separate and do not establish a provider pass.
