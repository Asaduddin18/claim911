// Pure post-call checks. Provider transcript evidence is authoritative here;
// expected scenario text must never be treated as audio recognition evidence.
export function normalizeIdentifierSpeech(value){
 const digits={zero:'0',one:'1',two:'2',three:'3',four:'4',five:'5',six:'6',seven:'7',eight:'8',nine:'9'};
 return String(value||'').toLowerCase()
  .replace(/\bclaim\s*(?:nine\s+eleven|nine\s+one\s+one|9\s*11|9\s+1\s+1)\b/g,'claim911')
  .replace(/\b(?:hyphen|dash)\b/g,'-')
  .replace(/\b(?:zero|one|two|three|four|five|six|seven|eight|nine)\b/g,word=>digits[word])
  .replace(/\b((?:[a-z][,\s]+)+[a-z])[,\s]+((?:\d[,\s]*)+)\b/g,(_,letters,digits)=>letters.replace(/[,\s]/g,'')+digits.replace(/[,\s]/g,''))
  .replace(/\b(?:[a-z]\s+)+[a-z]\b/g,letters=>letters.replace(/\s+/g,''))
  .replace(/(?<=\d)\s+(?=\d)/g,'').replace(/\s*-\s*/g,'-');
}
export const normalizeSpeech=value=>normalizeIdentifierSpeech(value).replace(/’/g,"'")
 .replace(/\bthat(?:'|\s+)s\b/g,'that is').replace(/\bclaim\s*(?:911|9\s+1\s+1)\b/g,'claim911')
 .replace(/[^a-z0-9 ]/g,' ').replace(/\s+/g,' ').trim();
const CALL_CLOSING_NOTE="Thanks, that's all I need for this call.";
const identifierCodes=value=>(normalizeIdentifierSpeech(value).match(/\b(?:[a-z]+(?:-[a-z0-9]+)*-\d[a-z0-9-]*|[a-z]+\d+)\b/g)||[])
 .filter(code=>code!=='claim911').sort();

function explicitReferenceRepair(actual,position,expectedCodes){
 if(!expectedCodes.length)return false;
 for(let i=position+1;i<actual.length-1;i++){
  if(actual[i].role!=='assistant'||actual[i+1].role!=='user'||!actual[i].text.includes('?'))continue;
  const readback=identifierCodes(actual[i].text),answer=normalizeSpeech(actual[i+1].text);
  if(expectedCodes.every(code=>readback.includes(code))&&/^(yes|correct|that is correct|those are correct)\b/.test(answer)
    &&! /\b(no|not|incorrect|wrong|except)\b/.test(answer))return true;
 }
 return false;
}

export function parseBolnaTranscript(transcript){
 if(typeof transcript!=='string')return [];
 const turns=[];
 for(const line of transcript.split(/\r?\n/)){
  const match=line.match(/^\s*(assistant|agent|user|human)\s*:\s*(.*)$/i);
  if(match){
   const role=/assistant|agent/i.test(match[1])?'assistant':'user';
   if(turns.at(-1)?.role===role)turns.at(-1).text+=' '+match[2];
   else turns.push({role,text:match[2]});
  }else if(line.trim()&&turns.length)turns.at(-1).text+=' '+line.trim();
 }
 return turns;
}

export function providerQuestionAtReply(transcript,participantTurns){
 if(!Number.isInteger(participantTurns)||participantTurns<0||participantTurns>12)return null;
 const turns=parseBolnaTranscript(transcript),last=turns.at(-1);
 if(turns.filter(t=>t.role==='user').length!==participantTurns||last?.role!=='assistant')return null;
 const text=last.text.trim();
 // Post-call text must not cause an early hangup or supply a future question.
 // Only a completed question at the current conversational position is usable.
 if(!text.endsWith('?')||text.length>4000||normalizeSpeech(text).includes(normalizeSpeech(CALL_CLOSING_NOTE)))return null;
 return text;
}

function lastQuestion(text){
 const questions=String(text||'').match(/[^.!?]*\?/g);
 return questions?.length?questions.at(-1):String(text||'').split(/[.!]/).filter(item=>item.trim()).at(-1)||'';
}

export function evaluateBolnaDialogue({transcript,turns,mode,purpose,deferSemanticAlignment=false}){
 const actual=parseBolnaTranscript(transcript),issues=[],checks=[],semanticReviews=[];
 if(!actual.length)issues.push('PROVIDER_TRANSCRIPT_MISSING');
 if(!Array.isArray(turns)||!turns.length)issues.push('PARTICIPANT_TURNS_MISSING');
 if(actual.at(-1)?.role!=='assistant'||!normalizeSpeech(actual.at(-1)?.text).includes(normalizeSpeech(CALL_CLOSING_NOTE)))
  issues.push('CALL_CLOSING_NOTE_MISSING');
 let cursor=0;
 if(actual.filter(turn=>turn.role==='user').length!==(turns||[]).length)issues.push('PARTICIPANT_TURN_COUNT_MISMATCH');
 for(const [index,expected] of (turns||[]).entries()){
  const answer=normalizeSpeech(expected.participant_text);
  const position=actual.findIndex((turn,i)=>i>=cursor&&turn.role==='user');
  if(position<0){issues.push(`TURN_${index+1}_PARTICIPANT_ANSWER_MISSING`);continue;}
  const exact=answer.length>0&&normalizeSpeech(actual[position].text)===answer;
  const expectedCodes=identifierCodes(expected.participant_text);
  if(JSON.stringify(expectedCodes)!==JSON.stringify(identifierCodes(actual[position].text))){
   const repaired=deferSemanticAlignment&&explicitReferenceRepair(actual,position,expectedCodes);
   if(!deferSemanticAlignment)issues.push(`TURN_${index+1}_IDENTIFIER_MISMATCH`);
   else semanticReviews.push({turn:index+1,kind:repaired?'reference_repair_requires_semantic_confirmation':'identifier_alignment_requires_semantic_confirmation',
    expected_codes:expectedCodes,recognized_codes:identifierCodes(actual[position].text)});
  }
  if(!exact){
   semanticReviews.push({turn:index+1,injected_text:expected.participant_text,recognized_text:actual[position].text});
   if(!deferSemanticAlignment)issues.push(`TURN_${index+1}_PARTICIPANT_ANSWER_MISSING`);
  }
  const question=actual[position-1],followUp=actual[position+1];
  const expectedQuestion=expected.assistant_text;
  const questionMatches=question?.role==='assistant'&&normalizeSpeech(lastQuestion(question.text))===normalizeSpeech(lastQuestion(expectedQuestion));
  if(!questionMatches){
   if(deferSemanticAlignment&&question?.role==='assistant')semanticReviews.push({turn:index+1,kind:'question_recognition',heard_question:expectedQuestion,provider_question:question.text});
   else issues.push(`TURN_${index+1}_PRECEDING_QUESTION_MISMATCH`);
  }
  if(followUp?.role!=='assistant'||!normalizeSpeech(followUp.text))issues.push(`TURN_${index+1}_ASSISTANT_FOLLOWUP_MISSING`);
  if(!['live_audio_transcription','bolna_provider_transcript'].includes(expected.question_source))
   issues.push(`TURN_${index+1}_LIVE_QUESTION_SOURCE_MISSING`);
  checks.push({turn:index+1,preceding_assistant_text:question?.text||null,participant_text:actual[position].text,
   following_assistant_text:followUp?.role==='assistant'?followUp.text:null,question_matches:questionMatches,
   question_evidence:'bolna_provider_transcript'});
  cursor=position+1;
 }
 if(purpose==='CAREGIVER_INTAKE'&&actual.length){
  if(actual.filter(turn=>turn.role==='user').length>2)issues.push('CAREGIVER_INTAKE_EXTRA_PARTICIPANT_TURN');
  if(actual.at(-1)?.role!=='assistant')issues.push('CAREGIVER_HANDOFF_NOT_TERMINAL');
  const lastParticipant=actual.map((turn,index)=>turn.role==='user'?index:-1).filter(index=>index>=0).at(-1);
  const closing=actual[lastParticipant+1];
  const text=closing?.role==='assistant'?closing.text:'';
  const lower=normalizeSpeech(text);
  const handoffSpeech=normalizeSpeech(text.replace(/^\s*Let me check the case record[.!]?\s*/i,''));
  const wordCount=handoffSpeech?handoffSpeech.split(' ').length:0;
  if(!text)issues.push('CAREGIVER_HANDOFF_MISSING');
  if(/cannot (?:access|check)|no connection|connection.{0,30}(?:not ready|unavailable)|do not have.{0,20}connection/i.test(text))
   issues.push('CAREGIVER_HANDOFF_FALSE_BLOCKER');
  if(/reference number|timestamp|receipt|share (?:any )?document|provide (?:a )?document/i.test(text))
   issues.push('CAREGIVER_HANDOFF_REQUESTS_EVIDENCE');
  if(/\b(?:i(?:'ve| have)?|we(?:'ve| have)?)\s+(?:already\s+)?(?:(?:reported|sent|submitted)\b[^.!?]{0,55}\bto\s+(?:the\s+)?|(?:notified|contacted|called)\s+(?:the\s+)?)(?:hospital|insurer|tpa|desk)\b/i.test(text))
   issues.push('CAREGIVER_INTAKE_UNSUPPORTED_EXTERNAL_ACTION');
  if(!/claim911.{0,40}(?:continue|check|coordinate|contact)|(?:continue|coordinate|check).{0,50}(?:hospital|insurer|desk)/i.test(text))
   issues.push('CAREGIVER_HANDOFF_DOES_NOT_EXPLAIN_NEXT_STEP');
  if(wordCount>36)issues.push('CAREGIVER_HANDOFF_TOO_LONG');
  if((text.match(/\?/g)||[]).length>0)issues.push('CAREGIVER_HANDOFF_ASKS_ANOTHER_QUESTION');
  checks.push({purpose:'CAREGIVER_INTAKE',closing_text:text||null,word_count:wordCount,
   next_step_clear:Boolean(text&&/claim911.{0,40}(?:continue|check|coordinate|contact)|(?:continue|coordinate|check).{0,50}(?:hospital|insurer|desk)/i.test(text))});
 }
 return {passed:issues.length===0,mode,adaptive:mode!=='scenario-scripted',issues,turn_checks:checks,
  checkpoint_eligible:false,identifiers_verified:false,
  semantic_alignment_required:semanticReviews.length>0,semantic_reviews:semanticReviews,
  limits:'Checks expected exchange order and speech content. Human review and independent state verification remain required.'};
}
