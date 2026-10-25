'use client';
import {useEffect,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import * as Tabs from '@radix-ui/react-tabs';
import {DialogContent} from '@/components/ui/dialog-content';
import CaseActivity from '@/components/case-activity';
import CaseFollowups from '@/components/case-followups';
import {X,ShieldCheck,ArrowRight,FileText,ArrowUpRight} from 'lucide-react';

export default function DecisionReview({caseId,onClose}){
 const [data,setData]=useState(null),[detail,setDetail]=useState(null),[error,setError]=useState('');
 useEffect(()=>{
  let current=true;setData(null);setDetail(null);setError('');
  if(caseId)Promise.all(['decisions',''].map(async suffix=>{
   const response=await fetch('/api/controller/cases/'+caseId+(suffix?'/'+suffix:''),{cache:'no-store'});
   if(!response.ok)throw new Error('The case could not be opened. Refresh your workspace.');return response.json();
  })).then(([decisions,record])=>{if(current){setData(decisions);setDetail(record)}}).catch(e=>{if(current)setError(e.message)});
  return()=>{current=false};
 },[caseId]);
 return <Dialog.Root open={!!caseId} onOpenChange={v=>{if(!v)onClose()}}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><DialogContent className="dialog decision-review">
  <Dialog.Title>Case review</Dialog.Title><Dialog.Description>Review the next action, its evidence and the conversations behind it.</Dialog.Description><Dialog.Close className="dialog-close" aria-label="Close case review"><X size={20}/></Dialog.Close>
  {error?<p role="alert">{error}</p>:!data||!detail?<p role="status">Checking the case…</p>:<Tabs.Root key={caseId} defaultValue="next"><Tabs.List className="case-tabs" aria-label="Case review sections"><Tabs.Trigger value="next">Next action</Tabs.Trigger><Tabs.Trigger value="documents">Documents</Tabs.Trigger><Tabs.Trigger value="followups">Follow-ups</Tabs.Trigger><Tabs.Trigger value="activity">Activity &amp; conversations</Tabs.Trigger></Tabs.List>
   <Tabs.Content value="next"><p className="setup-note">Proposals do not execute actions. Sharing documents requires the caregiver’s exact approval.</p>{!data.proposals.length&&<p>No new action is proposed. Review the case activity for unresolved items.</p>}{data.proposals.map(p=>{const policy=data.policy_decisions.find(d=>d.proposal_id===p.id);return <article className="decision-card" key={p.id}><p className="eyebrow">{p.desk.replaceAll('_',' ')}</p><h3>{p.summary}</h3><div className="permission-row"><ShieldCheck size={18}/><div><strong>{policy?.state.replaceAll('_',' ')||'Review required'}</strong><p>{policy?.reason||'Action checks are unavailable. Refresh before proceeding.'}</p></div></div><p><ArrowRight size={14}/> Expected result: {p.expected_checkpoint.replaceAll('_',' ')}</p><details><summary>Supporting evidence ({p.evidence_references.length})</summary><ul>{data.observations.filter(o=>p.evidence_references.includes(o.reference)).map(o=><li key={o.reference}>{o.summary} <small>({o.status})</small></li>)}</ul></details></article>})}</Tabs.Content>
   <Tabs.Content value="documents"><h3>Case documents</h3><p className="muted">An upload is separate from institution verification. Check the supporting action evidence.</p>{detail.documents?.length?detail.documents.map(d=><a className="document-row" key={d.id} href={'/api/controller/cases/'+caseId+'/documents/'+d.id} target="_blank" rel="noreferrer"><FileText size={18}/><span>{d.filename||d.name||'Case document'}<small>Uploaded evidence</small></span><ArrowUpRight size={16}/></a>):<p>No documents have been uploaded for this case.</p>}</Tabs.Content>
   <Tabs.Content value="followups"><CaseFollowups caseId={caseId}/></Tabs.Content>
   <Tabs.Content value="activity"><CaseActivity caseId={caseId} surface="controller"/></Tabs.Content>
  </Tabs.Root>}
 </DialogContent></Dialog.Portal></Dialog.Root>
}
