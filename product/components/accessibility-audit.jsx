'use client';
import {useEffect,useState} from 'react';

export default function AccessibilityAudit(){
 const [result,setResult]=useState(null),[busy,setBusy]=useState(false);
 async function run(){
  setBusy(true);
  try{
   const axe=(await import('axe-core')).default;
   const report=await axe.run({exclude:[['#claim911-audit-panel']]},{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}});
   setResult({url:location.pathname+location.search,engine:report.testEngine,checkedAt:report.timestamp,
    violations:report.violations.map(v=>({id:v.id,impact:v.impact,description:v.description,help:v.help,helpUrl:v.helpUrl,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),
    passes:report.passes.length,incomplete:report.incomplete.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)}))});
  }catch(error){setResult({error:String(error)})}
  finally{setBusy(false)}
 }
 useEffect(()=>{function shortcut(event){if(event.altKey&&event.shiftKey&&event.code==='KeyA'&&!busy){event.preventDefault();run()}}window.addEventListener('keydown',shortcut);return()=>window.removeEventListener('keydown',shortcut)},[busy]);
 return <aside id="claim911-audit-panel" aria-label="Local accessibility evaluation" style={{margin:'24px',padding:'20px',border:'1px solid #ccd4c8',borderRadius:'12px'}}>
  <p>Local evaluation mode. Automated results supplement keyboard and visual checks. Alt+Shift+A also checks the current view, including an open dialog.</p>
  <button type="button" onClick={run} disabled={busy} style={{padding:'12px',marginTop:'12px',border:'1px solid #60745b',borderRadius:'8px'}}>{busy?'Checking accessibility…':'Run accessibility check'}</button>
  {result&&<pre data-testid="accessibility-results" style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',fontSize:'12px',marginTop:'16px'}}>{JSON.stringify(result,null,2)}</pre>}
 </aside>
}
