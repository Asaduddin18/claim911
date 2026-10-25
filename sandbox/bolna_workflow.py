"""Server-owned Bolna purpose selection for the existing durable scenario."""
from datetime import datetime,timezone
from fastapi import HTTPException
from sandbox.executor import PHASES


def voice_purpose(run,expected_fingerprint,*,now=None):
    now=now or datetime.now(timezone.utc)
    checkpoint=run['checkpoint'];keys=run['manifest']['checkpoints']
    if run.get('origin') not in {'USER_PREPARED','AUDIO_DEMONSTRATION','AUDIO_RUN'}:
        raise HTTPException(409,'Verification fixtures cannot start provider sessions.')
    if checkpoint<0 or checkpoint>=len(keys):
        raise HTTPException(409,'This run has no pending voice checkpoint.')
    if run['state']=='READY' and checkpoint==0:
        pass # Explicit, consented browser compatibility check before worker execution.
    elif run['state']=='RUNNING' and run.get('lease_token') and run.get('lease_until') and run['lease_until']>now:
        pass
    else:
        raise HTTPException(409,'The next voice conversation needs the current scenario worker lease.')
    provider=run.get('provider_configuration') or {}
    if provider.get('transport')=='BOLNA_WEBRTC':
        if provider.get('assistant_config_sha256')!=expected_fingerprint:
            raise HTTPException(409,'The assistant changed during this run. Preserve it for review.')
    elif checkpoint!=0 or provider.get('transport') not in {None,'PIPECAT_STDIO'}:
        raise HTTPException(409,'A run cannot mix completed assistant transports.')
    purpose,_=PHASES[keys[checkpoint]]
    if purpose is None:
        raise HTTPException(409,'This checkpoint requires its separate approval or evidence operation.')
    return purpose
