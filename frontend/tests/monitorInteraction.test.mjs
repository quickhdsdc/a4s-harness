import {workspaceDirectory, workspaceModule} from './workspace.mjs'
import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync, writeFileSync, mkdirSync, unlinkSync} from 'node:fs'
import {parse, compileScript} from '@vue/compiler-sfc'
import {transform} from 'esbuild'
import {createRenderer, h, ref, nextTick} from 'vue'

const renderer = createRenderer({
  createElement: tag => ({tag, tagName:tag.toUpperCase(), props:{}, children:[],
    addEventListener(){}, removeEventListener(){}, get options(){return this.children},
    getAttribute(key){return this.props[key]}, dispatchEvent(){}}),
  createText: text => ({text, children:[]}), createComment: text => ({comment:text, children:[]}),
  setText: (node,text) => { node.text = text }, setElementText: (node,text) => { node.text = text; node.children = [] },
  patchProp: (node,key,old,value) => { node.props[key] = value; if (key === 'value') node.value = value },
  insert(node,parent,anchor) {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node),1)
    const index = parent.children.indexOf(anchor)
    parent.children.splice(index < 0 ? parent.children.length : index, 0, node); node.parent = parent
  },
  remove(node) { const index = node.parent?.children.indexOf(node); if (index >= 0) node.parent.children.splice(index,1) },
  parentNode: node => node.parent, nextSibling: node => node.parent?.children[node.parent.children.indexOf(node)+1],
})
const text = node => (node.text || '') + node.children.map(text).join('')
const find = (node, predicate) => [ ...(predicate(node) ? [node] : []), ...node.children.flatMap(child => find(child,predicate)) ]
const settle = async () => { for (let i=0;i<12;i++) { await new Promise(resolve => setImmediate(resolve)); await nextTick() } }

async function component(name, mocks, cleanup) {
  const filename = 'src/components/' + name + '.vue'
  const {descriptor} = parse(readFileSync(new URL('../' + filename, import.meta.url),'utf8'), {filename})
  let code = compileScript(descriptor, {id:name, inlineTemplate:true, genDefaultAs:'__component'}).content
  for (const [pattern, replacement] of [
    [/import \{\s*acceptDemoSession\s*\} from ['"]\.\.\/services\/demoSession['"]/g, 'const {acceptDemoSession} = globalThis.__monitorMocks'],
    [/import \{\s*api\s*\} from ['"]\.\.\/services\/api['"]/g, 'const {api} = globalThis.__monitorMocks'],
    [/import \{\s*useWizardStore\s*\} from ['"]\.\.\/stores\/wizardStore['"]/g, 'const {useWizardStore} = globalThis.__monitorMocks'],
    [/import \{\s*useEnvStore\s*\} from ['"]\.\.\/stores\/environmentStore['"]/g, 'const {useEnvStore} = globalThis.__monitorMocks'],
    [/import \{\s*useSharedWebSocket\s*\} from ['"]\.\.\/services\/websocketService['"]/g, 'const {useSharedWebSocket} = globalThis.__monitorMocks'],
    [/import ResetAgentButton from ['"]\.\/ResetAgentButton.vue['"]/g, 'const ResetAgentButton = {render: () => null}'],
    [/import LiveFaultMonitor from ['"]\.\/LiveFaultMonitor.vue['"]/g, 'const {LiveFaultMonitor} = globalThis.__monitorMocks'],
    [/import ProductionWorkspace from ['"]\.\/ProductionWorkspace.vue['"]/g, 'const ProductionWorkspace = {render: () => null}'],
  ]) code = code.replace(pattern, replacement)
  code = code.replaceAll("'../services/", "'../../src/services/")
  const result = await transform(code + '\nexport default __component', {loader:'ts', format:'esm'})
  const directory = workspaceDirectory('monitor-tests')
  mkdirSync(directory, {recursive:true})
  const file = new URL(name + '-' + Date.now() + '.mjs', directory)
  writeFileSync(file,workspaceModule(result.code)); cleanup.push(file)
    globalThis.__monitorMocks = mocks
  return (await import(file.href)).default
}

test('Process events request analysis only when active, fresh and the Agent is available', async () => {
  for (const variant of ['fresh','locked','stale','inactive','disconnected']) {
    const cleanup = [], writes = [], wizardData = {}
    const event = {id:'event-code7', seq:1, kind:'PROCESS_INTERVENTION_RAISED',
      episode_id:'process-episode', at:Date.now()/1000, claimed:false}
    const report = {running:true, stale:variant==='stale', events:[event],
      state:{stable:false, process_attention:true, communication:'GOOD',
        active_episode_ids:variant==='inactive'?[]:['process-episode']}}
    const mocks = {
      useWizardStore: () => ({wizardData,updateData:(key,value)=>{wizardData[key]=value}}),
      useSharedWebSocket: () => ({connectionStatus:ref(variant==='disconnected'?'disconnected':'connected')}),
      api:{
        async get(url) {assert.equal(url,'/api/festo/live-monitor'); return {data:report}},
        async post(url,body) {
          assert.equal(url,'/api/festo/live-monitor/claim'); writes.push(body)
          return {data:{request:'Maintenance investigation: operational anomaly detected.\nEvidence: {}'}}
        },
      },
    }
    let app
    try {
      const monitor = await component('LiveFaultMonitor',mocks,cleanup)
      const host = {children:[]}
      app=renderer.createApp({render:()=>h(monitor,{assetId:'urn:instance',endpoint:'http://aas',agentLocked:variant==='locked'})})
      app.component('HelpTip',{render:()=>null})
      app.mount(host); await settle()
      assert.equal(writes.length,variant==='fresh'?1:0,variant)
      if (variant==='fresh') {
        assert.match(text(host),/Needs attention/)
        assert.equal(writes[0].asset_id,'urn:instance')
        assert.equal(writes[0].event_id,'event-code7')
        assert.match(wizardData.pendingAgentQuestion,/operational anomaly detected/)
      } else assert.equal(wizardData.pendingAgentQuestion,undefined)
    } finally {
      app?.unmount(); cleanup.forEach(file=>unlinkSync(file)); delete globalThis.__monitorMocks
    }
  }
})

test('Reset Agent rotates chat/incident session, refuses a running task and reports failure', async () => {
  for (const variant of ['ready', 'locked', 'failed']) {
    const cleanup = [], calls = [], sessions = []
    const session = {id:'fresh-demo', started_at:1234}
    const mocks = {acceptDemoSession:data=>sessions.push(data), api:{async post(url, body) {
      calls.push({url,body})
      if (variant === 'failed') throw new Error('Stop the running Agent task first')
      return {data:{demo_session:session}}
    }}}
    let app
    try {
      const button = await component('ResetAgentButton', mocks, cleanup)
      const host = {children:[]}
      app = renderer.createApp({render:()=>h(button,{agentLocked:variant==='locked'})})
      app.mount(host); await settle()
      const control = find(host,node=>node.tag==='button')[0]
      assert.match(text(host),/Reset Agent/)
      assert.equal(Boolean(control.props.disabled),variant==='locked')
      await control.props.onClick(); await settle()
      assert.equal(calls.length,variant==='locked'?0:1)
      if (calls.length) assert.equal(calls[0].url,'/api/demo/festo/session/reset')
      assert.deepEqual(sessions,variant==='ready'?[session]:[])
      if (variant==='failed') assert.match(text(host),/Stop the running Agent task first/)
    } finally { app?.unmount(); cleanup.forEach(file=>unlinkSync(file)); delete globalThis.__monitorMocks }
  }
})

test('One source selector drives the dashboard and simulation uses the OPC monitor', async () => {
  globalThis.document = {activeElement:null}
  const cleanup = [], calls = []
  let running = false, fault = false, observedAt = 100
  const bindings = ['Press.Fault','Turning.Fault','Press.Ready','Turning.Ready','Press.Fault01','Press.PressureBar','Press.FlowLMin','Safety.EmergencyStop'].map(path => ({path, node:'ns=2;s='+path, tag:'SIMULATED.'+path, value:path === 'Press.PressureBar' ? 6 : false}))
  const state = {asset:{id:'urn:festo:demo',idShort:'FestoWorkCenterStamping_99'}, issues:[], maintenance:{submodelElements:[]}, context:{}, line:{id:1}, order:{id:1}, mes_ready:true}
  const nodes = () => bindings.map(row => ({...row, value:row.path === 'Press.PressureBar' ? fault ? 3.8 : 6 : row.path === 'Press.Fault' ? fault : row.value}))
  const report = source => ({source, target:{source}, running, stale:!running, events:[], state:{communication:'GOOD', latest: running ? {observed_at:++observedAt, values:nodes().map(row => ({...row,status:'Good'}))} : null}})
  const mocks = {
    useWizardStore: () => ({wizardData:{},updateData:()=>{}}),
    useEnvStore: () => ({aasUiUrl:'http://aas',backendUrl:'http://backend'}),
    useSharedWebSocket: () => ({connectionStatus:ref('disconnected')}),
    api:{
      async get(url, options) {
        calls.push(url)
        if (url.endsWith('/asset')) return {data:{asset:state.asset,endpoint:'http://aas'}}
        if (url.endsWith('/simulator')) return {data:{running:true,mode:fault?'fault':'normal',nodes:nodes()}}
        if (url.endsWith('/live-monitor')) return {data:report(options.params.source)}
        if (url.endsWith('/audit')) return {data:{events:[]}}
        if (url.endsWith('/documents')) return {data:{documents:[]}}
        if (url.endsWith('/latest')) return {data:{run:null}}
        if (url === '/api/demo/festo') return {data:state}
        throw Error('Unexpected request ' + url)
      },
      async post(url, body) {
        calls.push(url)
        if (url.endsWith('/simulator/state')) {fault=body.mode === 'fault'; return {data:{running:true,mode:body.mode,nodes:nodes()}}}
        if (url.endsWith('/start')) {running=true; return {data:report(body.source)}}
        if (url.endsWith('/stop')) {running=false; return {data:report(body.source)}}
        throw Error('Unexpected write ' + url)
      },
    },
  }
  let app
  try {
    mocks.LiveFaultMonitor = await component('LiveFaultMonitor', mocks, cleanup)
    const workspace = await component('RecoveryWorkspace', mocks, cleanup)
    const host = {children:[]}
    app = renderer.createApp({render:()=>h(workspace, {assetId:state.asset.id,endpoint:'http://aas'})})
    app.component('HelpTip', {render:()=>null}); app.mount(host)
    await settle()
    const selectors = find(host, node => node.tag === 'select')
    assert.equal(selectors.length,1)
    const select = selectors[0]
    select.props['onUpdate:modelValue']('simulator'); select.props.onChange()
    await settle()
    assert.match(text(host), /AIR PRESSURE · SIM/)
    assert.equal(find(host, node => node.tag === 'tr' && text(node).includes('Not read')).length,8)
    assert.doesNotMatch(text(host), /Start server|Inject air leak|Restore simulated pressure|SIM · HTTP STREAM/)
    const start = find(host, node => node.tag === 'button' && text(node) === 'Start monitoring')[0]
    await start.props.onClick(); await settle()
    assert.equal(select.props.disabled, true)
    assert.match(text(host), /6bar/)
    const faultButton = find(host, node => node.tag === 'button' && text(node) === 'Fault / leak')[0]
    await faultButton.props.onClick(); await settle()
    assert.match(text(host), /6bar/, 'Commands must wait for OPC read-back')
    await new Promise(resolve => setTimeout(resolve,3100)); await settle()
    assert.match(text(host), /3.8bar/)
    const stop = find(host, node => node.tag === 'button' && text(node) === 'Stop')[0]
    await stop.props.onClick(); await settle()
    select.props['onUpdate:modelValue']('live'); select.props.onChange(); await settle()
    assert.match(text(host), /PRESSURE 1 · RAW OPC/)
    assert.doesNotMatch(text(host), /AIR PRESSURE · SIM|3.8bar|6bar/)
    assert.ok(calls.includes('/api/festo/live-monitor/start'))
    assert.ok(calls.every(url => !url.includes('/api/demo/festo/monitor') && url !== '/api/opc/read'))
  } finally {
    app?.unmount()
    cleanup.forEach(file => unlinkSync(file))
    delete globalThis.__monitorMocks
    delete globalThis.document
  }
})


test('Pneumatic suspicion hands off even when PLC alarms are unavailable', async () => {
  const cleanup=[], writes=[], wizardData={}
  const event={id:'pneumatic',seq:1,kind:'LEAK_SUSPECTED',episode_id:'leak',at:Date.now()/1000,claimed:false}
  const report={running:true,stale:false,events:[event],state:{communication:'UNKNOWN',
    active_episode_ids:['leak'],press_leak:{stable:true,communication:'GOOD',episode_id:'leak',phase:'suspected',config:{}}}}
  const mocks={useWizardStore:()=>({wizardData,updateData:(key,value)=>{wizardData[key]=value}}),
    useSharedWebSocket:()=>({connectionStatus:ref('connected')}),api:{
      async get(){return {data:report}},
      async post(url,body){writes.push({url,body});return {data:{request:'Assess pneumatic trend'}}},
    }}
  let app
  try {
    const monitor=await component('LiveFaultMonitor',mocks,cleanup)
    const host={children:[]};app=renderer.createApp({render:()=>h(monitor,{assetId:'urn:press',endpoint:'http://aas'})})
    app.component('HelpTip',{render:()=>null});app.mount(host);await settle()
    assert.equal(writes.length,1)
    assert.equal(writes[0].url,'/api/festo/live-monitor/claim')
    assert.equal(writes[0].body.event_id,'pneumatic')
    assert.equal(wizardData.pendingAgentQuestion,'Assess pneumatic trend')
    assert.match(text(host),/abnormal airflow/)
  } finally {app?.unmount();cleanup.forEach(file=>unlinkSync(file));delete globalThis.__monitorMocks}
})
