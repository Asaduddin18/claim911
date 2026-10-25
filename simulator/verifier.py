"""Verification contains only the recipient public key, never a signing secret."""
import base64
from datetime import datetime, timezone, timedelta
import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class VerificationError(ValueError):
    pass


def verify_receipt(public_key, receipt, expected, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        envelope = receipt['envelope']
        raw = json.dumps(envelope,sort_keys=True,separators=(',',':'),default=str).encode()
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key)).verify(
            base64.b64decode(receipt['signature'],validate=True),raw)
    except Exception as exc:
        raise VerificationError('Invalid recipient signature') from exc
    if envelope.get('simulated') is not True or envelope.get('source') != 'demo-designated-claims':
        raise VerificationError('Unrecognized receipt source or mode')
    if envelope.get('status') != 'RECEIVED' or envelope.get('decision_status') != 'PENDING':
        raise VerificationError('Unsupported receipt status')
    fields = ['case_id','submission_id','request_type','reference','revision','patient_id','packet_hash','route_id','destination']
    for key in fields:
        if key not in expected or envelope.get(key) != expected[key]:
            raise VerificationError(f'Receipt does not match {key}')
    try:
        issued = datetime.fromisoformat(envelope['issued_at'])
        received = datetime.fromisoformat(envelope['received_at'])
        dispatched = datetime.fromisoformat(expected['dispatched_at'])
        if any(x.tzinfo is None for x in [issued,received,dispatched]):
            raise ValueError('Timezone required')
        if issued>now+timedelta(seconds=30) or now-issued>timedelta(minutes=10):
            raise ValueError('Receipt expired or from future')
        if received<dispatched or received>issued:
            raise ValueError('Receipt chronology invalid')
    except (KeyError,ValueError,TypeError) as exc:
        raise VerificationError('Invalid receipt chronology') from exc
    return {'verified':True,'receipt_id':envelope['receipt_id'],'simulated':True,
            'coordination_state':'BLOCKER_RESOLVED','decision_state':'PENDING'}
