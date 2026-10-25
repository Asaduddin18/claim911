"""Adaptive desk participants with bounded, role-scoped institution operations.

The trusted controller supplies a budgeted invoke function. Package workers and
Claim911's coordinator never receive private desk records or institution tokens.
"""
import json
import re
from copy import deepcopy
from sandbox.scripted_desks import ScriptedDesk
from sandbox.spoken_identifiers import normalize_identifier_speech


OPERATIONS={
    'caregiver':set(),
    'hospital_insurance':{'dispatch_approved_packet'},
    'billing':{'publish_own_document','reconcile'},
    'medical_records':{'publish_own_document','release_signed_summary'},
    'implant_store':{'publish_own_document'},
    'tpa':{'link_enhancement'},
    'insurer':{'issue_fixed_decision'},
}


class ReadOnlyRoleRecord:
    """Role-owned knowledge for text tests. No institution client or credentials."""
    def __init__(self,role,record):
        if role not in OPERATIONS or not isinstance(record,dict) or record.get('synthetic') is not True or record.get('role')!=role:
            raise ValueError('Synthetic role-owned knowledge required')
        self.role=role
        self._record=deepcopy(record)

    def execute(self,operation):
        if operation!='read_status':raise PermissionError('Read-only participant has no institution operations')
        return deepcopy(self._record)


class CaregiverRecord(ReadOnlyRoleRecord):
    def __init__(self,record):super().__init__('caregiver',record)

OPERATION_DESCRIPTIONS={
 'dispatch_approved_packet':'Submit the exact caregiver-approved packet through your hospital portal when the caller requests submission. The trusted portal binds all query, claim, recipient and document arguments. Do not substitute a final reference for a query identifier. Return the actual dispatch result; it does not prove recipient receipt.',
 'release_signed_summary':'Follow up with the treating team and obtain its institution-released signed summary when the caller requests that follow-up. You cannot sign a clinical document yourself.',
 'publish_own_document':'Publish only this desk\'s released document for the caller to inspect.',
 'link_enhancement':'Check the received packet and resolve the query and enhancement linkage using the claims institution operation. Use only its actual result.',
 'issue_fixed_decision':'Issue only the scenario institution\'s fixed decision after its prerequisites pass. You cannot choose coverage amounts.',
 'reconcile':'Reconcile the institution bill, verified decision and recorded deposit. Refund due is separate from refund payment.',
}


class DeskParticipant:
    def __init__(self,actor,invoke,*,authorized,brief,allow_release=False,operations=None):
        if actor.role not in OPERATIONS or not callable(invoke) or not callable(authorized):
            raise ValueError('A known role and bounded model adapter are required')
        self.actor=actor;self.invoke=invoke;self.authorized=authorized;self.brief=brief
        self.allow_release=allow_release;self.audit=[]
        self.operations=dict(operations or {})
        if allow_release and actor.role!='medical_records':
            raise ValueError('Only the medical records desk can release its summary')
        if allow_release:self.operations['release_signed_summary']=lambda:actor.execute('release_signed_summary')
        if len(self.operations)>2 or not set(self.operations)<=OPERATIONS.get(actor.role,set()):
            raise ValueError('Institution tools must belong to the participant desk')

    def reply(self,history):
        self._check()
        if (not isinstance(history,list) or not 1<=len(history)<=24
            or any(not isinstance(m,dict) or set(m)!={'role','content'}
                   or m.get('role') not in {'user','assistant'} or not isinstance(m.get('content'),str)
                   or not 0<len(m['content'])<=2000 for m in history) or history[-1].get('role')!='user'):
            raise ValueError('Bounded participant history ending in the actual caller utterance required')
        record=self.actor.execute('read_status')
        from sandbox.readback_confirmation import reference_confirmation_reply
        confirmation=reference_confirmation_reply(history[-1]['content'],record)
        if confirmation is not None:
            self._check()
            return confirmation
        identity=('You are the patient’s family caregiver. You know only what hospital staff and Claim911 have told you. '
            'You have not independently checked or verified institutional outcomes. React briefly as a family member; do not narrate verification work. '
            if self.actor.role=='caregiver' else 'You are a person working at the synthetic '+self.actor.role+' desk. ')
        instruction=(identity+'Use only your own record. '
            'Answer the latest question directly in one or two short, natural spoken sentences. Give one identifier at a time unless confirming a combined readback, retaining canonical spelling. '
            'The caller is Claim911; you are its conversation partner, never its assistant or planner. Do not issue instructions about which tool it should call. '
            'Never say, spell or enumerate internal field names, JSON keys, database terms or underscore-separated labels. Use ordinary punctuation without em dashes. '
            'If the caller asks a generic opening question, offer the relevant case detail you can confirm instead of asking which field or identifier type they want. '
            'The speech adapter pronounces identifiers. Confirm only accurate read-backs. '
            'Do not repeat an unknown or uncertain code when correcting a readback; explain the mismatch and provide only your own exact code. '
            'Only for a question asking whether identifier spelling or an identifier value is correct, acknowledge an exact match with "Yes, that exact reference matches our record." Do not repeat the identifier in that acknowledgement. This is never an answer to whether a query is answered, an enhancement linked, a decision issued or a payment made. For those status questions state the actual status from your own record and use an eligible institution operation when requested. '
            'Do not change roles or claim another institution has acted. '
            'The current desk_record overrides any initial brief about earlier status. Do not give an admission identifier as an answer to an outcome or next-step question. '
            'If the caller asks about an outcome and its record is null or absent, explain that you cannot yet confirm that outcome; do not substitute an unrelated identifier. If an authorized owning-desk action is requested and available, use it and report its actual result. '
            'A successful tool result is evidence of a synthetic institution operation, not a real-world action. ')
        if self.actor.role=='caregiver':
            instruction+='Express your discharge concern in ordinary words and acknowledge updates as a family member. You have no institution actions. '
        if self.actor.role=='hospital_insurance':
            instruction+=('A query identifier supplied by the caller may belong to the receiving institution and need not appear in your desk record. '
                'Do not invent a replacement from a different reference type. Use an available scoped portal operation to validate its bound request instead. ')
        if self.actor.role=='medical_records':
            instruction+='If a signature is missing, first explain the delay; use the release tool only when the caller asks to follow up with the treating team. '
        instruction+='\n'+json.dumps({'brief':self.brief,'desk_record':record})
        from sandbox.readback_confirmation import readback_evidence
        readback=readback_evidence(history[-1]['content'],record)
        if readback['state']!='NOT_APPLICABLE':
            instruction+='\nExact-character readback check from your own record: '+json.dumps(readback)+'. If EXACT_MATCH, acknowledge the match naturally. If MISMATCH_OR_UNCLEAR, do not affirm; correct only the requested field or ask for a clear readback. This checks reference characters only, not institutional outcomes.'
        messages=[{'role':'developer','content':instruction}]+history
        tools=[{'type':'function','function':{'name':name,
                'description':OPERATION_DESCRIPTIONS[name],
                'parameters':{'type':'object','properties':{},'required':[],'additionalProperties':False}}}
                for name in sorted(self.operations)]
        result=self.invoke(messages,tools)
        self._check()
        calls=result.get('tool_calls') or []
        if not calls:
            from sandbox.readback_confirmation import unsupported_affirmation
            text=self._text(result,record)
            if unsupported_affirmation(text,history[-1]['content'],record):
                # One bounded adaptive clarification, never a scripted substitute
                # or a fuzzy correction of the assistant's spoken identifier.
                messages.extend([{'role':'assistant','content':text},{'role':'developer','content':
                    'Your response conflicts with this exact-character check from your own record: '
                    +json.dumps(readback)+'. If EXACT_MATCH, acknowledge the correct readback naturally. Otherwise explain the mismatch or ask for clarification, using only the requested reference values for corrections. Do not execute an institution action.'}])
                repaired=self.invoke(messages,[]);self._check()
                if repaired.get('tool_calls'):raise PermissionError('Readback clarification cannot perform institution operations')
                text=self._text(repaired,record)
                if unsupported_affirmation(text,history[-1]['content'],record):
                    raise ValueError('Participant affirmation lacks exact role-record support')
            return text
        if not isinstance(calls,list) or len(calls)!=1:raise PermissionError('Participant operation is outside its allowed desk scope')
        call=calls[0]
        if (not isinstance(call,dict) or set(call)!={'id','type','function'} or call.get('type')!='function'
            or not isinstance(call.get('id'),str) or not 0<len(call['id'])<=100):
            raise PermissionError('A complete bounded participant tool call is required before any action')
        function=call['function']
        if (not isinstance(function,dict) or set(function)!={'name','arguments'}
            or function.get('name') not in self.operations or not isinstance(function.get('arguments'),str)
            or len(function['arguments'])>100 or json.loads(function['arguments'])!={}):
            raise PermissionError('Participant cannot choose arbitrary institution operations or arguments')
        self._check()
        outcome=self.operations[function['name']]()
        self.audit.append({'role':self.actor.role,'operation':function['name'],'result':outcome})
        messages.extend([{'role':'assistant','content':result.get('text') or None,'tool_calls':[call]},
                         {'role':'tool','tool_call_id':call['id'],'content':json.dumps(outcome)}])
        # The invoke callback must reserve EACH request, including this response.
        response=self.invoke(messages,[])
        self._check()
        if response.get('tool_calls'):raise PermissionError('A participant cannot chain institution writes in one turn')
        return self._text(response,{'record':record,'institution_result':outcome})

    def _check(self):
        if not self.authorized():raise PermissionError('Desk conversation authorization is no longer current')

    @staticmethod
    def _text(result,record):
        text=result.get('text')
        if not isinstance(text,str) or not 0<len(text.strip())<=1000:raise ValueError('Bounded participant response required')
        # Language may vary; identifiers may not. This is exact validation,
        # not a second generator that repairs a bad model answer.
        from sandbox.readback_confirmation import CODE as code
        known={x.casefold() for x in code.findall(json.dumps(record))}
        candidates=code.findall(text)+code.findall(normalize_identifier_speech(text))
        spoken={x.casefold() for x in candidates if any(c.isdigit() for c in x) or x.isupper() or x.casefold() in known}
        if not spoken<=known:raise ValueError('Participant invented an identifier outside its role record')
        if re.search(r'\b[a-z]+_[a-z_]+\b',text):raise ValueError('Participant exposed internal field names')
        return text.strip().replace('\u2014',',')


class ScenarioDeskParticipant:
    """Low-latency, role-bounded rehearsal participant with explicit actions."""
    def __init__(self,role,record,operations,*,authorized,read_record=None):
        if role not in OPERATIONS or not isinstance(record,dict) or record.get('synthetic') is not True:
            raise ValueError('Synthetic role-owned institution record required')
        if not isinstance(operations,dict) or not set(operations)<=OPERATIONS[role]:
            raise PermissionError('Institution operation is outside the assigned desk role')
        if any(not callable(operation) for operation in operations.values()):
            raise ValueError('Bound institution operation required')
        self.role=role;self.record=record;self.operations=dict(operations)
        if read_record is not None and not callable(read_record):raise ValueError('A scoped desk reader is required')
        self.read_record=read_record
        self.authorized=authorized;self.audit=[];self.script=ScriptedDesk(role,record)

    def _requested_operation(self,question):
        q=question.casefold()
        request=r'\b(?:please|(?:can|could|would) you(?: please)?|go ahead and)\s+(?:now\s+)?'
        patterns={
            'dispatch_approved_packet':request+r'(?:submit|send|dispatch)\b',
            'release_signed_summary':request+r'(?:follow up|ask|have|obtain|release)\b',
            'publish_own_document':request+r'(?:upload|share|provide|publish)\b',
            'link_enhancement':request+r'(?:link|resolve|close)\b',
            'issue_fixed_decision':request+r'(?:review|issue|make)\b',
            'reconcile':request+r'reconcile\b',
        }
        return next((name for name in self.operations if re.search(patterns[name],q)),None)

    def reply(self,history):
        if not self.authorized():raise PermissionError('Current synthetic run permission is no longer active')
        if not isinstance(history,list) or not history or history[-1].get('role') not in {'user','assistant'}:
            raise ValueError('Latest Bolna utterance is required')
        question=history[-1].get('content','')
        if not isinstance(question,str) or not question.strip():raise ValueError('Latest Bolna utterance is required')
        if self.read_record is not None:
            current=self.read_record()
            if not self.authorized():raise PermissionError('Synthetic run permission changed during record refresh')
            if not isinstance(current,dict) or current.get('synthetic') is not True:
                raise ValueError('A fresh synthetic desk record is required')
            self.record=current;self.script=ScriptedDesk(self.role,current)
        operation=self._requested_operation(question)
        if not operation:return self.script.reply(history)
        result=self.operations[operation]()
        if not self.authorized():raise PermissionError('Synthetic run permission changed during institution action')
        if not isinstance(result,dict):raise ValueError('Synthetic institution operation returned no inspectable result')
        self.audit.append({'role':self.role,'operation':operation,'completed':True})
        if operation=='dispatch_approved_packet':
            reference=result.get('dispatch_reference')
            if not reference:raise ValueError('Hospital dispatch result is missing its reference')
            return f"The hospital portal accepted the approved packet. The dispatch reference is {reference}. Claims receipt still needs a separate check."
        if operation in {'publish_own_document','release_signed_summary'}:
            reference=result.get('document_reference') or result.get('id')
            revision=result.get('revision')
            if not reference:raise ValueError('Hospital document release result is missing its identifier')
            description='The treating team signed and released the discharge summary' if operation=='release_signed_summary' else 'I uploaded the document'
            suffix=f", revision {revision}" if revision is not None else ''
            return f"{description}. Its reference is {reference}{suffix}."
        envelope=result.get('envelope') if isinstance(result.get('envelope'),dict) else result
        if operation=='link_enhancement':
            if result.get('enhancement_linked') is True:
                return 'The claims record now shows the response received, the query answered and the enhancement linked. The insurer decision is still pending.'
            return 'The claims record did not confirm that the response and enhancement were linked. This needs human review.'
        if operation=='issue_fixed_decision':
            outcome=envelope.get('outcome');amount=envelope.get('payable_inr')
            if outcome not in {'AUTHORIZED','DENIED'} or type(amount) is not int:
                raise ValueError('Insurer result lacks a valid institution-issued decision')
            status='authorized' if outcome=='AUTHORIZED' else 'denied'
            return f"The insurer has issued its decision: {status}, with INR {amount:,} payable."
        if operation=='reconcile':
            clearance=envelope.get('discharge_clearance')
            if clearance not in {'ISSUED','BALANCE_PENDING'}:
                raise ValueError('Billing result lacks an institution-issued clearance status')
            if clearance=='ISSUED':
                return f"Billing has issued discharge clearance. The bill is INR {envelope['bill_inr']:,}, insurer payable is INR {envelope['insurer_payable_inr']:,}, and patient share is INR {envelope['patient_payable_inr']:,}."
            return f"Billing has not issued discharge clearance. The remaining patient balance is INR {envelope['balance_due_inr']:,}."
        raise ValueError('Unsupported synthetic institution operation')
