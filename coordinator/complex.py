"""Evidence-driven complex discharge coordination; no institution credentials."""
from coordinator.voice_contracts import CAREGIVER_INTAKE_CLOSING,report_speech
import base64
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID, uuid4
from datetime import timedelta
from typing import Literal
from coordinator.caregiver import caregiver_summary
from coordinator.workflow_calls import packet_for,approval_valid,DOCUMENT_PURPOSES

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Depends, HTTPException, Header
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field


def canonical(v):
    return json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()


def digest(v):
    return hashlib.sha256(canonical(v)).hexdigest()


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')


class QueryEvidence(Strict):
    call_id: UUID
    document_id: UUID


class DocumentEvidence(Strict):
    document_id: UUID


class Approve(Strict):
    source: Literal['CAREGIVER_OPERATOR_ATTESTATION','CAREGIVER_SCOPED_SESSION','SYNTHETIC_REHEARSAL_FIXTURE'] = 'CAREGIVER_OPERATOR_ATTESTATION'
    accepted: bool
    packet_hash: str
    confirmation: str = Field(min_length=10,max_length=1000)


class ReceiptEvidence(Strict):
    dispatch_document_id: UUID
    receipt: dict


class QueryReport(Strict):
    query_reference: str = Field(min_length=1,max_length=100)
    claim_reference: str = Field(min_length=1,max_length=100)
    admission_id: str = Field(min_length=1,max_length=100)
    enhancement_reference: str = Field(min_length=1,max_length=100)
    received_at: str = Field(min_length=10,max_length=80)
    required_documents: list[Literal['itemized_bill','signed_discharge_summary','implant_invoice']]
    enhancement_linked: bool


class DocumentReport(Strict):
    document_kind: Literal['itemized_bill','signed_discharge_summary','implant_invoice']
    document_reference: str = Field(min_length=1,max_length=100)
    ready: bool
    summary: str = Field(min_length=1,max_length=2000)


class UpdateReport(Strict):
    summary: str = Field(min_length=1,max_length=2000)
    callback_at: str | None = Field(default=None,max_length=100)
    dispatch_reference: str | None = Field(default=None,max_length=100)


class WorkflowReport(Strict):
    operation: Literal['REPORT_QUERY','REPORT_DOCUMENT','REPORT_UPDATE']
    details: dict


KINDS={'itemized_bill':'billing','signed_discharge_summary':'medical_records','implant_invoice':'implant_store'}


def install(app,db,operator,incident,require_consent,event,config,bound_call):
    def load(conn,id,lock=False):
        row=conn.execute('SELECT data FROM coordinator.complex_workflows WHERE incident_id=%s'+(' FOR UPDATE' if lock else ''),(id,)).fetchone()
        if not row:
            raise HTTPException(404,'No document-query workflow')
        return row['data']

    def save(conn,id,w,type,payload):
        conn.execute('UPDATE coordinator.complex_workflows SET data=%s WHERE incident_id=%s',(Jsonb(w),id))
        event(conn,id,type,payload)

    def document(conn,id,did):
        d=conn.execute('SELECT * FROM coordinator.documents WHERE id=%s AND incident_id=%s',(did,id)).fetchone()
        if not d:
            raise HTTPException(422,'Evidence document must belong to this incident')
        try:
            value=json.loads(bytes(d['data']))
            if not isinstance(value,dict):
                raise ValueError()
            return value
        except (ValueError,TypeError):
            raise HTTPException(422,'Institution JSON evidence required')

    packet=packet_for
    current_approval=approval_valid

    def view(row,w):
        result=dict(w)
        tasks=[{'kind':k,'owner':owner,'state':'EVIDENCE_COLLECTED' if k in w['documents'] else 'NEEDED',
                'document_id':w['documents'].get(k,{}).get('document_id')} for k,owner in KINDS.items() if k in w['query']['required_documents']]
        result['tasks']=tasks
        complete=all(t['state']=='EVIDENCE_COLLECTED' for t in tasks)
        result['approval_current']=current_approval(row,w)
        result['packet']=packet(row,w) if complete else None
        result['packet_hash']=digest(result['packet']) if complete else None
        if not row['consent_active']:
            result['next_step']='CONSENT_REQUIRED'
        elif not complete:
            result['next_step']='COLLECT_DOCUMENTS'
        elif not result['approval_current']:
            result['next_step']='EXACT_PACKET_APPROVAL'
        elif not w.get('receipt'):
            result['next_step']='HOSPITAL_SUBMISSION_AND_TPA_RECEIPT'
        elif not w.get('query_resolution'):
            result['next_step']='TPA_QUERY_AND_ENHANCEMENT_FOLLOWUP'
        elif not w.get('decision'):
            result['next_step']='INSURER_REVIEW'
        elif not w.get('clearance'):
            result['next_step']='HOSPITAL_BILLING_RECONCILIATION'
        elif w['clearance']['envelope']['discharge_clearance']!='ISSUED':
            result['next_step']='PATIENT_BALANCE_REVIEW'
        else:
            result['next_step']='DISCHARGE_CLEARED_REFUND_PAYMENT_UNVERIFIED'
        result['caregiver_summary']=caregiver_summary(row,w)
        result['synthetic']=True
        result['decision_status']=w.get('decision',{}).get('envelope',{}).get('outcome','PENDING')
        return result

    @app.get('/v1/incidents/{id}/complex',dependencies=[Depends(operator)])
    def get(id:UUID):
        with db() as conn:
            return view(incident(conn,id),load(conn,id))

    @app.post('/v1/incidents/{id}/complex/query',dependencies=[Depends(operator)],status_code=201)
    def query(id:UUID,body:QueryEvidence):
        with db() as conn:
            row=incident(conn,id,True);require_consent(row)
            call=conn.execute('SELECT * FROM coordinator.calls WHERE id=%s AND incident_id=%s',(body.call_id,id)).fetchone()
            if not call or call['participant_role']!='claims' or not call['transcript']:
                raise HTTPException(422,'Attributed claims conversation required')
            q=document(conn,id,body.document_id)
            refs=q.get('references',{})
            if (q.get('patient_id')!=row['patient_id'] or refs.get('final_request')!=row['reference']
                or not q.get('admission_id') or not refs.get('query') or not refs.get('claim')
                or q.get('query_state')!='OPEN' or set(q.get('required_documents',[]))!=set(KINDS)):
                raise HTTPException(422,'Query identity or supported document requirements do not match')
            if conn.execute('SELECT 1 FROM coordinator.complex_workflows WHERE incident_id=%s',(id,)).fetchone():
                raise HTTPException(409,'Query already recorded; preserve existing evidence')
            return save_query(conn,id,row,call,q,body.document_id)

    def save_query(conn,id,row,call,q,did):
        discovery=conn.execute("SELECT payload FROM coordinator.events WHERE incident_id=%s AND type='HOSPITAL_REFERENCES_REPORTED' ORDER BY created_at DESC LIMIT 1",(id,)).fetchone()
        if discovery and (q['admission_id']!=discovery['payload']['admission_id'] or q['references']['enhancement']!=discovery['payload']['enhancement_reference']):
            raise HTTPException(409,'Claims admission or enhancement differs from the hospital report; clarify before proceeding')
        w={'query':q,'query_document_id':str(did),'query_call_id':str(call['id']),
           'source_mode':call['mode'],'documents':{},'revision':1,'approval':None,'receipt':None}
        conn.execute('INSERT INTO coordinator.complex_workflows(incident_id,data) VALUES(%s,%s)',(id,Jsonb(w)))
        conn.execute("UPDATE coordinator.incidents SET state='DOCUMENT_QUERY_OPEN',version=version+1 WHERE id=%s",(id,))
        event(conn,id,'DOCUMENT_QUERY_RECORDED',{'call_id':str(call['id']),'document_id':str(did),'mode':call['mode']})
        return query_result(row,w)

    def query_result(row,w):
        return view(row,w)|report_speech('The outstanding query and required documents are recorded. Document collection is the next step.')

    @app.post('/v1/incidents/{id}/complex/documents',dependencies=[Depends(operator)])
    def collect(id:UUID,body:DocumentEvidence):
        with db() as conn:
            row=incident(conn,id,True);require_consent(row);w=load(conn,id,True)
            d=document(conn,id,body.document_id);kind=d.get('kind')
            if kind not in KINDS or d.get('owner')!=KINDS[kind] or not d.get('ready'):
                raise HTTPException(422,'Released document from the responsible hospital desk required')
            if d.get('admission_id')!=w['query']['admission_id'] or d.get('patient_id')!=row['patient_id']:
                raise HTTPException(422,'Document belongs to a different patient or admission')
            if d.get('hash')!=digest({k:v for k,v in d.items() if k!='hash'}):
                raise HTTPException(422,'Institution document content hash mismatch')
            if kind=='signed_discharge_summary' and not d.get('signed_by'):
                raise HTTPException(422,'Institution signature required')
            if kind=='itemized_bill' and (not isinstance(d.get('amount_inr'),int) or d['amount_inr']<=0 or d.get('revision',0)<2):
                raise HTTPException(422,'Current revised itemized bill required')
            if w.get('receipt'):
                raise HTTPException(409,'Verified packet is immutable; open a new query for later revisions')
            prior=w['documents'].get(kind)
            if prior and prior['record']==d:
                return view(row,w)
            w['documents'][kind]={'record':d,'document_id':str(body.document_id),'support_status':'UPLOADED_INSTITUTION_RECORD'}
            w['revision']+=1;w['approval']=None
            save(conn,id,w,'QUERY_DOCUMENT_COLLECTED',{'document_id':str(body.document_id),'kind':kind,'revision':w['revision'],'approval_invalidated':True})
            return view(row,w)

    @app.post('/v1/incidents/{id}/complex/approve',dependencies=[Depends(operator)])
    def approve(id:UUID,body:Approve):
        with db() as conn:
            row=incident(conn,id,True);require_consent(row);w=load(conn,id,True)
            if body.source=='SYNTHETIC_REHEARSAL_FIXTURE' and not row['is_test']:
                raise HTTPException(403,'Synthetic caregiver approval is restricted to test incidents')
            v=view(row,w)
            if not body.accepted or not v['packet'] or body.packet_hash!=v['packet_hash']:
                raise HTTPException(409,'Approve the complete, current displayed packet hash')
            w['approval']={'packet_hash':body.packet_hash,'consent_version':row['consent_version'],
                           'revision':w['revision'],'confirmation':body.confirmation,'source':body.source,
                           'recorded_by':{'SYNTHETIC_REHEARSAL_FIXTURE':'SYNTHETIC_CAREGIVER_ROLE_FIXTURE','CAREGIVER_SCOPED_SESSION':'AUTHENTICATED_CASE_CAREGIVER','CAREGIVER_OPERATOR_ATTESTATION':'OPERATOR_ON_BEHALF_OF_CAREGIVER'}[body.source],
                           'recipient':'demo-tpa-complex','approved_at':datetime.now(timezone.utc).isoformat()}
            save(conn,id,w,'QUERY_PACKET_APPROVED',w['approval'])
            return view(row,w)

    @app.post('/v1/incidents/{id}/complex/revoke-approval',dependencies=[Depends(operator)])
    def revoke_approval(id:UUID):
        with db() as conn:
            row=incident(conn,id,True);w=load(conn,id,True)
            prior=w.get('approval');w['approval']=None
            if prior:
                save(conn,id,w,'QUERY_PACKET_APPROVAL_REVOKED',{'packet_hash':prior['packet_hash'],'previously_received':bool(w.get('receipt')),'past_disclosure_recalled':False})
            return view(row,w)

    @app.post('/v1/incidents/{id}/complex/verify',dependencies=[Depends(operator)])
    def verify(id:UUID,body:ReceiptEvidence):
        with db() as conn:
            row=incident(conn,id,True);require_consent(row);w=load(conn,id,True)
            if not current_approval(row,w):
                raise HTTPException(409,'Current exact-packet approval required')
            dispatch=document(conn,id,body.dispatch_document_id)
            expected=packet(row,w)
            if dispatch.get('packet')!=expected or dispatch.get('packet_hash')!=digest(expected):
                raise HTTPException(422,'Hospital dispatch differs from approved packet')
            receipt=body.receipt;e=receipt.get('envelope',{})
            try:
                Ed25519PublicKey.from_public_bytes(base64.b64decode(config['receipt_public_key'])).verify(
                    base64.b64decode(receipt['signature']),canonical(e))
            except Exception:
                raise HTTPException(422,'Recipient signature verification failed')
            binding={'case_id':str(row['case_id']),'submission_id':dispatch.get('id'),'packet_hash':digest(expected),
                     'query_id':w['query']['references']['query'],'claim_id':w['query']['references']['claim'],
                     'status':'RECEIVED','decision_status':'PENDING','source':'demo-tpa-complex','synthetic':True}
            if dispatch.get('submission_reference') is not None:
                from coordinator.reference_evidence import hospital_dispatch_reference
                try:binding['submission_reference']=hospital_dispatch_reference(dispatch)
                except ValueError:raise HTTPException(422,'Invalid hospital submission reference') from None
            if not e.get('receipt_id') or any(e.get(k)!=v for k,v in binding.items()):
                raise HTTPException(422,'Receipt identity, query or packet does not match')
            prior=conn.execute('SELECT incident_id FROM coordinator.verified_receipts WHERE id=%s',(e['receipt_id'],)).fetchone()
            if prior and prior['incident_id']!=id:
                raise HTTPException(409,'Receipt already bound to another incident')
            if w.get('receipt') and w['receipt']!=receipt:
                raise HTTPException(409,'A receipt has already been verified')
            if w.get('receipt')==receipt:
                return view(row,w)
            conn.execute('INSERT INTO coordinator.verified_receipts(id,incident_id,envelope,signature) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (e['receipt_id'],id,Jsonb(e),receipt['signature']))
            w['receipt']=receipt
            save(conn,id,w,'QUERY_RESPONSE_RECEIPT_VERIFIED',{'receipt_id':e['receipt_id'],'packet_hash':digest(expected)})
            conn.execute("UPDATE coordinator.incidents SET state='QUERY_RESPONSE_RECEIVED',decision_state='PENDING',version=version+1 WHERE id=%s",(id,))
            return view(row,w)


    def signed_document(conn,id,did,key_name,expected):
        value=document(conn,id,did)
        envelope=value.get('envelope',{})
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(config[key_name])).verify(
                base64.b64decode(value['signature'],validate=True),canonical(envelope))
            issued=datetime.fromisoformat(envelope['issued_at'])
            if issued.tzinfo is None or issued.timestamp()>datetime.now(timezone.utc).timestamp()+30:
                raise ValueError()
        except Exception:
            raise HTTPException(422,'Institution signature or issuance time invalid')
        if not envelope.get('synthetic') or any(envelope.get(k)!=v for k,v in expected.items()):
            raise HTTPException(422,'Institution event is for a different case, query, packet or issuer')
        return value

    @app.post('/v1/incidents/{id}/complex/query-resolution',dependencies=[Depends(operator)])
    def resolution(id:UUID,body:DocumentEvidence):
        with db() as conn:
            row=incident(conn,id,True);require_consent(row);w=load(conn,id,True)
            if not w.get('receipt') or not current_approval(row,w):
                raise HTTPException(409,'Current approved packet and verified recipient receipt required')
            value=signed_document(conn,id,body.document_id,'receipt_public_key',{
                'source':'demo-tpa-complex','kind':'QUERY_ANSWERED','case_id':str(row['case_id']),
                'packet_hash':digest(packet(row,w)),'query_id':w['query']['references']['query'],
                'claim_id':w['query']['references']['claim'],'query_state':'ANSWERED',
                'receipt_id':w['receipt']['envelope']['receipt_id'],
                'enhancement_reference':w['query']['references']['enhancement'],'enhancement_linked':True})
            if w.get('query_resolution') and w['query_resolution']!=value:
                raise HTTPException(409,'Query resolution already verified')
            if w.get('query_resolution')==value:
                return view(row,w)
            w['query_resolution']=value
            save(conn,id,w,'TPA_QUERY_AND_ENHANCEMENT_VERIFIED',{'document_id':str(body.document_id)})
            conn.execute("UPDATE coordinator.incidents SET state='AWAITING_INSURER_DECISION',version=version+1 WHERE id=%s",(id,))
            return view(row,w)

    @app.post('/v1/incidents/{id}/complex/decision',dependencies=[Depends(operator)])
    def decision(id:UUID,body:DocumentEvidence):
        with db() as conn:
            row=incident(conn,id,True);require_consent(row);w=load(conn,id,True)
            if not w.get('query_resolution') or not current_approval(row,w):
                raise HTTPException(409,'Verified query completion and current packet approval required')
            value=signed_document(conn,id,body.document_id,'insurer_public_key',{
                'source':'demo-insurer-complex','kind':'INSURER_DECISION','case_id':str(row['case_id']),
                'packet_hash':digest(packet(row,w)),'query_id':w['query']['references']['query'],
                'claim_id':w['query']['references']['claim'],'reference':row['reference']})
            e=value['envelope'];bill=w['documents']['itemized_bill']['record']['amount_inr']
            if (e.get('outcome') not in {'AUTHORIZED','DENIED'} or type(e.get('payable_inr')) is not int
                or not 0<=e['payable_inr']<=bill or e.get('bill_inr')!=bill
                or (e['outcome']=='DENIED' and e['payable_inr']!=0)):
                raise HTTPException(422,'Insurer decision amounts invalid')
            if w.get('decision') and w['decision']!=value:
                raise HTTPException(409,'Insurer decision already verified')
            if w.get('decision')==value:
                return view(row,w)
            w['decision']=value
            save(conn,id,w,'INSURER_DECISION_VERIFIED',{'document_id':str(body.document_id),'outcome':e['outcome']})
            conn.execute("UPDATE coordinator.incidents SET state='FINAL_DECISION_RECEIVED',decision_state=%s,version=version+1 WHERE id=%s",(e['outcome'],id))
            return view(row,w)

    @app.post('/v1/incidents/{id}/complex/clearance',dependencies=[Depends(operator)])
    def clearance(id:UUID,body:DocumentEvidence):
        with db() as conn:
            row=incident(conn,id,True);require_consent(row);w=load(conn,id,True)
            if not w.get('decision') or not current_approval(row,w):
                raise HTTPException(409,'Verified insurer decision and current approval required')
            e=w['decision']['envelope']
            value=signed_document(conn,id,body.document_id,'hospital_public_key',{
                'source':'demo-hospital-billing','kind':'DISCHARGE_RECONCILIATION','case_id':str(row['case_id']),
                'packet_hash':digest(packet(row,w)),'reference':row['reference'],'decision_id':e['id'],
                'bill_inr':e['bill_inr'],'insurer_payable_inr':e['payable_inr'],'refund_payment_state':'NOT_VERIFIED'})
            c=value['envelope'];patient=e['bill_inr']-e['payable_inr'];deposit=c.get('deposit_inr')
            if type(deposit) is not int or deposit<0 or any(type(c.get(k)) is not int for k in
                ['patient_payable_inr','refund_due_inr','balance_due_inr']):
                raise HTTPException(422,'Hospital amounts invalid')
            if (c['patient_payable_inr']!=patient or c['refund_due_inr']!=max(0,deposit-patient)
                or c['balance_due_inr']!=max(0,patient-deposit)
                or c.get('discharge_clearance')!=('ISSUED' if patient<=deposit else 'BALANCE_PENDING')):
                raise HTTPException(422,'Hospital reconciliation does not balance')
            if w.get('clearance') and w['clearance']!=value:
                raise HTTPException(409,'Hospital clearance already verified')
            if w.get('clearance')==value:
                return view(row,w)
            w['clearance']=value
            save(conn,id,w,'DISCHARGE_RECONCILIATION_VERIFIED',{'document_id':str(body.document_id),
                'refund_due_inr':c['refund_due_inr'],'refund_payment_state':'NOT_VERIFIED'})
            state='DISCHARGE_CLEARED' if c['discharge_clearance']=='ISSUED' else 'PATIENT_BALANCE_PENDING'
            conn.execute('UPDATE coordinator.incidents SET state=%s,version=version+1 WHERE id=%s',(state,id))
            return view(row,w)


    @app.post('/v1/tools/workflow')
    def workflow_report(body:WorkflowReport,x_call_token:str=Header(default='')):
        call=bound_call(x_call_token)
        with db() as conn:
            event(conn,call['incident_id'],'VOICE_TOOL_USED',{'call_id':str(call['id']),
                'tool':'workflow_report','operation':body.operation,'purpose':call['purpose']})
        from coordinator.workflow_calls import WORKFLOW_ROLES
        if call['purpose'] not in WORKFLOW_ROLES:
            raise HTTPException(403,'This call has no complex workflow operation scope')
        try:
            parsed={'REPORT_QUERY':QueryReport,'REPORT_DOCUMENT':DocumentReport,'REPORT_UPDATE':UpdateReport}[body.operation].model_validate(body.details)
        except Exception:
            raise HTTPException(422,'Workflow report fields are incomplete or invalid')
        collect_id=None;reference_candidates=[]
        with db() as conn:
            id=call['incident_id'];row=incident(conn,id,True);require_consent(row)
            from coordinator.sandbox_calls import require_current_context
            require_current_context(conn,call)
            if row['state']=='HUMAN_REVIEW':
                raise HTTPException(409,'Incident requires human review')
            if body.operation=='REPORT_QUERY':
                if call['purpose']!='QUERY_DISCOVERY' or call['participant_role']!='claims':
                    raise HTTPException(403,'Only the scoped claims discovery call can report the query')
                if set(parsed.required_documents)!=set(KINDS) or len(parsed.required_documents)!=len(KINDS):
                    raise HTTPException(422,'Unsupported or duplicate document requirements; human review required')
                from coordinator.reference_evidence import query_candidates,candidate_report_conflicts
                fields=('query_reference','claim_reference','admission_id','enhancement_reference')
                slips=query_candidates(conn,row)
                conflicts=candidate_report_conflicts({k:getattr(parsed,k) for k in fields},
                    [{k:s['details'][k] for k in fields} for s in slips])
                if conflicts:
                    raise HTTPException(422,{'code':'REFERENCE_CONFIRMATION_REQUIRED','fields':conflicts,
                        'instruction':'The report conflicts with the uploaded claims query slip. Confirm each named field separately or stop for review. Claim and final request references are different fields.'})
                try:
                    received=datetime.fromisoformat(parsed.received_at)
                    if received.tzinfo is None:
                        raise ValueError()
                except ValueError:
                    raise HTTPException(422,'Original receiving timestamp needs an explicit timezone')
                q={'patient_id':row['patient_id'],'admission_id':parsed.admission_id,
                   'references':{'query':parsed.query_reference,'claim':parsed.claim_reference,
                                 'enhancement':parsed.enhancement_reference,'final_request':row['reference']},
                   'query_state':'OPEN','required_documents':parsed.required_documents,
                   'received_at':parsed.received_at,'target_at':(received+timedelta(hours=3)).isoformat(),
                   'enhancement_linked':parsed.enhancement_linked,'synthetic':True,
                   'support_status':'REPORTED_FROM_CALL'}
                existing=conn.execute('SELECT data FROM coordinator.complex_workflows WHERE incident_id=%s',(id,)).fetchone()
                if existing:
                    prior=existing['data']
                    if prior['query']==q:
                        if str(call['id']) in {prior['query_call_id'],prior.get('query_confirmation_call_id')}:
                            return query_result(row,prior)
                        original=conn.execute('SELECT mode,state FROM coordinator.calls WHERE id=%s AND incident_id=%s',(prior['query_call_id'],id)).fetchone()
                        if (call['mode']=='SANDBOX_AUDIO' and prior.get('source_mode')=='SANDBOX_AUDIO'
                            and original and original['mode']=='SANDBOX_AUDIO' and original['state'] in {'COMPLETED','FAILED','CANCELLED'}
                            and not prior.get('documents') and not prior.get('approval') and not prior.get('receipt')):
                            prior['query_confirmation_call_id']=str(call['id'])
                            save(conn,id,prior,'QUERY_REPORT_RECONFIRMED',{'call_id':str(call['id']),'original_call_id':prior['query_call_id'],'document_id':prior['query_document_id'],'original_receiving_time_preserved':True})
                            return query_result(row,prior)
                    raise HTTPException(409,'Query already recorded; use follow-up and preserve source history')
                did=uuid4();raw=canonical(q)
                conn.execute("INSERT INTO coordinator.documents(id,incident_id,filename,content_type,kind,content_hash,data,status) VALUES(%s,%s,'call-reported-query.json','application/json','other',%s,%s,'REPORTED_FROM_CALL')",
                             (did,id,hashlib.sha256(raw).hexdigest(),raw))
                return save_query(conn,id,row,call,q,did)
            if body.operation=='REPORT_UPDATE' and call['purpose'] in {'CAREGIVER_INTAKE','QUERY_DISCOVERY','HOSPITAL_REFERENCE_DISCOVERY'} and not conn.execute(
                'SELECT 1 FROM coordinator.complex_workflows WHERE incident_id=%s',(id,)).fetchone():
                report={'call_id':str(call['id']),'purpose':call['purpose'],'source_mode':call['mode'],
                        'operation':body.operation,'details':parsed.model_dump(),'support_status':'REPORTED_FROM_CALL'}
                event_type='CAREGIVER_INTAKE_REPORTED' if call['purpose']=='CAREGIVER_INTAKE' else 'QUERY_DISCOVERY_UPDATE'
                if not conn.execute("SELECT 1 FROM coordinator.events WHERE incident_id=%s AND type=%s AND payload=%s",
                                    (id,event_type,Jsonb(report))).fetchone():
                    event(conn,id,event_type,report)
                return {'recorded':True,'support_status':'REPORTED_FROM_CALL','verified_state_changed':False,
                        'next_step':'HOSPITAL_REFERENCE_DISCOVERY' if call['purpose'] in {'CAREGIVER_INTAKE','HOSPITAL_REFERENCE_DISCOVERY'} else 'QUERY_DISCOVERY_PENDING','automatic_callback_scheduled':False,
                        **report_speech(CAREGIVER_INTAKE_CLOSING if call['purpose']=='CAREGIVER_INTAKE' else 'The reported blocker is saved; verification remains separate.')}
            w=load(conn,id,True)
            report={'call_id':str(call['id']),'purpose':call['purpose'],'source_mode':call['mode'],
                    'operation':body.operation,'details':parsed.model_dump(),'support_status':'REPORTED_FROM_CALL'}
            if body.operation=='REPORT_DOCUMENT':
                if DOCUMENT_PURPOSES.get(call['purpose'])!=parsed.document_kind or call['participant_role']!='hospital':
                    raise HTTPException(403,'Document kind is outside this hospital desk call')
                if parsed.ready:
                    docs=conn.execute('SELECT id,data FROM coordinator.documents WHERE incident_id=%s ORDER BY created_at DESC',(id,)).fetchall()
                    for doc in docs:
                        try:
                            value=json.loads(bytes(doc['data']))
                        except (ValueError,TypeError):
                            continue
                        if (isinstance(value,dict) and value.get('kind')==parsed.document_kind
                            and value.get('patient_id')==row['patient_id'] and value.get('admission_id')==w['query']['admission_id']
                            and isinstance(value.get('id'),str) and value['id'] not in reference_candidates):
                            reference_candidates.append(value['id'])
                        if isinstance(value,dict) and value.get('id')==parsed.document_reference and value.get('kind')==parsed.document_kind:
                            collect_id=doc['id'];break
            prior=w.setdefault('reports',[])
            if report not in prior:
                prior.append(report)
                save(conn,id,w,'WORKFLOW_PARTICIPANT_REPORT',report)
        if collect_id:
            result=collect(id,DocumentEvidence(document_id=collect_id))
            result['reported_document_result']='UPLOADED_DOCUMENT_CHECKED'
            result.update(report_speech('The uploaded document has been checked and linked. Other case steps remain separate.'))
            return result
        if body.operation=='REPORT_DOCUMENT' and parsed.ready and reference_candidates:
            from coordinator.identifier_readbacks import readbacks
            spoken=reference_candidates[0].replace('-',' hyphen ').replace('/',' slash ')
            return {'recorded':True,'support_status':'REPORTED_FROM_CALL',
                    'reported_document_result':'REFERENCE_CONFIRMATION_REQUIRED',
                    'reported_document_reference':parsed.document_reference,
                    'uploaded_reference_candidates':reference_candidates,
                    'spoken_readbacks':readbacks({'document_reference':reference_candidates[0]}),
                    'spoken_outcome':f'Please confirm the uploaded document identifier: {spoken}. Is that exactly correct?',
                    'call_complete':False,
                    'instruction':'Say spoken_outcome, pronouncing hyphen and slash aloud. Keep version separate; never silently substitute a candidate. After staff explicitly confirm, report again using that candidate canonical value exactly, including its separators. If not confirmed, stop for review.',
                    'verified_state_changed':False,'next_step':view(row,w)['next_step']}
        if body.operation=='REPORT_DOCUMENT' and not parsed.ready:
            return {'recorded':True,'support_status':'REPORTED_FROM_CALL',
                    'reported_document_result':'REPORTED_UNAVAILABLE',
                    **report_speech('The document delay is recorded. The document is not verified; follow-up is still needed.'),
                    'verified_state_changed':False,'next_step':view(row,w)['next_step']}
        continuation={
            'TPA_QUERY_FOLLOWUP':('query_resolution','Please resolve the outstanding query and link the enhancement in your system, then upload its signed confirmation.'),
            'INSURER_FOLLOWUP':('decision','Please review the complete packet in your system and upload the institution-issued decision if eligible.'),
            'DISCHARGE_FOLLOWUP':('clearance','Please reconcile the verified decision, bill and deposit in your system, then upload the signed billing result.')}
        if body.operation=='REPORT_UPDATE' and call['purpose']=='PACKET_SUBMISSION' and not parsed.dispatch_reference and not parsed.callback_at:
            return {'recorded':True,'support_status':'REPORTED_FROM_CALL','verified_state_changed':False,
                    'next_step':view(row,w)['next_step'],**report_speech("Please confirm the hospital's dispatch reference for the approved packet. If already submitted, do not submit it again.",complete=False)}
        if body.operation=='REPORT_UPDATE' and call['purpose'] in continuation and not parsed.callback_at:
            verified_key,request=continuation[call['purpose']]
            if not w.get(verified_key):
                return {'recorded':True,'support_status':'REPORTED_FROM_CALL','verified_state_changed':False,
                        'next_step':view(row,w)['next_step'],**report_speech('The status note is saved. '+request,complete=False)}
        return {'recorded':True,'support_status':'REPORTED_FROM_CALL',
                'reported_document_result':'AWAITING_UPLOADED_PROOF' if body.operation=='REPORT_DOCUMENT' else None,
                **report_speech('The document report is recorded; please upload its proof.' if body.operation=='REPORT_DOCUMENT' else 'The reported update is recorded. Verification remains separate.',complete=body.operation!='REPORT_DOCUMENT'),
                'verified_state_changed':False,'next_step':view(row,w)['next_step']}

    return get
