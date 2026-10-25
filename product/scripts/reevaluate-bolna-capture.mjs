// Offline re-evaluation of actual retained media. Never creates a provider call.
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {evaluateBolnaDialogue,parseBolnaTranscript} from './bolna-dialogue-evaluation.mjs';
const [reportPath,capturePath,archivePath,reviewPath]=process.argv.slice(2);
if(!reviewPath)throw new Error('Report, captured media, new archive and review paths required.');
const report=JSON.parse(await readFile(reportPath,'utf8')),capture=JSON.parse(await readFile(capturePath,'utf8'));
if(report.run_id!==capture.run_id||report.call_id!==capture.call_id||report.provider_execution_id!==capture.execution_id)
 throw new Error('Captured media belongs to another call.');
const evaluation=evaluateBolnaDialogue({transcript:report.provider_transcript,turns:report.turns,
 mode:report.participant_mode,purpose:report.participant_role==='caregiver'?'CAREGIVER_INTAKE':undefined,deferSemanticAlignment:true});
if(!evaluation.passed)throw new Error('Captured dialogue still fails: '+evaluation.issues.join(', '));
const turns=parseBolnaTranscript(report.provider_transcript);
if(turns.length!==capture.turns.length||turns.some((t,i)=>(t.role==='assistant'?'assistant':'participant')!==capture.turns[i].speaker))
 throw new Error('Captured media and provider turn boundaries differ.');
for(const [key,value] of Object.entries(report.dialogue_checks||{}))
 if(key!=='provider_dialogue_order_and_content'&&value!==true)throw new Error('Unresolved original media check: '+key);
const archive={execution_id:capture.execution_id,assistant_config_sha256:report.provider_configuration.assistant_config_sha256,
 provider_transcript_sha256:createHash('sha256').update(report.provider_transcript).digest('hex'),
 turns:turns.map((t,i)=>({speaker:capture.turns[i].speaker,text:t.text,pcm_base64:capture.turns[i].pcm_base64}))};
await writeFile(archivePath,JSON.stringify(archive),{flag:'wx',mode:0o600});
await writeFile(reviewPath,JSON.stringify({source_report:reportPath,source_capture:capturePath,evaluation,
 original_failure_preserved:true,new_provider_sessions:0,semantic_review_required:true}),{flag:'wx',mode:0o600});
console.log(JSON.stringify({offline_checks_passed:true,turns:turns.length,new_provider_sessions:0}));
