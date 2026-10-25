"""Provider-returned token usage, never inferred billing or released reservations."""
import re
from uuid import UUID
from psycopg.types.json import Jsonb


def usage_evidence(result):
    if not isinstance(result,dict):return None
    model=result.get('model');usage=result.get('usage')
    if not isinstance(model,str) or not re.fullmatch(r'gpt-5-mini(?:-\d{4}-\d{2}-\d{2})?',model) or not isinstance(usage,dict):return None
    counts={key:usage.get(key) for key in ('prompt_tokens','completion_tokens','total_tokens')}
    if any(type(value) is not int or not 0<=value<=1_000_000 for value in counts.values()):return None
    if counts['total_tokens']!=counts['prompt_tokens']+counts['completion_tokens']:return None
    for key,detail,parent in [('cached_tokens','prompt_tokens_details','prompt_tokens'),('reasoning_tokens','completion_tokens_details','completion_tokens')]:
        value=usage.get(detail,{}).get(key) if isinstance(usage.get(detail,{}),dict) else None
        if type(value) is int and 0<=value<=counts[parent]:counts[key]=value
    return {'version':1,'source':'PROVIDER_RESPONSE_TOKEN_USAGE','model':model,'usage':counts,
            'billing_verified':False,'reservation_released':False}


def store_usage(conn,request_id,result):
    evidence=usage_evidence(result)
    if evidence is None:return False
    # Schema migration belongs to normal ledger initialization, not a model call.
    changed=conn.execute('UPDATE coordinator.sandbox_spend SET cost_evidence=%s WHERE request_id=%s',
        (Jsonb(evidence),UUID(str(request_id))))
    if changed.rowcount!=1:raise ValueError('Token usage must bind to an existing reservation')
    return True


def attach_report_usage(conn,report):
    if report.get('scope')!='TEXT_PARTICIPANT_ONLY' or not isinstance(report.get('model_calls'),list) or len(report['model_calls'])>200:
        raise ValueError('Bounded participant report required')
    run_id=UUID(str(report['run_id']));bound=[]
    for call in report['model_calls']:
        request_id=UUID(str(call['request_id']))
        row=conn.execute('SELECT run_id,operation FROM coordinator.sandbox_spend WHERE request_id=%s',(request_id,)).fetchone()
        if not row or str(row['run_id'])!=str(run_id) or row['operation']!=call['operation'] or row['operation'] not in {'persona','judge'}:
            raise ValueError('Usage report must bind each request to its original run and operation')
        if usage_evidence(call) is not None:bound.append((request_id,call))
    for request_id,call in bound:store_usage(conn,request_id,call)
    return len(bound)
