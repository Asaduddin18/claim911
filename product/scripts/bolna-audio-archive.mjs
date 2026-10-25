export function appendBolnaArchiveAudio(archive,speaker,pcmBase64){
 if(!Array.isArray(archive)||!['assistant','participant'].includes(speaker)||typeof pcmBase64!=='string')
  throw new TypeError('A bounded Bolna archive audio turn is required.');
 const audio=Buffer.from(pcmBase64,'base64');
 if(!audio.length||audio.length%2!==0)throw new TypeError('Bolna PCM audio must contain complete 16-bit samples.');
 const previous=archive.at(-1);
 if(speaker==='assistant'&&previous?.speaker==='assistant'){
  // Keep a short pause when one spoken turn arrives as multiple VAD bouts.
  previous.pcm_base64=Buffer.concat([Buffer.from(previous.pcm_base64,'base64'),Buffer.alloc(1600),audio]).toString('base64');
 }else archive.push({speaker,pcm_base64:audio.toString('base64')});
 return archive;
}

// Keep each provider assistant line separate. Bolna may already have the
// transcript for the current audio segment before the browser finishes it.
export function bolnaAssistantTextAtTurn(transcript,turnIndex){
 if(typeof transcript!=='string'||!Number.isInteger(turnIndex)||turnIndex<0)return null;
 const turns=[];
 for(const line of transcript.split(/\r?\n/)){
  const match=line.match(/^\s*(assistant|agent|user|human)\s*:\s*(.*)$/i);
  if(match&&/assistant|agent/i.test(match[1]))turns.push(match[2].trim());
  else if(match)continue;
  else if(line.trim()&&turns.length)turns[turns.length-1]+=' '+line.trim();
 }
 const text=turns[turnIndex]?.trim();
 return text&&text.length<=4000?text:null;
}
