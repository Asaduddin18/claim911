# Bolna-led voice testing approach

## What established test suites do

Voice-agent teams normally test at two levels. Fast scripted scenarios pin a particular exchange, expected response and tool call. Slower audio scenarios test the real microphone and speaker path, including transcription, identifiers, latency, turn-taking, interruptions and hang-up behavior. Adaptive simulated callers add coverage for varied question wording, while deterministic scripted callers keep regressions reproducible. Each run saves the conversation and is evaluated against explicit criteria.

Pipecat Evals and LiveKit Agent Simulations both document this pattern. Their built-in harnesses run agents integrated with those frameworks, so a green result against a Pipecat assistant would not prove the Bolna assistant behaves correctly. Claim911 must run the actual configured Bolna agent for any release claim about assistant behavior.

## Claim911 test layers

1. **Offline contract checks:** pytest verifies role permissions, case ownership, exact tool arguments, consent, evidence gates, configuration fingerprint checks and synthetic institution state. No provider session or audio is needed.
2. **Scripted Bolna browser checks:** Playwright opens the official Bolna Web-Call SDK, starts the pinned agent, feeds a controlled caregiver or desk utterance through a virtual microphone, and captures the browser session, transcript, tool calls and final sandbox state. These tests isolate one behavior at a time, such as asking about the missing signed summary or preserving the final authorization reference.
3. **Adaptive participant runs:** a role-bounded synthetic caller listens to Bolna's latest spoken answer, transcribes it, and answers that question using only the assigned synthetic desk's facts. It may clarify or ask the desk to repeat, but cannot call institution tools or alter records. A dialogue evaluator scores relevance, role consistency, fact accuracy, repetition, identifiers, turn-taking and interruption recovery.
4. **Independent workflow verification:** after each scripted or adaptive conversation, Claim911's verifier checks the actual synthetic institution records, uploaded evidence, receiving-side receipt and checkpoint order. A conversation judge cannot mark a checkpoint complete.
5. **Release runs:** execute the full case from fresh isolated state three times with the same pinned Bolna agent fingerprint. Preserve each failure, audio recording, transcript, tool audit, configuration fingerprint and independent checkpoint report. Replays and Pipecat-assistant runs are not counted as Bolna passes.

## Participant audio and safety boundary

The participant is the only simulated side. Use licensed, natural-sounding synthetic voices and role-private facts. Feed their audio into the browser session through a controlled audio-input adapter. Capture Bolna's real audio output and corresponding provider transcript. The harness should wait for the assistant turn to finish before sending a normal reply, with separate tests that intentionally interrupt it.

The documented v3 Web-Call SDK events cover connection state, call start/end, errors, microphone permission and audio level. They do not expose a streaming transcript or remote audio frame callback. A dynamic participant therefore needs a separate, explicitly configured speech recognizer or a deterministic turn script driven by a verified audio boundary. Do not assume the provider's post-call transcript is available soon enough to answer during the live call. [Bolna Web-Call SDK event reference](https://github.com/bolna-ai/web-call#events--callon-event-handler--offevent-handler--onceevent-handler)

The external Bolna agent remains the assistant. Its short-lived tool token identifies one call and one environment. The public voice gateway routes the token only to that environment's scoped coordinator. For sandbox sessions, a trusted broker holds the Bolna key and can mint sessions only for a prepared synthetic run. The sandbox worker and its packages receive neither the Bolna key nor operational credentials. No sandbox test can dispatch a telephone call.

Pipecat may still supply audio fixtures or reusable evaluation ideas, but its assistant pipeline is a separate adapter and never substitutes for Bolna evidence. Hindi remains deferred.

## Reuse boundaries

- **Bolna Web-Call SDK:** actual browser/WebRTC session to the assistant, using an authenticated backend-minted ephemeral session.
- **Playwright:** browser lifecycle, microphone fixture setup, call events and UI behavior.
- **pytest:** deterministic policy, tool, security-boundary and state-verification tests.
- **Pipecat Evals concepts:** scripted versus adaptive scenarios and evaluation criteria. Its runtime is not the assistant under test. Pipecat Evals runs a Pipecat-integrated agent, so it cannot certify the hosted Bolna assistant.
- **axe-core:** accessibility checks for the caregiver and sandbox journeys.

There is no ready-made open-source library that simulates role-specific callers into a hosted Bolna WebRTC session while preserving Claim911's evidence boundaries. Keep that adapter small and use the established pieces around it: Playwright drives the browser, the Bolna SDK carries the assistant's real audio, and a deterministic scenario actor answers from a private role-specific fact sheet. Add an adaptive caller only after the scripted suite is stable. It may use a model to interpret the latest assistant turn and phrase a natural answer, but it cannot access tools or write case state. A separate evaluator checks turn relevance and dialogue quality; pytest checks the actual case state.

## Recommended test harness for the Bolna demo

Use a layered test pyramid rather than making every edit a live voice session:

1. **Fast deterministic checks on every change:** pytest asserts typed tool arguments, role boundaries, consent, reference handling, institution writes and final state against the isolated synthetic database. Playwright checks the three surfaces and accessibility. No provider calls are needed.
2. **Scripted Bolna browser cases during integration:** the real configured Bolna agent answers a small set of controlled cases. Playwright starts the official browser SDK from a user gesture, supplies synthetic audio through a virtual microphone, and retains the provider transcript, call metadata and audio. Keep scripted turn expectations exact and short so a mismatch is diagnosable.
3. **Adaptive participant runs after scripted cases are stable:** capture the Bolna remote audio from the SDK's configured audio element, detect end of turn, transcribe the audio locally, then let a role-bounded synthetic actor answer from the current synthetic institution record. A fixed participant actor can be deterministic first; optional paraphrasing can be added after question-to-answer relevance is reliable. The actor has no institution tools and cannot alter records.
4. **Release rehearsal:** run the full case three times from fresh sandbox state with a pinned Bolna configuration. A separate evaluator checks transcript quality, and the independent verifier checks all thirteen state checkpoints. Humans listen to the complete recordings before the demo.

For local ASR, `faster-whisper` is a practical MIT-licensed option. It is batch transcription, so the harness should first wait for a clear end-of-turn signal and then transcribe the captured utterance. Do not call it streaming or use an unstable partial transcript to decide a protected action. [faster-whisper](https://github.com/SYSTRAN/faster-whisper)

For participant TTS, test a frozen Kokoro-82M English voice locally; its upstream model card lists Apache-2.0 weights, and the inference library is open source. Confirm the selected voice and its dependencies before bundling. [Kokoro-82M model card](https://huggingface.co/hexgrad/Kokoro-82M), [Kokoro inference library](https://github.com/hexgrad/kokoro)

Piper is another local TTS option, but the actively maintained OHF-Voice engine is GPL-3.0. Each voice model has its own terms, so check the exact model card before redistributing it. [OHF-Voice Piper](https://github.com/OHF-Voice/piper1-gpl)

Pin model and package versions, download assets before isolation, verify hashes, and give the synthetic actor runtime no network, operational credentials or host filesystem access. A Bolna provider error must fail the run visibly. Do not silently substitute Pipecat, a local assistant or another voice transport. Do not use participant TTS output as evidence that Bolna's own recognition or assistant behavior passed.

LiveKit Agent Simulations document a useful pattern: run scenario-based simulated callers, judge conversation expectations, then independently check final application state. That runtime starts a LiveKit agent, so it is a reference pattern rather than a direct Bolna harness. Pipecat Evals has the same boundary for Pipecat-integrated agents. [LiveKit Agent Simulations](https://docs.livekit.io/testing/simulations/), [Pipecat Evals scenarios](https://reference-server.pipecat.ai/en/stable/api/pipecat.evals.scenario.html)

This separation keeps provider compatibility, speech quality and institution correctness as distinct claims with distinct evidence.

## Current integration evidence, 24 October

The local capture regression now uses two real browser RTCPeerConnections, not
only a generated MediaStream. It sends the known synthetic sentence through
WebRTC, records the receiver track with MediaRecorder, converts it to 16 kHz
PCM and transcribes it through the isolated Azure Speech provider. The complete
sentence was recovered: "This is a synthetic hospital test. The discharge
summary needs a signature." The receiver reported 337 packets received and
zero packets lost. The same check verifies that Bolna's stopped preflight mic
track cannot stop the separately cloned live synthetic microphone track.

The synthetic microphone also requires a continuously running silent source.
With no source connected to its MediaStreamDestination while idle, Chrome sent
zero RTP packets. This was reproduced using the local WebRTC pair. Connecting
a running ConstantSourceNode with an exact zero value restored 38 packets in
the same 750 ms interval, without adding noise or changing participant speech.
This regression now prevents an apparently live microphone track from passing
when its media clock is actually idle. Continuous AudioWorklet capture also
passes the complete known-sentence recognition check; the parallel recorder
remains available for comparison.

From `product/`, use `npm run test:voice-contracts` for offline dialogue checks
and `npm run test:voice-loopback` for local browser/media checks. The latter uses
`fixtures/audio/reference-english.wav`, containing only the synthetic sentence
above. Optional private provider configuration enables its separate speech
recognition assertion. Neither command creates a Bolna session.

`product/scripts/bolna-dialogue-evaluation.mjs` evaluates the provider's saved
speaker-labelled transcript. It verifies the immediately preceding question,
the participant answer and the assistant's subsequent response in order. Eight
offline regression cases include the original unrelated-answer defect, a later
unrelated question hiding an earlier expected question, missing user speech,
missing follow-up and an assistant quoting a participant answer. The harness
fails if these transcript checks fail, even if WebRTC connected successfully.

Scenario-scripted mode supplies a versioned expected reply after the detected
audio boundary, then checks the actual Bolna transcript after hangup. It is an
integration regression, not adaptive-participant evidence. Adaptive mode now
transcribes each actual Bolna audio turn and passes that turn to the selected
synthetic role actor. The actor replies from its synthetic record and the
response audio is injected into the browser microphone. Unknown questions no
longer select one of two guessed answer categories. The existing role actor is
still a bounded scenario actor, not proof of natural multi-desk behavior.

### Verified hosted question-and-answer regression

The first passing question-aware Bolna exchange is run
`964a0ad4-25f8-4f0e-ba29-e757891d2285`. The participant recognized the actual
opening question, answered from caregiver facts, and Bolna asked a relevant
follow-up about missing documents. The provider transcript independently
confirmed question, participant answer and assistant follow-up in order.
The browser receiver reported zero concealed samples; no phone call was used.

Two defects caused the earlier failures: the idle virtual microphone emitted
no RTP, and comfort noise kept the energy-level turn detector open. The first
now has a local packet-clock regression. The second uses the already installed
Silero VAD through Pipecat in a read-only, mount-free, network-disabled container.
Silero finds the end of the preserved opening at 5,696 ms instead of the former
14-second timeout. Pipecat supplies only speech detection, never the assistant.

The same Bolna agent now uses 600 ms Deepgram endpointing, 600 ms incremental
delay and final-transcript response generation. Voice, prompt and scoped tools
were preserved and verified after the update. Timing settings are now part of
the reviewed configuration fingerprint. The adaptive mode is the harness
default; scripted mode remains available only as a separately labelled regression.

Run `3431dc6c-ab94-42fb-beca-a4475088cbe2` adds a second actual Bolna turn. The
caregiver answers the assistant's live document question and Bolna gives a
relevant follow-up. Both turns pass provider-transcript ordering and content
checks; the run still has zero case checkpoints and no Bolna report-tool writes.

The adaptive harness now transcribes each live Bolna turn, sends the exact turn
and prior dialogue to a budgeted language model, and synthesizes a short answer
from the selected role's synthetic record. The actor has no tools, cannot write
workflow state and cannot see another institution's record. Transcription,
model reply and speech synthesis each reserve against the existing sandbox
ledger; a stale credit check or exhausted budget stops the turn. The harness
also rejects database profiles that do not point to the
local `claim911_sandbox` database. Its turn limit is eight.

The workflow runner now defaults to Bolna browser transport. It launches the
real browser session for each voice checkpoint, streams captured Bolna audio to
a trusted host controller, and asks the selected synthetic role actor to answer
from its own institution record. Desk actors can call only the operations
already authorized for that role and checkpoint. The Bolna API key stays in the
trusted session broker; participant audio/model work goes through the isolated
provider container. The host controller verifies the completed provider
transcript and archives its captured audio before the existing independent
checkpoint verifier can advance the case. A worker lease heartbeat keeps long
voice turns current and stops if permission or the lease changes.

The run stores only the reviewed Bolna assistant fingerprint. A changed
fingerprint fails closed. Pipecat remains an explicitly selected legacy path and
does not count as Bolna evidence. Offline Python tests for participant history
and the workflow adapter, the existing provider archive and run contracts pass;
the browser harness also passes syntax checks and its dialogue/role tests. These
changes have not yet been exercised against a live Bolna session. The sandbox
product API and coordinator are not running, so the 13 checkpoints, three fresh
runs and complete audio review remain unverified. Hindi remains deferred.

## References

- [Bolna Web-Call SDK](https://github.com/bolna-ai/web-call)
- [Pipecat Evals overview](https://docs.pipecat.ai/pipecat/evals/overview)
- [Pipecat Evals source and scenario model](https://github.com/pipecat-ai/pipecat)
- [Playwright end-to-end testing](https://playwright.dev/docs/intro)
- [Piper TTS engine](https://github.com/rhasspy/piper)
- [Piper voice models](https://github.com/rhasspy/piper-voices)
- [LiveKit Agent Simulations](https://docs.livekit.io/testing/simulations/)
- [LiveKit agent testing CLI](https://docs.livekit.io/reference/developer-tools/livekit-cli/agent/testing/)
