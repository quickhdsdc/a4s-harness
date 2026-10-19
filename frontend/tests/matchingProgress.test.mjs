import {workspaceDirectory, workspaceModule} from './workspace.mjs'
import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync,writeFileSync,mkdirSync,unlinkSync} from 'node:fs'
import {transform} from 'esbuild'
import {parse,compileScript} from '@vue/compiler-sfc'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'

const directory=workspaceDirectory('matching-tests')
mkdirSync(directory,{recursive:true})
let sequence=0
async function moduleFrom(source,files) {
  const {code}=await transform(source,{loader:'ts',format:'esm'})
  const file=new URL(`matching-${++sequence}.mjs`,directory)
  writeFileSync(file,workspaceModule(code));files.push(file)
  return import(file.href)
}
async function component(files) {
  const {descriptor}=parse(readFileSync(new URL('../src/components/MatchingProgress.vue',import.meta.url),'utf8'))
  const code=compileScript(descriptor,{id:'matching-progress-test',inlineTemplate:true,genDefaultAs:'__component'}).content
  return (await moduleFrom(code+'\nexport default __component',files)).default
}
async function service(mock,files) {
  globalThis.__matchingMock=mock
  let code=readFileSync(new URL('../src/services/aasService.ts',import.meta.url),'utf8')
  code=code.replace(/import \{ api, MODEL_BOUND_TIMEOUT \} from .*api.*\r?\n/,'const {api,MODEL_BOUND_TIMEOUT}=globalThis.__matchingMock\n')
    .replace(/import \{ useEnvStore \} from .*environmentStore.*\r?\n/,'const useEnvStore=()=>({})\n')
    .replace('setInterval(poll, 1000)','globalThis.__matchingMock.setInterval(poll, 1000)')
    .replace('clearInterval(timer)','globalThis.__matchingMock.clearInterval(timer)')
  return (await moduleFrom(code,files)).aasService
}
const settle=async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve()}
function cleanup(files) {files.forEach(f=>unlinkSync(f));delete globalThis.__matchingMock}

test('Batch matching displays phases and no fictitious percent or property counter',async()=>{
  const files=[]
  try {
    const C=await component(files)
    const html=await renderToString(createSSRApp({render:()=>h(C,{progress:{status:'running',percent:55,stage:'Embedding',detail:'Batch query embeddings',properties_completed:8,properties_total:15}})}))
    assert.doesNotMatch(html,/55%|8 \/ 15|comparisons processed/)
    assert.match(html,/Retrieve candidates/)
    assert.match(html,/aria-current="step"/)
    assert.doesNotMatch(html.match(/<progress[^>]*>/)[0],/value=/)
    const unknown=await renderToString(createSSRApp({render:()=>h(C,{progress:{status:'running',percent:null,stage:'Preparing'}})}))
    const tag=unknown.match(/<progress[^>]*>/)[0]
    assert.doesNotMatch(tag,/value=/)
  } finally {cleanup(files)}
})

test('Polling does not overlap and a late response cannot overwrite completed state',async()=>{
  const files=[],updates=[]
  let tick,finishPost,finishGet,gets=0,cleared=false
  const mock={MODEL_BOUND_TIMEOUT:1200000,
    setInterval(fn){tick=fn;return 1},clearInterval(){cleared=true},
    api:{post:()=>new Promise(resolve=>{finishPost=resolve}),get:()=>{gets++;return new Promise(resolve=>{finishGet=resolve})}}}
  try {
    const s=await service(mock,files)
    const run=s.runMatch('battery.pdf','Battery',undefined,p=>updates.push(p))
    tick();tick();assert.equal(gets,1)
    finishPost({data:{success:true,progress:{status:'completed',percent:100}}});await run
    assert.equal(cleared,true);assert.deepEqual(updates.map(p=>p.percent),[100])
    finishGet({data:{status:'running',percent:20}});await settle()
    assert.deepEqual(updates.map(p=>p.percent),[100])
    await tick();assert.equal(gets,1)
  } finally {cleanup(files)}
})

test('Matching failure stops polling; a progress read failure does not cancel matching',async()=>{
  const files=[]
  let tick,failPost,cleared=false
  const mock={MODEL_BOUND_TIMEOUT:1200000,
    setInterval(fn){tick=fn;return 1},clearInterval(){cleared=true},
    api:{post:()=>new Promise((_,reject)=>{failPost=reject}),get:async()=>{throw new Error('temporary progress failure')}}}
  try {
    const s=await service(mock,files)
    const run=s.runMatch('battery.pdf','Battery',undefined,()=>{})
    await tick();assert.equal(cleared,false)
    failPost(new Error('matching failed'))
    await assert.rejects(run,/matching failed/);assert.equal(cleared,true)
  } finally {cleanup(files)}
})
