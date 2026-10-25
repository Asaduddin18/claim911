import {rm,readdir,readFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const root=fileURLToPath(new URL('..',import.meta.url));
// Only disposable build cache is removed. Source, sessions and case data stay intact.
await rm(path.join(root,'.next','cache'),{recursive:true,force:true});
const child=spawn(process.execPath,[path.join(root,'node_modules','next','dist','bin','next'),'build','--webpack'],{
 cwd:root,stdio:'inherit',env:{...process.env,NEXT_TELEMETRY_DISABLED:'1'}});
const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve)});
if(code!==0)process.exit(code||1);
async function styles(directory){
 const entries=await readdir(directory,{withFileTypes:true});let result='';
 for(const entry of entries){const file=path.join(directory,entry.name);if(entry.isDirectory())result+=await styles(file);else if(entry.name.endsWith('.css'))result+=await readFile(file,'utf8')}
 return result;
}
const css=await styles(path.join(root,'.next','static'));
for(const selector of ['sandbox-workspace','run-choice','financial-breakdown','document-checklist']){
 if(!css.includes('.'+selector))throw new Error('Required product styles are missing: '+selector);
}
console.log('Verified caregiver and sandbox component styles in the production output.');
