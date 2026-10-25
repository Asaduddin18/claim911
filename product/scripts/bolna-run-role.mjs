const checkpointRoles=Object.freeze({
 caregiver_intake_confirmed:'caregiver',
 hospital_references_reported:'hospital_insurance',
 claims_query_discovered:'tpa',
 bill_checked:'billing',
 signed_summary_checked:'medical_records',
 implant_invoice_checked:'implant_store',
 hospital_dispatch_recorded:'hospital_insurance',
 query_and_enhancement_verified:'tpa',
 insurer_decision_verified:'insurer',
 hospital_reconciliation_verified:'billing',
 caregiver_handoff_completed:'caregiver',
});

export function participantForRun(run){
 if(!run||!['READY','RUNNING'].includes(run.state))throw new Error('The selected sandbox run is not ready for a Bolna conversation.');
 if(run.state==='READY'&&run.checkpoint!==0)throw new Error('A ready run can start Bolna only at its first checkpoint.');
 if(!Number.isInteger(run.checkpoint)||run.checkpoint<0)throw new Error('The selected run has no valid checkpoint.');
 const role=checkpointRoles[run.checkpoints?.[run.checkpoint]?.key];
 if(!role)throw new Error('The selected checkpoint is an approval or evidence step, not a voice conversation.');
 return role;
}

export function checkpointParticipantRoles(){return {...checkpointRoles};}
