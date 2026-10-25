# Simulator testing boundaries

Bolna remains the Claim911 assistant. The adaptive synthetic participant remains a role-scoped model in provider tests. Local test doubles do not replace either one in the demonstration.

## What changed

The participant text session is independent of speech recognition, speech synthesis and semantic judging. `ParticipantDialogue` accepts the observed question, delegates to the same participant used by the voice runner, and retains a bounded reply and history. This allows local tests to supply controlled model/tool responses and reproduce failures without provider access.

Recognition remains a transport concern. The browser uses actual Bolna transcript text when available; otherwise the existing live audio recognition path is still required. The current SDK has not been proven to expose every live turn as text. Text tests cannot establish that speech was heard correctly.

Speech output is a separate stage. A failed synthesis request leaves its generated reply available in the same session. Reprocessing that question does not regenerate a participant answer or repeat its synthetic institution operation. There is no automatic speech retry. Lost generation after a possible institution operation leaves the session failed and requires reconciliation. This cache is in memory, not durable recovery after process loss. Session identity cannot change role or actor.

Known language/permission topic mismatches stop before synthesis. A complete conversation with a known critical topic mismatch does not invoke the paid semantic judge. Other conversational criteria remain unassessed, never marked passed. This is a narrow deterministic rejection rule, not a general-purpose semantic judge.

## Local checks first

From the project directory, using the project's Python environment:

```text
python scripts/check_simulator_local.py --output /absolute/path/to/new-report.json
```

No runtime provider configuration is needed. The command uses pytest, test doubles and a plugin that rejects network connections. It checks participant history, bounded retries, failed speech isolation, identifier guards, known topic mismatches, common hold/closing behavior, policy contracts and release-evidence rejection. Reports explicitly say that Bolna, model quality, audio and workflow state were not verified.

Both the full sandbox workflow runner and the paid participant-text evaluator run this local preflight before constructing their provider adapter. A failure aborts execution. Passing it does not override suspended spending, fresh participant evaluation, reviewed agent configuration, permission or evidence gates.

The independent local institution/database integration suite remains separate. It tests receipt, document, decision and payment evidence using explicitly simulated calls. It does not establish Bolna behavior.

## Provider verification stays separate

1. Local participant/control regression tests.
2. Local institution/workflow integration with fake calls and independently checked state.
3. Budgeted text model evaluation when spending is allowed.
4. Focused audio compatibility checks.
5. Complete Bolna workflow and human listening review.

No local replay or test double qualifies as a Bolna pass. Three fresh full-case runs and the other release gates remain required by the approved plan. Paid testing is currently stopped.
