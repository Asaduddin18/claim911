"""Independent run gates from core records, archived audio and institution reads.

No model output or conversational judge verdict can satisfy these checks.
Only read credentials and institution public keys are required.
"""
import base64,hashlib,io,json,wave
from uuid import UUID
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sandbox.actors import scenario_manifest


class MissingEvidence(Exception):pass


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()


def same_instant(left,right):
    try:
        a=datetime.fromisoformat(left.replace('Z','+00:00'));b=datetime.fromisoformat(right.replace('Z','+00:00'))
        return a.tzinfo is not None and b.tzinfo is not None and a==b
    except (ValueError,TypeError,AttributeError):return False


class CheckpointVerifier:
    def __init__(self,core,institutions,*,read_tokens,public_keys,require_real_audio=True,
                 required_audio_provenance='BOLNA_WEBRTC'):
        self.core=core;self.institutions=institutions
        self._tokens={k:read_tokens[k] for k in ('hospital','claims','insurer')}
        self._keys={k:public_keys[k] for k in ('claims','hospital','insurer')}
        if required_audio_provenance not in {'BOLNA_WEBRTC','PIPECAT_STDIO',None}:
            raise ValueError('Known audio provider provenance required')
        self.required_audio_provenance=required_audio_provenance if require_real_audio else None
        self.require_real_audio=self.required_audio_provenance is not None

    def _get(self,path,role=None):
        response=(self.institutions.get(path,headers={'Authorization':'Bearer '+self._tokens[role]})
                  if role else self.core.get(path))
        response.raise_for_status();return response.json()

    def __call__(self,checkpoint,incident_id,evidence_references):
        result=self.inspect(checkpoint,incident_id)
        return bool(result['passed'] and set(result['evidence_references'])<=set(evidence_references))

    def inspect(self,checkpoint,incident_id):
        refs=[]
        def need(condition,reason):
            if not condition:raise MissingEvidence(reason)
        try:
            incident_id=str(UUID(str(incident_id)))
            need(checkpoint in scenario_manifest()['checkpoints'],'UNKNOWN_CHECKPOINT')
            data=self._get('/v1/incidents/'+str(incident_id));row=data['incident'];w=data.get('complex_workflow') or {}
            need(str(row['id'])==str(incident_id) and row['is_test'] and row['consent_active'],'CONSENTED_SYNTHETIC_CASE_REQUIRED')
            case=str(row['case_id']);calls={str(c['id']):c for c in data['calls']}
            docs={str(d['id']):d for d in data['documents']}
            refs.append('incident:'+str(incident_id))
            def event(kind,**binding):
                found=next((e for e in reversed(data['events']) if e['type']==kind and all(e['payload'].get(k)==v for k,v in binding.items())),None)
                need(found is not None,'EVENT_REQUIRED:'+kind);refs.append('event:'+str(found['sequence']))
                return found['payload']
            def audio(call_id,purpose,role):
                c=calls.get(str(call_id))
                need(c and c['purpose']==purpose and c['participant_role']==role and c['mode']=='SANDBOX_AUDIO' and c['state']=='COMPLETED','COMPLETED_SCOPED_AUDIO_REQUIRED:'+purpose)
                if self.require_real_audio:
                    need(c.get('sandbox_audio_provenance')==self.required_audio_provenance,
                         'REQUIRED_AUDIO_PROVENANCE:'+str(self.required_audio_provenance))
                turns=c['transcript']
                if self.required_audio_provenance=='BOLNA_WEBRTC':
                    archive=self._get(f'/v1/sandbox/incidents/{incident_id}/audio-calls/{call_id}/browser-archive')
                    need(c.get('execution_id') and archive['execution_id']==c['execution_id'],'BOLNA_PROVIDER_EXECUTION_BINDING_REQUIRED')
                    original='\n'.join(t['text'] for t in c['transcript'] if t.get('speaker')=='provider_transcript')
                    need(original and hashlib.sha256(original.encode()).hexdigest()==archive['provider_transcript_sha256'],'BOLNA_PROVIDER_TRANSCRIPT_BINDING_REQUIRED')
                    need(archive.get('assistant_config_sha256'),'REVIEWED_BOLNA_CONFIG_REQUIRED')
                    turns=archive['turns']
                need(len(turns)>=2 and {t['speaker'] for t in turns}=={'assistant','participant'},'BOTH_CONVERSATION_SIDES_REQUIRED')
                artifacts=self._get(f'/v1/sandbox/incidents/{incident_id}/audio-calls/{call_id}/artifacts')
                need(len(artifacts)==len(turns),'EVERY_TURN_REQUIRES_AUDIO')
                for index,(turn,artifact) in enumerate(zip(turns,artifacts)):
                    need(artifact['turn_index']==index and artifact['speaker']==turn['speaker'] and artifact['content_hash']==turn.get('audio_sha256'),'AUDIO_TRANSCRIPT_BINDING_MISMATCH')
                    response=self.core.get(f'/v1/sandbox/incidents/{incident_id}/audio/{artifact["id"]}');response.raise_for_status()
                    with wave.open(io.BytesIO(response.content),'rb') as wav:
                        need((wav.getframerate(),wav.getnchannels(),wav.getsampwidth())==(16000,1,2),'INVALID_AUDIO_FORMAT')
                        pcm=wav.readframes(wav.getnframes())
                    need(pcm and hashlib.sha256(pcm).hexdigest()==artifact['content_hash'],'AUDIO_HASH_MISMATCH')
                refs.append('call:'+str(call_id));return c
            def report(purpose):
                candidates=[r for r in w.get('reports',[]) if r['purpose']==purpose and r.get('source_mode')=='SANDBOX_AUDIO']
                need(candidates,'SCOPED_PARTICIPANT_REPORT_REQUIRED:'+purpose)
                return candidates[-1]
            def raw_document(id):
                need(str(id) in docs,'CASE_DOCUMENT_REQUIRED')
                response=self.core.get(f'/v1/incidents/{incident_id}/documents/{id}');response.raise_for_status()
                raw=response.content
                need(hashlib.sha256(raw).hexdigest()==docs[str(id)]['content_hash'],'STORED_DOCUMENT_HASH_MISMATCH')
                refs.append('document:'+str(id));return json.loads(raw)
            def signed(value,issuer,source,kind=None):
                envelope=value['envelope']
                Ed25519PublicKey.from_public_bytes(base64.b64decode(self._keys[issuer])).verify(base64.b64decode(value['signature']),canonical(envelope))
                need(envelope.get('synthetic') is True and envelope.get('case_id')==case and envelope.get('source')==source,'INSTITUTION_EVENT_IDENTITY_MISMATCH')
                if kind:need(envelope.get('kind')==kind,'INSTITUTION_EVENT_KIND_MISMATCH')
                need(w.get('packet') and envelope.get('packet_hash')==hashlib.sha256(canonical(w['packet'])).hexdigest(),'INSTITUTION_PACKET_MISMATCH')
                return envelope
            def institution_query():return self._get(f'/claims/complex/{case}/query','claims')
            def receipt():
                value=w.get('receipt');need(value,'RECEIVING_SIDE_RECEIPT_REQUIRED')
                e=signed(value,'claims','demo-tpa-complex')
                need(e['status']=='RECEIVED' and e['decision_status']=='PENDING','RECEIPT_IS_NOT_APPROVAL')
                need(any(str(r['id'])==e['receipt_id'] and r['envelope']==e for r in data['verified_receipts']),'CORE_VERIFIED_RECEIPT_REQUIRED')
                q=institution_query();need(any(r==value for r in q['receipts']),'INSTITUTION_RECEIPT_REQUIRED')
                need(e['query_id']==w['query']['references']['query'] and e['claim_id']==w['query']['references']['claim'],'RECEIPT_QUERY_BINDING_MISMATCH')
                refs.append('receipt:'+e['receipt_id']);return e
            if checkpoint=='caregiver_intake_confirmed':
                event('INTAKE_CREATED');event('CONSENT_GRANTED')
                intake=event('CAREGIVER_INTAKE_REPORTED')
                audio(intake['call_id'],'CAREGIVER_INTAKE','caregiver')
            elif checkpoint=='hospital_references_reported':
                discovery=data.get('reference_discovery');need(discovery,'HOSPITAL_REFERENCE_REPORT_REQUIRED')
                audio(discovery['call_id'],'HOSPITAL_REFERENCE_DISCOVERY','hospital')
                actual=self._get(f'/hospital/complex/{case}/desks/insurance','hospital')
                need(all(discovery[k]==actual['references'][v] for k,v in [('initial_reference','preauthorization'),('enhancement_reference','enhancement'),('final_reference','final_request')]),'HOSPITAL_REFERENCES_MISMATCH')
                need(discovery['admission_id']==actual['admission_id'],'HOSPITAL_ADMISSION_MISMATCH')
            elif checkpoint=='claims_query_discovered':
                need(w and w.get('source_mode')=='SANDBOX_AUDIO','AUDIO_QUERY_SOURCE_REQUIRED')
                confirmation=w.get('query_confirmation_call_id')
                if confirmation:event('QUERY_REPORT_RECONFIRMED',call_id=confirmation,original_call_id=w['query_call_id'],document_id=w['query_document_id'])
                audio(confirmation or w['query_call_id'],'QUERY_DISCOVERY','claims')
                q=institution_query();reported=w['query']
                need(reported['patient_id']==q['patient_id'] and reported['admission_id']==q['admission_id'],'QUERY_IDENTITY_MISMATCH')
                need(all(reported['references'][k]==q['references'][k] for k in ['query','claim','enhancement','final_request']),'QUERY_REFERENCE_MISMATCH')
                need(same_instant(reported['received_at'],q['received_at']) and set(reported['required_documents'])==set(q['required_documents']),'QUERY_REQUIREMENTS_OR_ORIGINAL_CLOCK_MISMATCH')
                raw_document(w['query_document_id'])
            elif checkpoint in {'bill_checked','signed_summary_checked','implant_invoice_checked'}:
                kind,owner,purpose={'bill_checked':('itemized_bill','billing','BILLING_DOCUMENT'),
                  'signed_summary_checked':('signed_discharge_summary','medical_records','RECORDS_DOCUMENT'),
                  'implant_invoice_checked':('implant_invoice','implant_store','IMPLANT_DOCUMENT')}[checkpoint]
                collected=w.get('documents',{}).get(kind);need(collected,'CHECKED_DOCUMENT_REQUIRED:'+kind)
                record=collected['record'];actual=self._get(f'/hospital/complex/{case}/desks/{owner}','hospital')['documents']
                need(any(d==record for d in actual),'DOCUMENT_DIFFERS_FROM_OWNING_DESK')
                need(record.get('ready') and record['owner']==owner and record['patient_id']==row['patient_id'] and record['admission_id']==w['query']['admission_id'],'DOCUMENT_OWNER_READINESS_OR_ADMISSION_MISMATCH')
                if kind=='signed_discharge_summary':need(record.get('signed_by'),'TREATING_TEAM_SIGNATURE_REQUIRED')
                need(raw_document(collected['document_id'])==record,'UPLOADED_RECORD_MISMATCH')
                r=report(purpose);audio(r['call_id'],purpose,'hospital')
                need(r['details'].get('ready') and r['details'].get('document_reference')==record['id'],'VOICE_DOCUMENT_REFERENCE_MISMATCH')
            elif checkpoint=='exact_packet_approved':
                need(w.get('approval_current'),'CURRENT_EXACT_PACKET_APPROVAL_REQUIRED')
                approval=w['approval'];need(approval['source'] in {'CAREGIVER_SCOPED_SESSION','SYNTHETIC_REHEARSAL_FIXTURE'},'EXPLICIT_CAREGIVER_APPROVAL_SOURCE_REQUIRED')
                event('QUERY_PACKET_APPROVED',packet_hash=w['packet_hash'])
            elif checkpoint=='hospital_dispatch_recorded':
                need(w.get('approval_current'),'CURRENT_EXACT_PACKET_APPROVAL_REQUIRED')
                r=report('PACKET_SUBMISSION');audio(r['call_id'],'PACKET_SUBMISSION','hospital')
                reference=r['details'].get('dispatch_reference');need(reference,'EXACT_DISPATCH_REFERENCE_REQUIRED')
                h=self._get(f'/hospital/complex/{case}/desks/insurance','hospital')
                from coordinator.reference_evidence import hospital_dispatch_reference
                need(any(hospital_dispatch_reference(d)==reference and d['packet_hash']==w['packet_hash'] and d['packet']==w['packet'] for d in h['dispatches']),'HOSPITAL_DISPATCH_RECORD_REQUIRED')
            elif checkpoint=='recipient_receipt_verified':receipt()
            elif checkpoint=='query_and_enhancement_verified':
                r=report('TPA_QUERY_FOLLOWUP');audio(r['call_id'],'TPA_QUERY_FOLLOWUP','claims')
                receipt();value=w.get('query_resolution');need(value,'VERIFIED_QUERY_RESOLUTION_REQUIRED')
                e=signed(value,'claims','demo-tpa-complex','QUERY_ANSWERED');q=institution_query()
                actual=q.get('query_resolution') or {}
                need(e['query_state']=='ANSWERED' and e['enhancement_linked'] is True and actual.get('envelope')==e and actual.get('signature')==value['signature'],'QUERY_AND_ENHANCEMENT_NOT_CONFIRMED')
                document=event('TPA_QUERY_AND_ENHANCEMENT_VERIFIED')['document_id'];raw_document(document)
            elif checkpoint=='insurer_decision_verified':
                r=report('INSURER_FOLLOWUP');audio(r['call_id'],'INSURER_FOLLOWUP','claims')
                value=w.get('decision');need(value,'ISSUER_DECISION_REQUIRED')
                e=signed(value,'insurer','demo-insurer-complex','INSURER_DECISION')
                actual=self._get(f'/insurer/complex/{case}/review','insurer').get('decision')
                need(actual and actual.get('envelope')==e and actual.get('signature')==value['signature'],'INSURER_RECORD_MISMATCH')
                need(e['reference']==row['reference'] and e['outcome'] in {'AUTHORIZED','DENIED'} and type(e['payable_inr']) is int,'INVALID_ISSUER_DECISION')
                need(0<=e['payable_inr']<=e['bill_inr'] and (e['outcome']!='DENIED' or e['payable_inr']==0),'INVALID_ISSUER_AMOUNTS')
                raw_document(event('INSURER_DECISION_VERIFIED')['document_id'])
            elif checkpoint in {'hospital_reconciliation_verified','caregiver_handoff_completed'}:
                r=report('DISCHARGE_FOLLOWUP');audio(r['call_id'],'DISCHARGE_FOLLOWUP','hospital')
                value=w.get('clearance');need(value,'HOSPITAL_RECONCILIATION_REQUIRED')
                e=signed(value,'hospital','demo-hospital-billing','DISCHARGE_RECONCILIATION')
                actual=self._get(f'/hospital/complex/{case}/desks/insurance','hospital').get('clearance')
                need(actual and actual.get('envelope')==e and actual.get('signature')==value['signature'],'HOSPITAL_RECONCILIATION_MISMATCH')
                patient=e['bill_inr']-e['insurer_payable_inr'];deposit=e['deposit_inr']
                need(e['patient_payable_inr']==patient and e['refund_due_inr']==max(deposit-patient,0) and e['balance_due_inr']==max(patient-deposit,0),'HOSPITAL_ARITHMETIC_MISMATCH')
                need(e['refund_payment_state']=='NOT_VERIFIED','REFUND_DUE_IS_NOT_PAYMENT_PROOF')
                raw_document(event('DISCHARGE_RECONCILIATION_VERIFIED')['document_id'])
                if checkpoint=='caregiver_handoff_completed':
                    need(row['state']=='DISCHARGE_CLEARED' and e['discharge_clearance']=='ISSUED','ADMINISTRATIVE_CLEARANCE_REQUIRED')
                    r=report('CAREGIVER_COMPLEX_UPDATE');audio(r['call_id'],'CAREGIVER_COMPLEX_UPDATE','caregiver')
                    summary=w['caregiver_summary'];need(summary['statements'] and summary['refund_payment_verified'] is False and summary['insurance_decision_made_by_agent'] is False,'SOURCE_BACKED_HANDOFF_REQUIRED')
                    # Recheck earlier gates at handoff. A previously passed bill
                    # checkpoint cannot hide a later institution version change.
                    for prior in scenario_manifest()['checkpoints'][:-1]:
                        need(self.inspect(prior,incident_id)['passed'],'PRIOR_GATE_NO_LONGER_VALID:'+prior)
            return {'checkpoint':checkpoint,'passed':True,'evidence_references':list(dict.fromkeys(refs)),'reason':'AUTHORITATIVE_RECORDS_MATCH'}
        except MissingEvidence as exc:return {'checkpoint':checkpoint,'passed':False,'evidence_references':[],'reason':str(exc)}
        except Exception:return {'checkpoint':checkpoint,'passed':False,'evidence_references':[],'reason':'EVIDENCE_UNAVAILABLE_OR_INVALID'}

    def audit(self,incident_id):
        checks=[self.inspect(name,incident_id) for name in scenario_manifest()['checkpoints']]
        return {'incident_id':str(incident_id),'passed':all(c['passed'] for c in checks),'checks':checks,
                'method':'INDEPENDENT_RECORD_AUDIO_HASH_AND_SIGNATURE_CHECKS',
                'required_audio_provenance':self.required_audio_provenance,
                'fixture_audio_allowed':self.required_audio_provenance is None,
                'conversation_quality_evaluated':False,'replaces_pipecat_evals':False}
