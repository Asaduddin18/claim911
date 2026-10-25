# Isolated Pipecat worker

Build only from this directory. The context contains an exact dependency lock,
fixed broker-only Pipecat processors and a small trusted evaluation scenario.
It contains no runtime configuration, provider key or institution fixture secrets.

The image was built and its Pipecat 1.13.0 pipeline and evaluation scenario were
loaded under non-root, read-only, network-disabled runtime restrictions. Ten
boundary checks also passed against this actual package image. These results are
not an audio conversation or full workflow result.

`pipeline.py` converts bounded mono 16 kHz PCM utterances through broker STT,
conversation and TTS stages. Its HTTP client has one fixed broker address,
disables environment proxies and redirects, and does not retry uncertain turns.
The broker must authenticate each session, own model context, execute scoped tools
and enforce the durable spend ledger. The live broker server and Pipecat Evals
transport still need connecting. Do not enable direct internet for this worker.

Run the offline check:

```sh
docker --context colima-claim911-sandbox build -t claim911-audio-worker:local .
docker --context colima-claim911-sandbox run --rm --network none --read-only \
  --user 65532:65532 --cap-drop ALL --security-opt no-new-privileges:true \
  --pids-limit 64 --memory 768m --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777 claim911-audio-worker:local
```

Dependency download happens at image build time. Runtime package installation is
not enabled. The base image is digest-pinned. The lock includes upstream optional
packages; no vector database service is started or used. Final license inventory
and dependency minimization remain release tasks.

## Verified stdio execution

The worker now has a network-disabled execution path in `run_stdio.py`.
`sandbox/stdio_control.py` owns the scoped grant and forwards only validated JSON
operations over stdin/stdout. The worker receives no capability, provider key,
database credential or host mount. Output size, request count, run duration and
container resources are bounded. Timed-out workers are removed by their unique
owned container name. Returned PCM and text must match the trusted provider results.

One real Pipecat STT/model/TTS turn passed in 8.891 seconds using synthetic input
speech, GPT-5 mini and free Azure Speech. The result is a focused records-desk
question, not an institution decision. The session was revoked after the check.
All ten isolation probes passed again on the exact updated image. No one-shot
worker remained running. This proves the Pipecat frame pipeline and stdio bridge;
it does not prove Pipecat Evals/RTVI, adaptive callers or the complete discharge case.

The HTTP client remains an optional deployment path and is not exposed to the
network-disabled worker. Do not enable direct network access to make it work.
The scoped audio protocol is implemented in `sandbox/audio_gateway.py` and is also
used by the stdio bridge. It owns role-private conversation context, consent
version checks before and after provider execution, expiry, revocation, exact
transcription/response binding, idempotency and durable model cost hooks.
