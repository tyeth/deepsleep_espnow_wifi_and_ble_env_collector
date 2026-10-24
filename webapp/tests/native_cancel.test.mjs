import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createRequire} from "node:module";
import {dirname, resolve} from "node:path";
import {fileURLToPath} from "node:url";
import vm from "node:vm";
import {test} from "node:test";

const htmlPath=process.argv[2] || fileURLToPath(new URL("../index.html",import.meta.url));
const html=readFileSync(htmlPath,"utf8");
const require=createRequire(import.meta.url);
const T=require(resolve(dirname(htmlPath),"ai_tools.js"));
function section(from,to){
 const start=html.indexOf(from),end=html.indexOf(to,start);
 assert.ok(start>=0&&end>start,`Missing portal source section: ${from}`);
 return html.slice(start,end);
}

for(const cancel of [false,true]){
 test(`native tool loop ${cancel?"skips a stopped":"runs an active"} queued SQL query`,async()=>{
  let release,queued,queries=0,destroyed=0,turn=0;
  const blocker=new Promise(resolve=>{release=resolve;});
  const waiting=new Promise(resolve=>{queued=resolve;});
  const stop=new AbortController();
  const session={destroy(){destroyed++;}};
  const py={globals:{set(){},get(){return JSON.stringify({cols:["co2"],rows:[[1234]],row_count:1});}},
   async runPythonAsync(){queries++;}};
  const context=vm.createContext({T,blocker,signal:stop.signal,SQL_MAX_ROWS:50,TOOL_ITER:3,AI_QUOTA_FRACTION:.8,
   aiSession:{async clone(){return session;}},
   quota:()=>({used:0,window:100}),
   ensureSqlDb:async()=>py,
   setStatus(_id,text){if(text==="querying your data...")queued();},
   showSteps(){},
   wasAborted:(_error,signal)=>signal.aborted,
   throwIfStopped:signal=>signal.throwIfAborted(),
   promptJSON:async()=>JSON.stringify(turn++?{answer:"CO2 is 1234 ppm"}:{tool:"sql",query:"SELECT MAX(co2) AS co2 FROM readings"})});
  vm.runInContext(section("let sqlQueue=Promise.resolve();","// render tool results")+
   section("async function askWithTools(q,signal){","let asking=false;"),context);
  vm.runInContext("sqlQueue=blocker",context);
  const result=vm.runInContext("askWithTools('Highest CO2?',signal)",context);
  await waiting;
  if(cancel)stop.abort();
  release();
  if(cancel)await assert.rejects(result,{name:"AbortError"});
  else assert.equal((await result).text,"CO2 is 1234 ppm");
  assert.equal(queries,cancel?0:1,"Stopped work must not reach the SQL engine");
  assert.equal(destroyed,1,"The temporary model session must be released");
 });
}
