# Sandbox security boundary

The audio dependency virtual environment is not an isolation boundary. Do not run
scenario packages on the host. The dedicated Colima profile must have no host
mounts and no SSH agent forwarding. Always select `colima-claim911-sandbox`
explicitly; do not use the default Docker context.

This initial probe has no network, host mounts, secrets, ports or writable root.
It runs as a non-root user without Linux capabilities, with resource limits and
no privilege escalation. Its image build may download the base image; runtime
package installation is prohibited. The probe is a baseline, not an audio runner.

Run from this directory:

```sh
docker --context colima-claim911-sandbox compose build probe
docker --context colima-claim911-sandbox compose run --rm probe
```

If the Compose plugin is unavailable, the tested equivalent is:

```sh
docker --context colima-claim911-sandbox build -f Dockerfile.probe -t claim911-isolation-probe:local .
docker --context colima-claim911-sandbox run --rm --network none --read-only \
  --user 65532:65532 --cap-drop ALL --security-opt no-new-privileges:true \
  --pids-limit 32 --memory 128m --cpus 0.5 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777 claim911-isolation-probe:local
```

`sandbox/broker.py` now implements synthetic institution tool capabilities:
one run, case and role; expiry and revocation; bounded requests; no URL proxy;
idempotent replay; and uncertain-result reconciliation. Its token issuer is a
private Python interface, never an HTTP endpoint. Keep this trusted component
outside the package runner. The institution executor still enforces exact
disclosure approval. These capabilities do not grant provider inference access.
Restarting the broker invalidates worker grants; the controller must reconcile
institution state before issuing replacement grants.

Before enabling audio, implement a restricted broker outside the package runner.
It must own provider secrets, enforce model/speech-only requests, synthetic case
scope, spend limits, request sizes and destinations. The runner must have no
arbitrary URL proxy, host gateway access, operational API access, database
credentials, real phone transport or signing keys. Use only an internal network
to that broker and sandbox services. Re-run escape checks on the final topology.
The baseline's network-none success does not prove a later networked topology.

Copy only allowlisted source files into images. Never use the repository root or
private runtime directory as an image build context. Inspect image contents,
container configuration and VM mounts before release. Container isolation reduces
risk; it is not a promise against every operating-system vulnerability.

## Current implementation and final-topology audit

The package VAD and Pipecat Evals workers now run credential-free through bounded standard-input/output protocols with network disabled. The trusted standard-library provider adapter runs separately on an internal network through a destination-allowlisted egress proxy. It receives only the credentials needed for one approved provider operation through standard input. It cannot choose arbitrary provider URLs. Bolna browser sessions are minted by the separate trusted broker, never by a package worker.

Run `scripts/audit_sandbox_boundary.py --runtime <private-runtime> --output <new-report>` from the project root to inspect the current provider topology and VM settings, then execute the existing isolation probe inside the actual audio and evaluation images. The audit makes no provider requests. On 24 October it verified both images, network denial, absent host mounts and credential environment, read-only root, non-root execution, capability removal and disabled agent forwarding. This evidence is narrower than a complete security review, and must be regenerated when the topology changes.
