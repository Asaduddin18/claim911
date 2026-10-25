# Voice participant architecture decision

24 October 2026. Status: revised after user approval of adaptive participants;
complete Bolna workflow validation remains open.

## Current decision

Use deterministic synthetic institution state and adaptive role-bounded people
for the demo. Keep fixed scripted participants for precise regressions. The
caregiver and institution participants now share the existing bounded model
adapter. Each receives only its own record and the actual latest caller turn.
Institution tools remain explicit, argument-free capabilities with independently
checked permissions. Caregiver knowledge has a read-only adapter with no tools.
Unknown identifiers and spoken internal field names fail locally. Language
grounding is also evaluated semantically; identifier validation alone is not a
proof that every sentence is true.

The existing pytest suite supplies deterministic workflow and boundary checks.
The existing credential-free Pipecat Evals worker evaluates the new text-first
participant corpus. The trusted Azure adapter supplies its model calls. This
tests participant conversation behavior without audio; it does not test Bolna's
assistant or award workflow checkpoints. Bolna remains the only demo assistant,
with distinct later browser-audio and complete-case release evidence.

No LiveKit migration or second assistant framework was introduced. The reusable
blocks already in the project cover the required actor, evaluation, browser and
institution boundaries. The earlier phrase-matching approach below is retained
as implementation history, rather than the selected demo behavior.

Free speech accounting now uses management-verified resource identity, matched
credentials, current F0 SKU and a proven resource-write interval. Only eligible
speech holds are settled to zero. Earlier ambiguous holds and model holds remain.
Successful new speech calls can use the fresh, profile-bound proof; absent or
expired proof retains the conservative reservation. No limits or tiers change.

## Outcome

Bolna remains the Claim911 assistant. Scripted synthetic participants answer
the latest actual question from their own current institution record. Their
speech is generated with the existing role-specific Azure Speech F0 voices.
Institution operations and independent checkpoint verification remain separate
from dialogue quality.

## Options considered

| Option | Benefit | Cost or limitation | Decision |
| --- | --- | --- | --- |
| Existing Azure Speech STT/TTS for live participants, Bolna transcript for post-call verification | Reuses configured credentials, voices and restricted egress; no participant LLM inference; avoids blocking on an unavailable live execution transcript | STT can mishear references; captured audio must be complete; Azure availability still matters | Selected after live evidence |
| Local whisper.cpp English model | Offline recognition, Apple Silicon support and no per-request cloud recognition charge | Requires model download, model/image pinning, isolated deployment and latency/accuracy validation; cannot restore speech already cut off by capture | Optional fallback if measured recognition failures remain after capture correction |
| Azure realtime speech model as a participant | Flexible speech understanding and natural generated replies | Adds a second reasoning model, inference spend, deployment dependencies and fact-drift risk; does not meet the current scripted-participant preference | Not selected for this demo |

Sources: [Azure short-audio recognition and detailed results](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-speech-to-text-short),
[whisper.cpp](https://github.com/ggml-org/whisper.cpp), and
[Azure realtime audio](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/audio-real-time).

## Evidence and common fixes

The failed run `3e551a96-4025-4bed-bd71-a235cc42a923` stopped at checkpoint 0.
Its second captured clip contained 2.62 seconds of PCM but only 15 active 20 ms
windows at the diagnostic energy threshold. This measurement is a signal
diagnostic, not a transcript or proof of what was spoken.

Inspection found a deterministic capture defect: after VAD reported quiet, the
harness waited a further 1.6 seconds, then selected a duration-sized tail from
the current buffer. That shifts the selected window into later silence and can
discard the beginning of the spoken question. Replacing the speech model alone
would leave this defect intact.

Capture now selects an absolute audio-clock range from before the VAD speech
start through the VAD quiet event. Wall-clock waiting does not change that
range. The audio worklet keeps a bounded rolling buffer, and an unavailable
window fails explicitly instead of returning a partial turn.

The existing Azure recognizer now requests detailed results and preserves the
service-ranked transcript and confidence values. Confidence is retained as
diagnostic evidence; an uncalibrated threshold is not treated as proof that an
answer is correct. Empty or invalid recognition still stops participation.

Both scripted execution paths now use a heard question. The old standalone
smoke path that answered two prewritten expected questions has been removed.
The evaluator requires a live question source for every participant mode.
Scripted desks refresh their own record each turn, expose exact released
document references and revisions, and distinguish an open query from one
resolved by the institution. Unsupported caregiver questions request
clarification. The claims follow-up objective requests institution-owned query
resolution and enhancement linkage when these remain pending.

On a participant failure, the parent requests browser cleanup and diagnostic
preservation before a bounded hard stop. It does not automatically redial or
retry an uncertain action.

## Latest live evidence and closing correction

Run `421aaba5-eade-429c-bc29-4985767e8e4b` connected and ended. Its
participant answer matched the actual Bolna question, and Bolna saved the
caregiver intake report. Audio recognition succeeded with the timestamped
capture. It remains a failed run with zero verified checkpoints: the assistant
omitted the common closing sentence and later reprompted. Repeated live
execution-transcript requests returned 503, so that polling was removed from
the live response path. The installed Bolna browser SDK exposes audio-level
events but no live transcript event. Final execution transcripts remain required
for archive and dialogue verification.

The base caregiver prompt instructed a shorter ending that conflicted with the
appended common close. The shared prompt and tool result now supply the complete
closing. Successful report responses also carry the common closing instruction
for all roles without granting task or evidence completion. The update gateway
now preserves explicitly confirmed dispatch references and callback times;
previously its summary-only schema dropped these structured fields. The narrow
provider prompt/tool update was read back and fingerprinted for sandbox use.
The operational fingerprint was intentionally not promoted. Trusted sandbox
services still need refreshing before the next provider validation.

357 backend regressions and 20 Node contract checks pass. The local WebRTC
regression recovered 1.3 seconds of voiced speech lost by the old selection.
These do not prove the revised closing prompt works in a provider call.

## Remaining proof

Local loopback and contract checks do not prove Bolna behavior. The complete
13-checkpoint Bolna workflow, three consecutive fresh runs, mandatory fault
coverage and complete human audio review are still release gates. Hindi stays
deferred. No local replay or Pipecat assistant run counts toward those gates.

### Intake confirmation and evaluation repair, 24 October

Do not whitelist recognition errors such as “this charge” versus “discharge”. The saved evidence failed the small-model semantic check and stays failed. The current Bolna intake instead summarizes the core concern once and asks the caregiver to confirm or correct it before reporting. This is a standard closed-loop conversation pattern for decision-relevant understanding, not a scenario-specific replacement dictionary. Intake remains limited to the concern and one confirmation; no repeat consent, language, document or reference questions are added.

The shared prompt and fresh call objective both contain the same behavior. The sandbox transport requires the confirmation exchange before accepting current intake evidence. Semantic evaluation may recognize an explicit repair and confirmation, but cannot infer one from an acknowledgment or successful tool write. Institution verification remains separate. The updated agent configuration was read back and sandbox service pins were refreshed; historical runs cannot be counted under the new fingerprint.
