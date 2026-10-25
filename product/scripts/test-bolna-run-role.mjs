import test from 'node:test';
import assert from 'node:assert/strict';
import {participantForRun,checkpointParticipantRoles} from './bolna-run-role.mjs';

const keys=['caregiver_intake_confirmed','hospital_references_reported','claims_query_discovered','bill_checked',
 'signed_summary_checked','implant_invoice_checked','exact_packet_approved','hospital_dispatch_recorded',
 'recipient_receipt_verified','query_and_enhancement_verified','insurer_decision_verified',
 'hospital_reconciliation_verified','caregiver_handoff_completed'];

test('every voice checkpoint maps to its owning synthetic participant',()=>{
 const expected=['caregiver','hospital_insurance','tpa','billing','medical_records','implant_store',null,
  'hospital_insurance',null,'tpa','insurer','billing','caregiver'];
 const roles=checkpointParticipantRoles();
 assert.equal(Object.keys(roles).length,11);
 for(let checkpoint=0;checkpoint<keys.length;checkpoint++){
  const run={state:'RUNNING',checkpoint,checkpoints:keys.map(key=>({key}))};
  if(expected[checkpoint])assert.equal(participantForRun(run),expected[checkpoint]);
  else assert.throws(()=>participantForRun(run),/approval or evidence/);
 }
});

test('a fresh ready run starts at its first manifest checkpoint',()=>{
 const checkpoints=keys.map(key=>({key}));
 assert.equal(participantForRun({state:'READY',checkpoint:0,checkpoints}),'caregiver');
 assert.throws(()=>participantForRun({state:'READY',checkpoint:1,checkpoints}),/first checkpoint/);
});

test('terminal, malformed and expired workflow selections fail closed',()=>{
 for(const state of ['PREPARED','PAUSED','UNCERTAIN','COMPLETED','CANCELLED'])
  assert.throws(()=>participantForRun({state,checkpoint:0,checkpoints:keys.map(key=>({key}))}));
 assert.throws(()=>participantForRun({state:'RUNNING',checkpoint:99,checkpoints:keys.map(key=>({key}))}));
});


test('an explicitly isolated hospital component uses hospital role at checkpoint zero',()=>{
 assert.equal(participantForRun({state:'READY',checkpoint:0,execution_scope:'COMPONENT',
  checkpoints:[{key:'hospital_references_reported'}]}),'hospital_insurance');
});
