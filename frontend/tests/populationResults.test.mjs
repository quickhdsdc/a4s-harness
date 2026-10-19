import {workspaceDirectory, workspaceModule} from './workspace.mjs'
import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync,writeFileSync,mkdirSync,unlinkSync} from 'node:fs'
import {transform} from 'esbuild'
import {parse,compileScript} from '@vue/compiler-sfc'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {populationTranscript} from '../src/services/populationPresentation.mjs'

const directory=workspaceDirectory('population-tests')
mkdirSync(directory,{recursive:true})
let sequence=0
async function render(result, populationError = null) {
  const {descriptor}=parse(readFileSync(new URL('../src/components/GenerationStage.vue',import.meta.url),'utf8'))
  let code=compileScript(descriptor,{id:'population-test',inlineTemplate:true,genDefaultAs:'__component'}).content
  code=code.replace(/import \{ useEnvStore \} from [^\n]+/, 'const useEnvStore=()=>({})')
    .replace(/import \{ aasService \} from [^\n]+/, 'const aasService={}')
    .replace(/import \{ ApiError \} from [^\n]+/, 'class ApiError extends Error {}')
    .replace("@/services/populationPresentation.mjs",new URL('../src/services/populationPresentation.mjs',import.meta.url).href)
  const compiled=await transform(code+'\nexport default __component',{loader:'ts',format:'esm'})
  const path=new URL(`result-${++sequence}.mjs`,directory)
  writeFileSync(path,workspaceModule(compiled.code))
  try {
    const C=(await import(path.href)).default
    return await renderToString(createSSRApp({render:()=>h(C,{data:{targetAAS:'Battery',generationComplete:true,populationResult:result,populationError}})}))
  } finally {unlinkSync(path)}
}

test('60 of 61 writes shows a compact summary; detailed 404 stays in chat',async()=>{
  const result={counts:{applied:60,failed:1,notAttempted:0,total:61},failed:[{path:'Lifetime.ExpectedLifetime',error:'HTTP 404'}]}
  const html=await render(result)
  assert.match(html,/partially completed/)
  assert.match(html,/Values applied: 60 \/ 61/)
  assert.match(html,/See chat for failure details/)
  assert.doesNotMatch(html,/Lifetime.ExpectedLifetime|HTTP 404/)
  assert.doesNotMatch(html,/Template:|Submodel ID:|ID Short:|61 properties|populated successfully/)
  assert.match(populationTranscript(result,'Battery'),/60 of 61.*1 failed/)
  assert.match(populationTranscript(result,'Battery'),/Lifetime.ExpectedLifetime.*HTTP 404/)
})

test('request errors do not expose raw HTTP diagnostics in the left panel',async()=>{
  const html=await render(null,'AasHttpError: HTTP 404 on http://localhost:8081/submodels/long-id')
  assert.match(html,/See chat for details/)
  assert.doesNotMatch(html,/AasHttpError|localhost|HTTP 404/)
})

test('old completion flag cannot claim success without actual write results',async()=>{
  const html=await render(null)
  assert.match(html,/Verified write counts are unavailable/)
  assert.doesNotMatch(html,/populated successfully|Values applied:/)
})

test('all skipped decisions display no populated values',async()=>{
  const html=await render({counts:{applied:0,failed:0,notAttempted:61,total:61},failed:[]})
  assert.match(html,/No values were populated/)
  assert.match(html,/Not attempted: 61/)
})
