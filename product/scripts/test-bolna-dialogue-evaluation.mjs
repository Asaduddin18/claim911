import {test} from 'node:test';
import assert from 'node:assert/strict';
import {evaluateBolnaDialogue} from './bolna-dialogue-evaluation.mjs';

const turn={assistant_text:'What is holding things up?',expected_assistant_question:'What is holding things up?',
 question_source:'live_audio_transcription',participant_text:'The hospital says insurance is pending.'};
const check=transcript=>evaluateBolnaDialogue({transcript,turns:[turn],mode:'scenario-scripted'});

test('product name recognition is ordinary wording, while case identifiers stay exact',()=>{
 const turns=[{...turn,participant_text:'Please ask Claim911 to check final request FIN63.'}];
 const evaluate=text=>evaluateBolnaDialogue({turns,mode:'adaptive',deferSemanticAlignment:true,
  transcript:`assistant: What is holding things up?\nuser: Please ask claim nine eleven to check final request ${text}.\nassistant: Thanks, that's all I need for this call.`});
 assert.equal(evaluate('FIN63').passed,true);
 assert.equal(evaluate('FIN64').semantic_alignment_required,true);
 assert.equal(evaluate('FIN64').identifiers_verified,false);
});

test('accepts the real provider question, exact actor answer and assistant follow-up',()=>{
 assert.equal(check("assistant: Hi, I am Claim911. What is holding things up?\nuser: The hospital says insurance is pending!\nassistant: Which documents are missing? Thanks, that's all I need for this call.").passed,true);
});
test('rejects the original language-question versus consent-answer defect',()=>{
 const result=check('assistant: What language do you prefer?\nuser: The hospital says insurance is pending.\nassistant: I can help.');
 assert.equal(result.passed,false);assert.ok(result.issues.includes('TURN_1_PRECEDING_QUESTION_MISMATCH'));
});
test('an earlier matching question does not conceal an unrelated latest question',()=>{
 assert.equal(check('assistant: What is holding things up? Which language do you prefer?\nuser: The hospital says insurance is pending.\nassistant: Okay.').passed,false);
});
test('connection, expected text and a greeting cannot pass without participant speech',()=>{
 assert.equal(check('assistant: What is holding things up?').passed,false);
});
test('a hangup after actor speech fails without the next assistant turn',()=>{
 assert.equal(check('assistant: What is holding things up?\nuser: The hospital says insurance is pending.').passed,false);
});
test('a transcript quoting the actor answer in an assistant turn cannot pass',()=>{
 assert.equal(check('assistant: What is holding things up? The hospital says insurance is pending.\nassistant: Okay.').passed,false);
});
test('adaptive evidence requires a live audio question source',()=>{
 const result=evaluateBolnaDialogue({transcript:'assistant: What is holding things up?\nuser: The hospital says insurance is pending.\nassistant: Okay.',
  turns:[{...turn,assistant_text:turn.expected_assistant_question,question_source:'versioned_scenario_expectation'}],mode:'adaptive'});
 assert.equal(result.passed,false);assert.ok(result.issues.includes('TURN_1_LIVE_QUESTION_SOURCE_MISSING'));
});
test('missing transcript and missing turns fail closed',()=>{
 assert.equal(evaluateBolnaDialogue({transcript:'',turns:[],mode:'scenario-scripted'}).passed,false);
});
test('scripted participants also require the actual question rather than a scenario expectation',()=>{
 const result=evaluateBolnaDialogue({transcript:"assistant: What is holding things up?\nuser: The hospital says insurance is pending.\nassistant: Thanks, that's all I need for this call.",
  turns:[{...turn,question_source:'versioned_scenario_expectation'}],mode:'scenario-scripted'});
 assert.equal(result.passed,false);assert.ok(result.issues.includes('TURN_1_LIVE_QUESTION_SOURCE_MISSING'));
});

test('caregiver intake requires a concise, clear desk-coordination handoff',()=>{
 const result=evaluateBolnaDialogue({purpose:'CAREGIVER_INTAKE',mode:'adaptive',turns:[
  {assistant_text:'What is holding things up?',participant_text:'Insurance clearance is pending.',question_source:'live_audio_transcription'}],
  transcript:"assistant: What is holding things up?\nuser: Insurance clearance is pending.\nassistant: Thanks, I understand. Claim911 will continue with the hospital and insurer desks, then show you what they confirm. Thanks, that's all I need for this call."});
 assert.equal(result.passed,true);
});

test('Bolna provider transcript is valid live assistant text evidence',()=>{
 const result=evaluateBolnaDialogue({mode:'adaptive',turns:[{assistant_text:'What is holding things up?',
  participant_text:'Insurance clearance is pending.',question_source:'bolna_provider_transcript'}],
  transcript:'assistant: What is holding things up?\nuser: Insurance clearance is pending.\nassistant: I will check. Thanks, that is all I need for this call.'});
 assert.ok(!result.issues.includes('TURN_1_LIVE_QUESTION_SOURCE_MISSING'));
});

test('every role needs the common terminal closing note',()=>{
 const result=evaluateBolnaDialogue({mode:'scenario-scripted',turns:[turn],
  transcript:'assistant: What is holding things up?\nuser: The hospital says insurance is pending.\nassistant: I will check the record.'});
 assert.ok(result.issues.includes('CALL_CLOSING_NOTE_MISSING'));
});
test('transcription spacing and expanded contractions retain the same closing meaning',()=>{
 const result=evaluateBolnaDialogue({mode:'scenario-scripted',turns:[turn],
  transcript:'assistant: What is holding things up?\nuser: The hospital says insurance is pending.\nassistant: Claim 911 will check. Thanks, that is all I need for this call.'});
 assert.equal(result.passed,true);
});

test('caregiver handoff rejects an untracked post-handoff participant turn',()=>{
 const evaluate=transcript=>evaluateBolnaDialogue({purpose:'CAREGIVER_INTAKE',mode:'adaptive',turns:[
  {assistant_text:'What is holding things up?',participant_text:'Insurance clearance is pending.',question_source:'live_audio_transcription'}],transcript});
 assert.equal(evaluate("assistant: What is holding things up?\nuser: Insurance clearance is pending.\nassistant: Thanks, I understand. Claim911 will check with the hospital and insurer, then show you what they confirm. Thanks, that's all I need for this call.").passed,true);
 const extra=evaluate('assistant: What is holding things up?\nuser: Insurance clearance is pending.\nassistant: Claim911 will check with the hospital and insurer.\nuser: Please do.\nassistant: We will show you what they confirm.');
 assert.equal(extra.passed,false);assert.ok(extra.issues.includes('PARTICIPANT_TURN_COUNT_MISMATCH'));
});

test('caregiver intake rejects unsupported connection claims and another request for references',()=>{
 const result=evaluateBolnaDialogue({purpose:'CAREGIVER_INTAKE',mode:'adaptive',turns:[
  {assistant_text:'What is holding things up?',participant_text:'Insurance clearance is pending.',question_source:'live_audio_transcription'}],
  transcript:'assistant: What is holding things up?\nuser: Insurance clearance is pending.\nassistant: The connection is not ready. Can you share a reference number?'});
 assert.equal(result.passed,false);
 assert.ok(result.issues.includes('CAREGIVER_HANDOFF_FALSE_BLOCKER'));
 assert.ok(result.issues.includes('CAREGIVER_HANDOFF_REQUESTS_EVIDENCE'));
});

test('a tool preamble does not inflate the bounded final handoff, while a later reprompt still fails',()=>{
 const transcript="assistant: What is holding things up?\nuser: The hospital says insurance is pending.\nassistant: Let me check the case record.\nassistant: The hospital says final insurance clearance is pending. Claim 911 will check with the hospital and insurer, then show you what they confirm. Thanks, that's all I need for this call.";
 const check=text=>evaluateBolnaDialogue({purpose:'CAREGIVER_INTAKE',mode:'scenario-scripted',turns:[turn],transcript:text});
 assert.equal(check(transcript).passed,true);
 assert.equal(check(transcript+'\nassistant: Hello, are you still on the line?').passed,false);
});

test('intake cannot claim a saved case note notified another institution',()=>{
 const check=closing=>evaluateBolnaDialogue({purpose:'CAREGIVER_INTAKE',mode:'scenario-scripted',turns:[turn],
  transcript:`assistant: What is holding things up?\nuser: The hospital says insurance is pending.\nassistant: ${closing} Claim911 will check with the hospital and insurer. Thanks, that's all I need for this call.`});
 for(const claim of ["I've reported the concern to the hospital.",'I have notified the insurer.','We contacted the hospital.'])
  assert.ok(check(claim).issues.includes('CAREGIVER_INTAKE_UNSUPPORTED_EXTERNAL_ACTION'));
 assert.ok(!check('I have saved your concern.').issues.includes('CAREGIVER_INTAKE_UNSUPPORTED_EXTERNAL_ACTION'));
});

test('literal and exactly spelled identifiers align without accepting a different code',()=>{
 const expected={assistant_text:'What is the admission ID?',participant_text:'The admission ID is ADM-SYN-2084.',question_source:'live_audio_transcription'};
 const evaluate=code=>evaluateBolnaDialogue({mode:'adaptive',turns:[expected],
  transcript:`assistant: What is the admission ID?\nuser: The admission ID is ${code}.\nassistant: Thanks, that's all I need for this call.`});
 assert.equal(evaluate('a d m hyphen s y n hyphen two zero eight four').passed,true);
 assert.equal(evaluate('a d m hyphen s y n hyphen two zero eight five').passed,false);
 assert.equal(evaluate('ADM-SIN-2084').passed,false);
});

test('ordinary recognition differences require explicit semantic review, never silent acceptance',()=>{
 const expected={assistant_text:'What is holding things up?',participant_text:'Discharge is held for insurance clearance.',question_source:'bolna_provider_transcript'};
 const args={mode:'adaptive',turns:[expected],transcript:"assistant: What is holding things up?\nuser: This charge is held for insurance clearance.\nassistant: Thanks, that's all I need for this call."};
 assert.equal(evaluateBolnaDialogue(args).passed,false);
 const deferred=evaluateBolnaDialogue({...args,deferSemanticAlignment:true});
 assert.equal(deferred.passed,true);
 assert.equal(deferred.semantic_alignment_required,true);
 assert.equal(deferred.semantic_reviews[0].recognized_text,'This charge is held for insurance clearance.');
});

test('identifier differences require independent review and cannot themselves verify a checkpoint',()=>{
 const args={mode:'adaptive',deferSemanticAlignment:true,turns:[{assistant_text:'What is the admission ID?',participant_text:'ADM-SYN-2084.',question_source:'bolna_provider_transcript'}],
  transcript:"assistant: What is the admission ID?\nuser: ADM-SYN-2085.\nassistant: Thanks, that's all I need for this call."};
 assert.equal(evaluateBolnaDialogue(args).semantic_alignment_required,true);
 assert.equal(evaluateBolnaDialogue(args).checkpoint_eligible,false);
 assert.equal(evaluateBolnaDialogue({...args,deferSemanticAlignment:false}).passed,false);
 args.transcript+='\nuser: Yes.\nassistant: Thanks, that is all I need for this call.';
 assert.ok(evaluateBolnaDialogue(args).issues.includes('PARTICIPANT_TURN_COUNT_MISMATCH'));
});

test('one caregiver issue confirmation is allowed before terminal handoff',()=>{
 const second={assistant_text:'You are waiting for final insurance clearance before discharge. Is that right?',participant_text:'Yes, that is right.',question_source:'bolna_provider_transcript'};
 const result=evaluateBolnaDialogue({purpose:'CAREGIVER_INTAKE',mode:'adaptive',turns:[turn,second],
  transcript:`assistant: ${turn.assistant_text}\nuser: ${turn.participant_text}\nassistant: ${second.assistant_text}\nuser: ${second.participant_text}\nassistant: Claim911 will check with the hospital and insurer, then show you what they confirm. Thanks, that's all I need for this call.`});
 assert.equal(result.passed,true);
});

test('a damaged code and its attempted repair remain pending independent semantic review',()=>{
 const turns=[{assistant_text:'What is the final reference?',participant_text:'FINAL-SYN-2084.',question_source:'live_audio_transcription'},
  {assistant_text:'Is the final reference FINAL-SYN-2084 correct?',participant_text:'Yes, that is correct.',question_source:'live_audio_transcription'}];
 const transcript="assistant: What is the final reference?\nuser: INAL-SYN-2084.\nassistant: Is the final reference FINAL-SYN-2084 correct?\nuser: Yes, that is correct.\nassistant: Thanks, that's all I need for this call.";
 const result=evaluateBolnaDialogue({transcript,turns,mode:'adaptive',deferSemanticAlignment:true});
 assert.equal(result.passed,true);assert.equal(result.semantic_alignment_required,true);
 assert.equal(evaluateBolnaDialogue({transcript:transcript.replace('Is the final reference FINAL-SYN-2084 correct?','Is that right?'),turns,mode:'adaptive',deferSemanticAlignment:true}).semantic_alignment_required,true);
 assert.equal(evaluateBolnaDialogue({transcript:transcript.replace('user: Yes, that is correct.','user: No, that is not correct.'),turns,mode:'adaptive',deferSemanticAlignment:true}).checkpoint_eligible,false);
});

test('live provider questions must match the current reply position and cannot end media early',async()=>{
 const {providerQuestionAtReply}=await import('./bolna-dialogue-evaluation.mjs');
 const transcript='assistant: What is the admission?\nuser: ADM-SYN-2084.\nassistant: Is ADM-SYN-2084 correct?';
 assert.equal(providerQuestionAtReply(transcript,1),'Is ADM-SYN-2084 correct?');
 assert.equal(providerQuestionAtReply(transcript,0),null);
 assert.equal(providerQuestionAtReply(transcript+'\nuser: Yes.',2),null);
 assert.equal(providerQuestionAtReply(transcript+'\nassistant: Let me check.',1),null);
 assert.equal(providerQuestionAtReply(transcript+"\nassistant: Thanks, that's all I need for this call. Any questions?",1),null);
});


test('short identifiers remain exact under deferred semantic evaluation',()=>{
 const turns=[{assistant_text:'What is the admission ID?',participant_text:'The admission ID is ADM42.',question_source:'live_audio_transcription'}];
 const transcript="assistant: What is the admission ID?\nuser: The admission ID is ADM42.\nassistant: Thanks, that's all I need for this call.";
 const evaluate=text=>evaluateBolnaDialogue({transcript:text,turns,mode:'adaptive',deferSemanticAlignment:true});
 assert.equal(evaluate(transcript).passed,true);
 assert.equal(evaluate(transcript.replace('user: The admission ID is ADM42.','user: The admission ID is ADM43.')).semantic_alignment_required,true);
 assert.equal(evaluate(transcript.replace('user: The admission ID is ADM42.','user: The admission ID is PRE37.')).identifiers_verified,false);
});


test('spelled compact identifiers align while changed characters remain mismatches',()=>{
 const turns=[{assistant_text:'What is the admission ID?',participant_text:'The admission ID is ADM42.',question_source:'live_audio_transcription'}];
 const evaluate=answer=>evaluateBolnaDialogue({transcript:"assistant: What is the admission ID?\nuser: "+answer+"\nassistant: Thanks, that's all I need for this call.",turns,mode:'adaptive',deferSemanticAlignment:true});
 assert.equal(evaluate('The admission ID is a d m four two.').passed,true);
 assert.equal(evaluate('The admission ID is A, D, M, four, two.').passed,true);
 assert.equal(evaluate('The admission ID is a d m four three.').semantic_alignment_required,true);
 assert.equal(evaluate('The admission ID is a d n four two.').checkpoint_eligible,false);
});
