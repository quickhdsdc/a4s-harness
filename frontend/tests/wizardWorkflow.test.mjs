import {workspaceDirectory, workspaceModule} from './workspace.mjs'
import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync, writeFileSync, mkdirSync, unlinkSync} from 'node:fs'
import {transform} from 'esbuild'
import {parse, compileScript} from '@vue/compiler-sfc'
import {createPinia, setActivePinia, disposePinia} from 'pinia'
import {createPersistedState} from 'pinia-plugin-persistedstate'
import {nextTick, createRenderer, h, ref} from 'vue'

const directory = workspaceDirectory('wizard-tests')
mkdirSync(directory, {recursive:true})
let sequence = 0
async function moduleFrom(code, cleanup) {
  const result = await transform(code, {loader:'ts', format:'esm'})
  const file = new URL(`workflow-${++sequence}.mjs`, directory)
  writeFileSync(file,workspaceModule(result.code)); cleanup.push(file)
  return await import(file.href)
}
async function storeFor(mocks, cleanup, storage) {
  globalThis.__wizardMocks = mocks
  let code = readFileSync(new URL('../src/stores/wizardStore.ts', import.meta.url), 'utf8')
  code = code.replace(/import \{ useEnvStore \} from .*environmentStore.*\r?\n/, 'const {useEnvStore} = globalThis.__wizardMocks\n')
    .replace(/import \{ api \} from .*services\/api.*\r?\n/, 'const {api} = globalThis.__wizardMocks\n')
    .replace(/import \{ useSharedWebSocket \} from .*websocketService.*\r?\n/, 'const {useSharedWebSocket} = globalThis.__wizardMocks\n')
  const pinia = createPinia(); setActivePinia(pinia)
  if (storage) {
    pinia.use(createPersistedState({storage}))
    renderer.createApp({render:()=>null}).use(pinia)
  }
  const {useWizardStore} = await moduleFrom(code, cleanup)
  return {store:useWizardStore(), pinia}
}
function mocksFor(post = async () => ({data:{success:true}})) {
  return {
    api:{post},
    useEnvStore:() => ({aasServerUrl:'http://aas', aasUiUrl:'http://viewer'}),
    useSharedWebSocket:() => ({sendStateUpdate(){}, onMessage(){}}),
  }
}
async function completed(store) {
  Object.assign(store.wizardData, {viewMode:'wizard', mode:'edit', targetAAS:'EV84',
    dataSourceType:'pdf', uploadedFiles:[{name:'battery.pdf'}], dataSourceValue:'/uploads/battery.pdf'})
  await nextTick()
  store.setStep(1)
  store.updateData('extractedEntities', [{entity:'Rated capacity', value:84}])
  store.setStep(2)
  store.updateData('matchedProperties', [{extractedEntity:'Rated capacity', aasProperty:'Capacity'}])
  store.setStep(3)
  store.updateData('generationComplete', true)
  await nextTick()
}
function clean(pinia, files) {
  disposePinia(pinia); files.forEach(file => unlinkSync(file)); delete globalThis.__wizardMocks
}

test('Executed stages can be revisited in any order without rerunning work', async () => {
  const files = [], requests = []
  const {store, pinia} = await storeFor(mocksFor(async (...args) => {requests.push(args)}), files)
  try {
    assert.equal(store.canVisitStep(3), false)
    await completed(store)
    const entities = store.wizardData.extractedEntities, matches = store.wizardData.matchedProperties
    for (const step of [0,2,1,3,0,3]) {
      assert.equal(store.canVisitStep(step), true)
      store.setStep(step); await nextTick()
      assert.equal(store.currentStep, step)
      assert.equal(store.highestVisitedStep, 3)
      assert.equal(store.wizardData.extractedEntities, entities)
      assert.equal(store.wizardData.matchedProperties, matches)
      assert.equal(store.wizardData.generationComplete, true)
    }
    assert.deepEqual(requests, [])
  } finally { clean(pinia, files) }
})

test('Reset clears results and navigation after server cleanup, preserving floor context', async () => {
  const files = [], requests = []
  let finish
  const {store, pinia} = await storeFor(mocksFor((...args) => {
    requests.push(args); return new Promise(resolve => {finish = resolve})
  }), files)
  try {
    await completed(store)
    store.wizardData.assets = [{id:'asset'}]; store.wizardData.connections = [{id:'connection'}]
    store.wizardData.pendingAgentQuestion = 'old instruction'
    const reset = store.resetWorkflow('battery.pdf')
    assert.equal(store.workflowBusy, true)
    assert.equal(store.currentStep, 3)
    finish({data:{success:true}}); await reset; await nextTick()
    assert.deepEqual(requests, [['/api/wizard/reset', {filename:'battery.pdf', uploads:['battery.pdf'], aas_id_short:'EV84'}]])
    assert.equal(store.currentStep, 0); assert.equal(store.highestVisitedStep, 0)
    assert.equal(store.wizardData.viewMode, 'wizard')
    assert.equal(store.wizardData.targetAAS, '')
    assert.deepEqual(store.wizardData.uploadedFiles, [])
    assert.deepEqual(store.wizardData.extractedEntities, [])
    assert.deepEqual(store.wizardData.matchedProperties, [])
    assert.equal(store.wizardData.generationComplete, false)
    assert.equal(store.wizardData.pendingAgentQuestion, '')
    assert.equal(store.canVisitStep(3), false); assert.equal(store.workflowBusy, false)
    assert.deepEqual(store.wizardData.assets, [{id:'asset'}])
    assert.deepEqual(store.wizardData.connections, [{id:'connection'}])
  } finally { clean(pinia, files) }
})

test('Failed reset preserves results; active stages refuse reset', async () => {
  const files = [], requests = []
  const {store, pinia} = await storeFor(mocksFor(async (...args) => {requests.push(args); throw new Error('Server busy')}), files)
  try {
    await completed(store)
    await assert.rejects(store.resetWorkflow('battery.pdf'), /Server busy/)
    assert.equal(store.currentStep, 3); assert.equal(store.wizardData.matchedProperties.length, 1)
    assert.equal(store.workflowBusy, false)
    store.wizardData.isMatching = true
    await assert.rejects(store.resetWorkflow('battery.pdf'), /Wait for the current stage/)
    assert.equal(requests.length, 1)
  } finally { clean(pinia, files) }
})

test('Changing attachment or target invalidates executed stages', async () => {
  const files = []
  const {store, pinia} = await storeFor(mocksFor(), files)
  try {
    for (const [key, value] of [['targetAAS','Other'], ['uploadedFiles',[{name:'battery.pdf',serverName:'battery_new-content.pdf'}]]]) {
      await completed(store)
      store.wizardData.extractionWarnings = ['Previous warning']
      store.wizardData.extractionConfigurations = ['Previous configuration']
      store.wizardData.chosenConfiguration = 'Previous configuration'
      store.updateData(key, value); await nextTick()
      assert.equal(store.currentStep, 0)
      assert.equal(store.highestVisitedStep, 0)
      assert.equal(store.canVisitStep(3), false)
      assert.deepEqual(store.wizardData.extractedEntities, [])
      assert.deepEqual(store.wizardData.matchedProperties, [])
      assert.deepEqual(store.wizardData.extractionWarnings, [])
      assert.deepEqual(store.wizardData.extractionConfigurations, [])
      assert.equal(store.wizardData.chosenConfiguration, '')
    }
  } finally { clean(pinia, files) }
})

const renderer = createRenderer({
  createElement:tag => ({tag,props:{},children:[],clientWidth:1000}),
  createText:text => ({text,children:[]}), createComment:text => ({comment:text,children:[]}),
  setText:(node,text) => {node.text=text}, setElementText:(node,text) => {node.text=text;node.children=[]},
  patchProp:(node,key,old,value) => {node.props[key]=value},
  insert(node,parent,anchor) {
    if(node.parent) node.parent.children.splice(node.parent.children.indexOf(node),1)
    const index=parent.children.indexOf(anchor)
    parent.children.splice(index<0?parent.children.length:index,0,node);node.parent=parent
  },
  remove(node){const index=node.parent?.children.indexOf(node);if(index>=0)node.parent.children.splice(index,1)},
  parentNode:node=>node.parent, nextSibling:node=>node.parent?.children[node.parent.children.indexOf(node)+1],
})
const text = node => (node.text || '') + node.children.map(text).join('')
const find = (node, predicate) => [...(predicate(node)?[node]:[]),...node.children.flatMap(child=>find(child,predicate))]
const settle = async () => {for(let i=0;i<5;i++){await new Promise(resolve=>setImmediate(resolve));await nextTick()}}

test('Wizard header Reset and stepper navigate retained results and return to Input', async () => {
  const files=[], requests=[]
  const mocks=mocksFor(async (...args)=>{requests.push(args);return {data:{success:true}}})
  const {store,pinia}=await storeFor(mocks,files)
  let app
  const previousWindow=globalThis.window, previousObserver=globalThis.ResizeObserver
  try {
    await completed(store)
    globalThis.window={innerWidth:1200}
    globalThis.ResizeObserver=class {observe(){} disconnect(){}}
    const filename='App.vue'
    const {descriptor}=parse(readFileSync(new URL('../src/App.vue',import.meta.url),'utf8'),{filename})
    let code=compileScript(descriptor,{id:'wizard-app',inlineTemplate:true,genDefaultAs:'__component'}).content
    code=code.replace(/import (\w+) from ['"]\.\/components\/[^'"\n]+['"]/g, 'const $1 = {render:()=>null}')
      .replace(/import \{ useEnvStore \} from .*environmentStore.*\r?\n/, 'const {useEnvStore} = globalThis.__wizardMocks\n')
      .replace(/import \{ useWizardStore \} from .*wizardStore.*\r?\n/, 'const useWizardStore = () => globalThis.__wizardMocks.store\n')
      .replace(/import \{ aasService \} from .*aasService.*\r?\n/, 'const aasService = globalThis.__wizardMocks.aasService\n')
      .replace(/import \{instanceUpdates\} from .*instanceUpdates.*\r?\n/, 'const instanceUpdates = {}\n')
      .replace(/import \{ api, ApiError \} from .*services\/api.*\r?\n/, 'const {api, ApiError} = globalThis.__wizardMocks\n')
      .replace(/import \{demoSession, refreshDemoSession\} from .*demoSession.*\r?\n/, 'const {demoSession, refreshDemoSession} = globalThis.__wizardMocks\n')
      .replace('@/services/populationPresentation.mjs', new URL('../src/services/populationPresentation.mjs', import.meta.url).href)
    Object.assign(mocks,{store,aasService:new Proxy({}, {get(){return ()=>{throw new Error('Navigation must not run pipeline')}}}),
      api:{post:mocks.api.post,get:async()=>({data:{mes_url:null}})},ApiError:Error,
      demoSession:ref(null),refreshDemoSession:async()=>{}})
    const component=(await moduleFrom(code+'\nexport default __component',files)).default
    const host={children:[]}
    app=renderer.createApp({render:()=>h(component)});app.use(pinia);app.mount(host);await settle()
    find(host,node=>node.tag==='button' && text(node)==='Shop floor & AAS')[0].props.onClick()
    await settle()
    const step=index=>find(host,node=>node.props?.role==='button')[index]
    step(0).props.onClick();await settle();assert.equal(store.currentStep,0)
    step(3).props.onClick();await settle();assert.equal(store.currentStep,3)
    assert.equal(requests.length,0)
    step(2).props.onClick();await settle()
    find(host,node=>node.tag==='button' && text(node)==='Next '+String.fromCharCode(0x2192))[0].props.onClick()
    await settle();assert.equal(store.currentStep,3);assert.equal(requests.length,0)
    const reset=find(host,node=>node.tag==='button' && text(node)==='Reset')[0]
    await reset.props.onClick();await settle()
    assert.equal(store.currentStep,0);assert.equal(requests.length,1)
    assert.equal(step(3).props['aria-disabled'],true)
    step(3).props.onClick();await settle();assert.equal(store.currentStep,0)
  } finally {
    app?.unmount(); clean(pinia,files)
    globalThis.window=previousWindow;globalThis.ResizeObserver=previousObserver
  }
})


test('Reload restores completed stages; a reset remains reset after reload', async () => {
  const files=[], data=new Map()
  const storage={getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value)}
  let pinia
  try {
    let loaded=await storeFor(mocksFor(),files,storage);pinia=loaded.pinia
    await completed(loaded.store);await nextTick()
    disposePinia(pinia)
    loaded=await storeFor(mocksFor(),files,storage);pinia=loaded.pinia
    await new Promise(resolve=>setTimeout(resolve,10));await nextTick()
    assert.equal(loaded.store.currentStep,3)
    assert.equal(loaded.store.highestVisitedStep,3)
    assert.equal(loaded.store.wizardData.extractedEntities.length,1)
    assert.equal(loaded.store.wizardData.matchedProperties.length,1)
    assert.equal(loaded.store.wizardData.generationComplete,true)
    await loaded.store.resetWorkflow('battery.pdf');await nextTick()
    disposePinia(pinia)
    loaded=await storeFor(mocksFor(),files,storage);pinia=loaded.pinia
    await new Promise(resolve=>setTimeout(resolve,10));await nextTick()
    assert.equal(loaded.store.currentStep,0)
    assert.equal(loaded.store.canVisitStep(3),false)
    assert.deepEqual(loaded.store.wizardData.extractedEntities,[])
  } finally {if(pinia)clean(pinia,files)}
})
