# Public release validation

Validated on 25 October 2026.

- Gitleaks 8.30.1, using its default rules plus one exact non-secret field-name exception: zero findings.
- Exact comparison against private configuration secret values and the verified recipient number: zero matches in the public export.
- No runtime profiles, databases, signing keys, installed dependencies or transient session material are staged.
- Network-denied local simulator contracts: 125 passed.
- Node voice, role, dialogue, capture and audio-archive contracts: 37 passed.
- Included finalized synthetic conversations: 13; checkpoint verifications: 13.
- Latest video: 1920 × 1080, 24 fps, approximately 3:59; full decode passed.
- All media files fit GitHub’s normal individual-file limit; Git LFS is not required.

These source-export checks start no new Bolna sessions. They supplement the recorded case evidence, and do not establish three fresh end-to-end runs or production readiness.
