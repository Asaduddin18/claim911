'use client';
import {useEffect,useState} from 'react';
import {ShieldCheck} from 'lucide-react';
import {Button} from '@/components/ui/button';

export default function CaregiverPermissions({active,busy,onInvestigation,onPacket}){
 const packet=active.packet_permission;
 const [accepted,setAccepted]=useState(false);
 useEffect(()=>setAccepted(false),[packet?.packet_hash,packet?.approved]);
 return <><h3>You decide what gets shared.</h3><div className="permission-row"><ShieldCheck size={23}/><div><strong>Investigation permission</strong><p>{active.consent_active?'You allowed Claim911 to investigate this case.':'Investigation is paused.'}</p></div><span className="pill">{active.consent_active?'Allowed':'Inactive'}</span></div><Button variant="outline" disabled={busy} onClick={()=>onInvestigation(!active.consent_active)}>{active.consent_active?'Pause investigation':'Allow investigation'}</Button><p className="muted">Pausing cancels pending follow-ups and disables active case tools.</p>{packet?<section className="packet-permission"><h3>{packet.approved?'Document sharing approved':'Review a document-sharing request'}</h3><p>Recipient: <strong>{packet.recipient}</strong></p><ul>{packet.documents.map(d=><li key={d.id}>{d.kind.replaceAll('_',' ')}{d.revision&&<> · version {d.revision}</>}<small> · {d.id}</small></li>)}</ul>{packet.approved?<><p>Permission applies to this exact document packet.</p><Button variant="outline" disabled={busy} onClick={()=>onPacket(false)}>Withdraw document-sharing permission</Button><p className="muted">This stops future sharing. Documents already received cannot be recalled.</p></>:<><label className="consent-check"><input type="checkbox" checked={accepted} onChange={e=>setAccepted(e.target.checked)}/><span>I approve sharing only these documents with this recipient.</span></label><Button disabled={busy||!accepted||!active.consent_active} onClick={()=>onPacket(true)}>Approve this packet</Button><p className="muted">Any document change needs your approval again.</p></>}</section>:<p className="muted">No document-sharing request is waiting for your approval.</p>}</>
}
