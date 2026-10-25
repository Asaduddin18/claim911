"""Purpose-limited model function calling over existing authenticated report tools."""
import json
from coordinator.app import ReferenceDiscovery
from coordinator.complex import QueryReport,DocumentReport,UpdateReport
from coordinator.voice_guidance import context_guidance

REPORTS={
 'claim911_report_references':(ReferenceDiscovery,'/v1/tools/references',None),
 'claim911_report_query':(QueryReport,'/v1/tools/workflow','REPORT_QUERY'),
 'claim911_report_document':(DocumentReport,'/v1/tools/workflow','REPORT_DOCUMENT'),
 'claim911_report_update':(UpdateReport,'/v1/tools/workflow','REPORT_UPDATE'),
}


class ScopedToolModel:
    """Trusted adapter owns the call token. The model never receives it.

    invoke(messages, tools) performs exactly one already-budgeted provider request.
    An accepted report speaks the backend's confirmed result directly, avoiding
    an unbudgeted extra model call or a claim that a failed write was saved.
    """
    def __init__(self,core,call_token,invoke,*,authorized=None,language='en'):
        if language not in {'en','hi'}:raise ValueError('Supported conversation language required')
        self.core=core;self._token=call_token;self.invoke=invoke;self.audit=[];self.authorized=authorized;self.language=language

    def reply(self,messages):
        if self.authorized is not None and not self.authorized():raise PermissionError('Conversation execution lease is no longer current')
        response=self.core.get('/v1/tools/context',headers={'X-Call-Token':self._token})
        response.raise_for_status();context=response.json();purpose=context['purpose']
        allowed={'claim911_report_update'}
        if purpose=='HOSPITAL_REFERENCE_DISCOVERY':allowed.add('claim911_report_references')
        elif purpose=='QUERY_DISCOVERY':allowed.add('claim911_report_query')
        elif purpose in {'BILLING_DOCUMENT','RECORDS_DOCUMENT','IMPLANT_DOCUMENT'}:allowed.add('claim911_report_document')
        tools=[{'type':'function','function':{'name':name,'description':'Record only facts explicitly confirmed by this participant. A saved report is not independently verified institution evidence.',
                'parameters':REPORTS[name][0].model_json_schema()}} for name in sorted(allowed)]
        instruction=('You are Claim911 coordinating a synthetic case. Follow the current purpose. '
          'Ask one short question at a time. Use a report function immediately after confirmed facts, '
          'Request only one identifier per question. Never ask for initial, enhancement and final references together. '
          'If uploaded_reference_candidates exist, read one candidate back for staff confirmation instead of asking staff to spell it again. The upload alone is not confirmation. '
          'before claiming they were recorded. Never infer a final request from initial approval. '
          'Use identifiers exactly as confirmed. If a required field is unknown, ask rather than invent it. '
          'For spelled identifiers, a spoken hyphen means the literal separator -, and separately spoken digits retain their order. '
          'Whitespace between separately recognized letters is not an extra hyphen: join those letters while preserving explicitly spoken separators. '
          'Read the normalized candidate back once. After participant confirmation, move to the next missing field. '
          'After two unsuccessful clarifications of the same identifier, report an unresolved update instead of repeating the question. '
          'Preserve those separators when reading back the canonical identifier; do not append a document version. '
          'A spoken report cannot authorize sharing, issue coverage, verify receipt or mark a refund paid. '
          'Current authoritative call context follows:\n'+json.dumps(context,default=str))
        instruction+='\n'+context_guidance(context)
        if purpose in {'TPA_QUERY_FOLLOWUP','INSURER_FOLLOWUP','DISCHARGE_FOLLOWUP'}:
            instruction+='\nIdentifier confirmation is not an outcome confirmation. Ask about each required status. If the institution has not processed an eligible step, ask its staff to review and perform its own authorized operation and upload the institution-issued proof. A generic yes about a reference does not establish query closure, enhancement linkage, an insurer decision or hospital clearance. Record confirmed status and request missing evidence; do not close merely because a pending report was saved.'
        instruction+='\nUse plain spoken sentences without em dashes.'
        if self.language=='hi':instruction+='\nदेखभाल करने वाले से सरल हिंदी में बात करें। सत्यापित रकम और संदर्भ न बदलें। रिफंड देय होना और भुगतान होना अलग बातें हैं।'
        if self.audit:
            outcome=self.audit[-1]['result']
            public={k:outcome[k] for k in ['reported_document_result','reported_dispatch_result','uploaded_reference_candidates','reported_document_reference','instruction','next_step','spoken_outcome','verified_state_changed'] if k in outcome}
            instruction+='\nLast scoped tool outcome (not a new participant statement): '+json.dumps(public,default=str)
        # One developer instruction combines the bounded session role and fresh
        # backend context; caller history cannot replace the instruction role.
        session_instructions='\n'.join(m['content'] for m in messages if m['role']=='developer')
        records_followup=purpose=='RECORDS_DOCUMENT' and 'scheduled records follow-up' in session_instructions.lower()
        if records_followup:
            instruction+='\nThis is the scheduled medical-records callback. Your first response must ask staff to follow up with the treating team and upload its released signed summary if available. Do not start by repeating only the readiness question.'
        model_messages=[{'role':'developer','content':session_instructions+'\n'+instruction}]+[m for m in messages if m['role']!='developer']
        result=self.invoke(model_messages,tools)
        calls=result.get('tool_calls') or []
        if not calls:
            if not result.get('text'):raise ValueError('Model response is empty')
            return result
        if len(calls)!=1:raise PermissionError('Only one purpose-scoped report operation may execute per turn')
        function=calls[0]['function'];name=function['name']
        if name not in allowed:raise PermissionError('Model requested an operation outside this conversation purpose')
        model,path,operation=REPORTS[name]
        parsed=model.model_validate(json.loads(function['arguments']))
        payload=parsed.model_dump(mode='json')
        if purpose=='PACKET_SUBMISSION' and name=='claim911_report_update' and payload.get('dispatch_reference') and context.get('uploaded_dispatch_candidates'):
            references={c['dispatch_reference'] for c in context['uploaded_dispatch_candidates']}
            if payload['dispatch_reference'] not in references:
                outcome={'recorded':False,'reported_dispatch_result':'REFERENCE_CONFIRMATION_REQUIRED',
                         'instruction':'The proposed reference does not exactly match uploaded dispatch proof. Read the uploaded candidate back for confirmation. Do not save an ASR rendering or silently replace an unconfirmed identifier.',
                         'verified_state_changed':False}
                self.audit.append({'call_id':context['call_id'],'tool':name,'arguments':payload,'result':outcome})
                return {'text':'That reference does not match the uploaded dispatch proof. Please confirm the exact reference shown on the proof.',
                        'report_tool':name,'report_recorded':False}
        body=payload if operation is None else {'operation':operation,'details':payload}
        if self.authorized is not None and not self.authorized():raise PermissionError('Conversation authorization changed before the report write')
        written=self.core.post(path,headers={'X-Call-Token':self._token},json=body)
        written.raise_for_status();outcome=written.json()
        self.audit.append({'call_id':context['call_id'],'tool':name,'arguments':payload,'result':outcome})
        spoken=outcome.get('spoken_outcome') or 'The confirmed report is recorded. Institution evidence and verification remain separate.'
        if records_followup and name in {'claim911_report_update','claim911_report_document'} and outcome.get('reported_document_result')!='UPLOADED_DOCUMENT_CHECKED':
            spoken+=' Please follow up with the treating team now and upload its released signed summary if available, or explain the remaining blocker.'
        workflow=context.get('workflow') or {}
        if name=='claim911_report_update' and not payload.get('callback_at'):
            if purpose=='INSURER_FOLLOWUP' and not workflow.get('decision'):
                spoken+=' Please review the complete packet and issue your institution decision if eligible, or explain the remaining blocker.'
            elif purpose=='TPA_QUERY_FOLLOWUP' and not workflow.get('query_completion_verified'):
                spoken+=' Please review the received packet, resolve the query and link the enhancement if eligible, then upload your institution confirmation.'
            elif purpose=='DISCHARGE_FOLLOWUP' and not workflow.get('clearance'):
                spoken+=' Please reconcile your bill, the insurer decision and deposit, then upload your hospital reconciliation. Keep refund due separate from payment.'
        if self.language=='hi' and purpose in {'CAREGIVER_INTAKE','CAREGIVER_COMPLEX_UPDATE'}:
            spoken='आपकी बात दर्ज हो गई है। अस्पताल और बीमा संस्था के सत्यापित रिकॉर्ड अलग से जाँचे जाते हैं।'
        return {'text':spoken,'usage':result.get('usage',{}),'model':result.get('model'),
                'report_tool':name,'report_recorded':True}
