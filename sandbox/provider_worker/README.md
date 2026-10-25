# Trusted Azure validation adapter

This separate image uses Python's standard library and pinned num2words 0.5.14
(with docopt 0.6.2) for deterministic currency pronunciation. Currency aliases
use international English number words while retaining the exact source amount
in SSML. It receives only the
credentials needed for a particular validation through stdin. No host directory,
Docker socket, database credential or operational account is mounted. It runs as
a non-root user with a read-only root and dropped capabilities.

The speech adapter is fixed to the configured eastus F0 resource and the English
and Hindi voices. The model adapter accepts only a verified Azure OpenAI hostname
and deployed GPT-5 mini, bounds context/output, disables proxies and refuses
redirects. No HTTP server or credential-minting endpoint is exposed.

English/Hindi TTS-to-STT round-trips and one model connection request were
validated. The model request had a committed USD 0.10 reservation; actual billing
is awaiting provider telemetry. Speech used the free F0 resource. The first
speech attempt returned IncompleteRead; its bounded diagnostic retry succeeded.
No telephone calls or complete agent scenarios ran.

These one-shot checks use a trusted adapter with outbound connectivity. This is
not the final networked sandbox topology. Before live worker integration, place
it behind the scoped broker and a restricted egress path, enforce durable spend
reservations on every paid operation, and repeat isolation tests with that actual
network topology. Never put provider credentials in the Pipecat worker.
