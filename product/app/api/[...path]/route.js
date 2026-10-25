export const dynamic='force-dynamic';
async function proxy(request,{params}){
 const {path}=await params; const surface=process.env.CLAIM911_SURFACE||'caregiver';
 const target=process.env.CLAIM911_API_URL||(surface==='sandbox'?'http://127.0.0.1:8121':'http://127.0.0.1:8120');
 const route=path.join('/');
 if(path.some(p=>p==='..')||!(route==='sessions'||route.startsWith('sessions/')||route==='health'||route.startsWith(surface+'/')))return Response.json({detail:'This action belongs to another workspace.'},{status:403});
 let body=request.method==='GET'||request.method==='HEAD'?undefined:await request.arrayBuffer();
 if(route==='sessions'&&request.method==='POST'){
  const input=JSON.parse(new TextDecoder().decode(body));
  const scopedHarness=surface==='sandbox'&&input.role==='sandbox_harness'
   &&typeof input.run_id==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(input.run_id);
  if(input.role!==surface&&!scopedHarness)return Response.json({detail:'Invalid workspace role.'},{status:403});
 }
 try{
  const r=await fetch(target+'/v2/'+route+new URL(request.url).search,{method:request.method,headers:{cookie:request.headers.get('cookie')||'','content-type':request.headers.get('content-type')||'application/json','last-event-id':request.headers.get('last-event-id')||'0'},body,cache:'no-store',redirect:'manual',signal:request.signal});
  const headers=new Headers();for(const h of ['content-type','set-cookie','content-disposition','x-content-type-options','cache-control','x-accel-buffering'])if(r.headers.has(h))headers.set(h,r.headers.get(h));
  return new Response(r.body,{status:r.status,headers});
 }catch{return Response.json({detail:'The workspace is temporarily unavailable. Your saved case has not been changed.'},{status:503})}
}
export {proxy as GET,proxy as POST,proxy as DELETE};
