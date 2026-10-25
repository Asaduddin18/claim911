"""Exact-character readback evidence. Formatting is normalized, codes are not guessed."""
import json,re
from sandbox.spoken_identifiers import normalize_identifier_speech

CODE=re.compile(r'\b(?:[a-z][a-z0-9]*(?:[-/][a-z0-9]+)+|[a-z]+[0-9]+)\b',re.I)


def reference_question(question):
    q=question.casefold()
    return bool(re.search(r'confirm|correct|accurate|read.?back',q)
        and re.search(r'reference|admission|identifier|spelling|code|(?:initial|enhancement|final) request',q))


def field_evidence(question,record):
    q=question.casefold();references=record.get('references',{})
    fields=[(r'initial (?:request|approval|reference)|preauthori[sz]ation',references.get('preauthorization')),
            (r'enhancement (?:request|reference)',references.get('enhancement')),
            (r'final (?:request|reference|authori[sz]ation)',references.get('final_request')),
            (r'admission (?:id|identifier)',record.get('admission_id')),
            (r'claim reference',references.get('claim')),
            (r'query reference',references.get('query'))]
    found=[(m.start(),value) for pattern,value in fields if value for m in re.finditer(pattern,q)]
    if not found and re.search(r'(?:document|summary|invoice|bill).*(?:identifier|reference)|(?:identifier|reference).*(?:document|summary|invoice|bill)',q):
        documents=record.get('documents',[])
        if len(documents)==1 and isinstance(documents[0].get('id'),str):
            return {documents[0]['id']},question
    if not found:return set(),question
    start,value=max(found,key=lambda item:item[0])
    # A confirmation can repeat its field after the code: "Initial reference
    # PRE37. Is that the correct initial reference?" Retain that same-field
    # candidate, without importing an earlier reference of another type.
    previous_other=max((position for position,other in found if other!=value),default=-1)
    start=min(position for position,other in found if other==value and position>previous_other)
    return {str(value)},question[start:]


def expected_reference_codes(question,record):return field_evidence(question,record)[0]


def codes(text):
    return {c.casefold() for c in CODE.findall(normalize_identifier_speech(text)) if any(ch.isdigit() for ch in c)}


def readback_evidence(question,record):
    from sandbox.scripted_desks import latest_question
    question=latest_question([{'role':'user','content':question}])
    if not reference_question(question):return {'state':'NOT_APPLICABLE'}
    expected,fragment=field_evidence(question,record)
    text=normalize_identifier_speech(fragment)
    # ASR may glue a field label to the following code. Separate only known
    # labels, never add, remove or replace a character inside an identifier.
    text=re.sub(r'\b(admission\s+id|reference)(?=[a-z])',r'\1 ',text)
    known={c for c in CODE.findall(json.dumps(record)) if any(ch.isdigit() for ch in c)}|expected
    heard=set();spans=[]
    for canonical in known:
        pattern=r'(?<![a-z0-9])'+r'[\s,.]*'.join(re.escape(c) for c in canonical.casefold())+r'(?![a-z0-9])'
        for match in re.finditer(pattern,text):heard.add(canonical.casefold());spans.append(match.span())
    remaining=list(text)
    for start,end in spans:remaining[start:end]=' '*(end-start)
    heard|=codes(''.join(remaining))
    allowed={v.casefold() for v in expected} or {v.casefold() for v in known}
    state='EXACT_MATCH' if heard and heard<=allowed else 'MISMATCH_OR_UNCLEAR'
    return {'state':state,'requested_reference_values':sorted(expected),'heard_reference_values':sorted(heard),
            'normalization':'EXACT_CHARACTERS_WITH_SPOKEN_DIGITS_SPACING_AND_PUNCTUATION_ONLY'}


def unsupported_affirmation(text,question,record):
    evidence=readback_evidence(question,record)
    if evidence['state']=='NOT_APPLICABLE':return False
    expected={v.casefold() for v in evidence['requested_reference_values']}
    supplied=codes(text)
    if expected and supplied and not supplied<=expected:return True
    answer=text.strip().casefold()
    affirmative=re.search(r'exact reference matches|^yes\b|^correct\b|^that(?: is|\x27s) (?:correct|right)\b',answer)
    denial=re.search(r'not.*(?:match|exact|correct)|mismatch|unclear|doesn.t.*match',answer)
    if evidence['state']=='EXACT_MATCH':return bool(denial)
    return bool(affirmative)


def reference_confirmation_reply(question,record):
    """Render exact role-owned reference comparisons, never outcome answers."""
    from sandbox.scripted_desks import latest_question
    latest=latest_question([{'role':'user','content':question}])
    if not reference_question(latest):return None
    if re.search(r'\b(answered|linked|received|submitted|approved|authorized|signed|ready|paid|status|decision|clearance|refund)\b',latest,re.I):
        return None
    evidence=readback_evidence(latest,record)
    values=evidence.get('requested_reference_values',[])
    if len(values)!=1:return None
    # Asking for a field without reading a value is a request for information,
    # not a wrong readback. Let the natural participant provide the field.
    if not evidence.get('heard_reference_values'):return None
    if evidence['state']=='EXACT_MATCH':return 'Yes, that exact reference matches our record.'
    return 'No, the reference in our record is '+values[0]+'.'
