import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {test} from "node:test";
const require=createRequire(import.meta.url);
const {register}=require("../webmcp.js");
const {createResolver,progress,queryText}=require("../prompt_backend.js");
const {validateSql,SQL_TABLES}=require("../ai_tools.js");

test("WebMCP is optional and does not register on HTTP",async()=>{
 let called=false;
 assert.equal(await register({secure:false,context:{registerTool(){called=true;}}}),null);
 assert.equal(await register({secure:true}),null);
 assert.equal(called,false);
});
test("tools see fresh data, reject bad input, observe cancellation, and clean up",async()=>{
 const tools=[];let rows=0;let queries=0;
 const dispose=await register({secure:true,context:{async registerTool(t,o){tools.push([t,o]);}},
  metadata:()=>({rows}),schema:()=>"readings",query:async sql=>{queries++;return {sql};}});
 assert.equal(tools.length,2);
 assert.equal((await tools[1][0].execute({sql:"SELECT 1"})).error.includes("No data"),true);
 rows=2;
 assert.equal((await tools[0][0].execute({})).rows,2);
 assert.match((await tools[1][0].execute({sql:42})).error,/nonempty/);
 const stop=new AbortController();stop.abort();
 assert.ok((await tools[1][0].execute({sql:"SELECT 1"},{signal:stop.signal})).error);
 assert.equal(queries,0);
 assert.deepEqual(await tools[1][0].execute({sql:"SELECT 1"}),{sql:"SELECT 1"});
 dispose();assert.ok(tools.every(([,o])=>o.signal.aborted));
});
test("partial registration failure aborts the first tool",async()=>{
 let signal,n=0;
 await assert.rejects(register({secure:true,context:{async registerTool(t,o){signal=o.signal;if(++n===2)throw Error("no");}}}),/no/);
 assert.ok(signal.aborted);
});
test("native API is preserved and local download requires opt-in",async()=>{
 const native={create(){}};let imports=0;
 const resolver=createResolver({LanguageModel:native},()=>imports++);
 assert.equal(await resolver.resolve({allowLocal:true}),native);
 assert.equal(imports,0);
 assert.equal(await createResolver({isSecureContext:true},()=>imports++).resolve(),null);
 assert.equal(imports,0);
});
test("mobile loader is single flight, local only, and retryable",async()=>{
 const host={isSecureContext:true};let imports=0;
 const resolver=createResolver(host,async()=>{imports++;if(imports===1)throw Error("offline");host.LanguageModel={create(){}};});
 await assert.rejects(resolver.resolve({allowLocal:true}),/offline/);
 const [a,b]=await Promise.all([resolver.resolve({allowLocal:true}),resolver.resolve({allowLocal:true})]);
 assert.equal(a,b);assert.equal(imports,2);assert.equal(resolver.local,true);
 assert.equal(host.TRANSFORMERS_CONFIG.device,"wasm");
 assert.equal(host.TRANSFORMERS_CONFIG.apiKey,"dummy");
});
test("unavailable native model uses the opt-in export without replacing native API",async()=>{
 const native={create(){}};const fallback={create(){}};
 const host={isSecureContext:true,LanguageModel:native};
 const resolver=createResolver(host,async()=>({LanguageModel:fallback}));
 assert.equal(await resolver.resolve({nativeUnavailable:true}),null);
 assert.equal(await resolver.resolve({nativeUnavailable:true,allowLocal:true}),fallback);
 assert.equal(host.LanguageModel,native);
 assert.equal(resolver.local,true);
 assert.equal(await resolver.resolve(),native);
 assert.equal(resolver.local,false);
});
test("stopped and insecure loads do not import; cloud config cannot leak readings",async()=>{
 let imports=0;const stop=new AbortController();stop.abort();
 await assert.rejects(createResolver({isSecureContext:true},()=>imports++).resolve({allowLocal:true,signal:stop.signal}));
 await assert.rejects(createResolver({isSecureContext:false},()=>imports++).resolve({allowLocal:true}),/HTTPS/);
 await assert.rejects(createResolver({isSecureContext:true,OPENAI_CONFIG:{}},()=>imports++).resolve({allowLocal:true}),/Another AI/);
 assert.equal(imports,0);
});
test("download progress handles normalized and byte events",()=>{
 assert.equal(progress({loaded:.5}),.5);
 assert.equal(progress({loaded:50,total:100}),.5);
 assert.equal(progress({loaded:200,total:100}),1);
 assert.equal(progress({}),null);
});

test("local inference chooses an available GPU and survives adapter rejection",async()=>{
 for (const [requestAdapter,expected] of [[async()=>({features:new Set(["shader-f16"])}),"webgpu"],
                                        [async()=>{throw Error("blocked");},"wasm"]]) {
  const host={isSecureContext:true,navigator:{gpu:{requestAdapter}}};
  const resolver=createResolver(host,async()=>({LanguageModel:{create(){}}}));
  await resolver.resolve({allowLocal:true});
  assert.equal(host.TRANSFORMERS_CONFIG.device,expected);
  assert.equal(host.TRANSFORMERS_CONFIG.dtype,expected==="wasm"?"q8":"q4");
  assert.equal(host.TRANSFORMERS_CONFIG.env.backends.onnx.wasm.proxy,expected==="wasm");
 }
});

test("phone model SQL fences are removed but unsafe statements still fail validation",()=>{
 assert.match(validateSql(queryText("```sql\nSELECT MAX(co2) FROM readings\n```"),SQL_TABLES,50),/^SELECT/);
 assert.equal(queryText("```sql\nSELECT MAX(co2) FROM readings\n```\nAnother example:\n```sql\nDELETE FROM readings\n```"),"SELECT MAX(co2) FROM readings");
 for(const reply of ["```sql\nDELETE FROM readings\n```", "```sql\nSELECT co2 FROM readings; DELETE FROM readings\n```", "SELECT co2 FROM readings; DELETE FROM readings", "Here is a query: SELECT co2 FROM readings"]){
  assert.throws(()=>validateSql(queryText(reply),SQL_TABLES,50));
 }
});

test("a prefaced fenced model query validates the entire SQL block",()=>{
 const reply="To answer your question:\n\n```sql\nSELECT src, MAX(co2) FROM readings GROUP BY src;\n```\nThis groups the readings by zone.";
 assert.match(validateSql(queryText(reply),SQL_TABLES,50),/^SELECT src, MAX\(co2\)/);
 for(const sql of ["DELETE FROM readings", "SELECT * FROM readings; DELETE FROM readings"]){
  assert.throws(()=>validateSql(queryText("Here is the query:\n```sql\n"+sql+"\n```"),SQL_TABLES,50));
 }
 assert.throws(()=>validateSql(queryText("Here is the query: SELECT * FROM readings"),SQL_TABLES,50));
});
