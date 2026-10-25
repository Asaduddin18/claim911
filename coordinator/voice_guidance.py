"""Shared evidence-confirmation guidance for every voice assistant adapter.

These instructions never verify an upload or grant an institution operation.
"""

def context_guidance(context):
    if not context:return ''
    paragraphs=[
        'Use only candidates actually present in this current context. An absent or empty candidate list means no candidate is available. Never create an example reference, guess a value, or reuse a reference from a different field. '
        'The greeting has already asked the first question. Process its answer before asking another question. '
        'Keep a short checklist of answered fields in this conversation; refreshing context does not erase answers. '
        'After all required facts are confirmed, call the required report tool immediately. If its call_complete is true, say spoken_outcome and close; if false, carry out only its remaining instruction.'
    ]
    followup=(context.get('workflow') or {}).get('active_followup') or {}
    if context.get('purpose')=='RECORDS_DOCUMENT' and followup.get('purpose')=='RECORDS_DOCUMENT':
        paragraphs.append('This is the scheduled medical-records callback. Ask staff to follow up with the treating team and upload its institution-released signed summary if available. Do not repeat only the earlier readiness question. You cannot sign the document, assume it is available or bypass its verification. After staff confirm release, obtain the document reference and use the required document report tool.')
    if context.get('uploaded_reference_candidates'):
        paragraphs.append('The current hospital has uploaded a reference slip. Read back ONE canonical candidate at a time and ask staff whether it is correct. Do not ask staff to spell an identifier already displayed in the slip. An upload alone is not confirmation. If recognition is ambiguous, offer that uploaded candidate for explicit confirmation instead of silently substituting it. Move to the next field after confirmation. Do not recap all identifiers together.')
    if context.get('uploaded_query_candidates'):
        paragraphs.append('A claims query slip is uploaded. Ask whether the query is outstanding. Then read back ONE uploaded candidate at a time: query reference, claim reference, admission ID and enhancement reference. Obtain an explicit confirmation for EACH before moving on. Do not ask staff to dictate a reference already in the slip. Use the provided spoken_readbacks, with canonical values only in tool arguments. Confirm the original receipt timestamp with timezone and the document requirements separately. Do not repeat or combine already confirmed identifiers. Report only after staff confirm the current query details; do not repeat data entry for fields already confirmed.')
    if context.get('uploaded_dispatch_candidates'):
        paragraphs.append('Existing hospital dispatch proof is uploaded. Read its exact dispatch_reference back for staff confirmation. Do not request another submission. Report that canonical value only after confirmation. If not confirmed, report an unresolved update without dispatch_reference. Hospital confirmation is separate from receiving-side receipt verification.')
    if context.get('uploaded_document_candidates'):
        paragraphs.append('The assigned document is uploaded. Read its exact document_reference back to the owning desk for confirmation, keeping revision separate. Then report_document. Only UPLOADED_DOCUMENT_CHECKED establishes that the uploaded document passed its backend check.')
    if paragraphs:
        paragraphs.append('For a reference readback, speak the provided spoken_readbacks entry using its spoken form, not the canonical code as a word. If staff cannot understand it, use that entry’s phonetic form once. Keep the canonical value unchanged in tool arguments. Spoken formatting does not verify a candidate.')
    return '\n'.join(paragraphs)
