import Workspace from '@/components/workspace';
import AccessibilityAudit from '@/components/accessibility-audit';
export const dynamic='force-dynamic';
export default async function Page({searchParams}){const query=await searchParams;return <><Workspace surface={process.env.CLAIM911_SURFACE||'caregiver'}/>{query?.audit==='1'&&<AccessibilityAudit/>}</>}
