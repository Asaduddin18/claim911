"""Server-owned purpose instructions contain no hidden institution records."""
from coordinator.voice_contracts import append_common_closing

def call_objective(purpose, reference):
    tasks={
        'HOSPITAL_INITIAL':f'Confirm whether final authorization {reference} was submitted. Ask its exact reference and reported submission time. Keep initial preauthorization separate. If hospital staff cannot confirm final submission after checking records, record SUBMISSION_UNKNOWN for that exact final reference, explain it remains unconfirmed and needs human review, then close. Do not repeat the question or ask hospital staff claims-queue questions. Initial approval alone does not prove a submission. Record SUBMITTED only for the request actually confirmed.',
        'CLAIMS_LOOKUP':f'Ask claims staff whether the designated claims queue received final request {reference}. If absent and queue confirmed, immediately record NOT_RECEIVED. Never ask claims staff to confirm hospital submission or record SUBMITTED.',
        'HOSPITAL_FOLLOWUP':f'This is a dispatch-destination follow-up for final request {reference}. Hospital submission and claims non-receipt are already reported. Do not repeat submission confirmation, reference or initial approval questions. Ask only: What exact destination did you send the final request to? Read the destination back and record DESTINATION immediately after confirmation. Check uploaded dispatch proof in context. Then call claim911_propose_correction; explain any returned proposal requires separate caregiver approval. Do not claim approval or perform correction.',
        'CORRECTION_REQUEST':f'Ask the hospital to perform only the exact authorized correction for final request {reference}. Use the authorized action in context. Hospital staff must submit through their own portal. Reported completion is not a verified receipt.',
        'CAREGIVER_UPDATE':'Explain current verified case state and the remaining next step. A recipient receipt does not mean insurance approval.'
    }
    return append_common_closing(tasks[purpose])
