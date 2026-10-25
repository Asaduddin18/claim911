"""Free speech accounting requires a fresh, credential-bound management proof."""
import hashlib,json
from pathlib import Path
from datetime import datetime,timezone,timedelta
from psycopg.types.json import Jsonb
from sandbox.spend import settle

SPEECH_OPERATIONS={'bolna-participant-transcribe','bolna-participant-synthesize'}


def current_speech_proof(profile_path,proof_path):
    profile_path=Path(profile_path);proof=json.loads(Path(proof_path).read_text())
    raw=profile_path.read_bytes()
    if proof.get('profile_sha256')!=hashlib.sha256(raw).hexdigest():
        raise ValueError('Provider profile changed since free speech verification')
    validate_proof(proof,json.loads(raw)['speech'])
    return proof


def validate_proof(proof,speech,*,now=None):
    now=now or datetime.now(timezone.utc)
    checked=datetime.fromisoformat(proof['verified_at'])
    if (proof.get('sku')!='F0' or proof.get('kind')!='SpeechServices' or proof.get('region')!='eastus'
        or proof.get('credential_sha256')!=hashlib.sha256(speech['api_key'].encode()).hexdigest()
        or speech.get('sku')!='F0' or speech.get('region')!='eastus'
        or proof.get('no_updates_since_resource_write') is not True
        or checked.tzinfo is None or not timedelta(0)<=now-checked<=timedelta(hours=24)):
        raise ValueError('Fresh credential-bound free speech evidence required')
    created=datetime.fromisoformat(proof['resource_created_at'])
    configured=datetime.fromisoformat(proof['profile_saved_at'])
    effective=datetime.fromisoformat(proof['last_resource_write_at'])
    if created.tzinfo is None or configured.tzinfo is None or configured<created or configured>checked:
        raise ValueError('Speech configuration chronology is unverified')
    if effective.tzinfo is None or not created<=effective<=checked:
        raise ValueError('Verified free-tier interval is invalid')
    return max(configured,effective)


def reconcile_speech(conn,proof,speech):
    since=validate_proof(proof,speech)
    conn.execute('ALTER TABLE coordinator.sandbox_spend ADD COLUMN IF NOT EXISTS cost_evidence jsonb')
    rows=conn.execute("SELECT request_id,reserved_micro FROM coordinator.sandbox_spend WHERE operation=ANY(%s) AND state='UNCERTAIN' AND created_at>=%s FOR UPDATE",
        (sorted(SPEECH_OPERATIONS),since)).fetchall()
    for row in rows:
        settle(conn,row['request_id'],confirmed_charge_micro=0)
        conn.execute('UPDATE coordinator.sandbox_spend SET cost_evidence=%s WHERE request_id=%s',
            (Jsonb(proof),row['request_id']))
    return {'reconciled_requests':len(rows),'released_reserved_micro':sum(r['reserved_micro'] for r in rows),
        'confirmed_charge_micro':0,'scope':'VERIFIED_F0_SPEECH_ONLY','model_holds_changed':False}
