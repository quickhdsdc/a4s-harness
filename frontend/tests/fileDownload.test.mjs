import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync, writeFileSync, mkdirSync, unlinkSync} from 'node:fs'
import {transform} from 'esbuild'

let sequence = 0
async function clientModule() {
  const directory = new URL('../../work/temp/frontend/file-download/', import.meta.url)
  mkdirSync(directory, {recursive:true})
  const source = readFileSync(new URL('../src/services/api.ts', import.meta.url), 'utf8')
    .replace(/import \{ useEnvStore \} from [^\n]+/, "const useEnvStore=()=>({backendUrl:'http://api.example'})")
  const file = new URL(`client-${++sequence}.mjs`, directory)
  writeFileSync(file, (await transform(source, {loader:'ts',format:'esm'})).code)
  try { return await import(file.href) } finally { unlinkSync(file) }
}

test('JSON downloads return Blob while normal JSON requests still return objects', async () => {
  const previous = globalThis.fetch
  globalThis.fetch = async () => new Response('{"assetAdministrationShells":[]}', {headers:{'Content-Type':'application/json'}})
  try {
    const {api} = await clientModule()
    const blob = await api.downloadFile('/api/download/json/Device')
    assert.ok(blob instanceof Blob)
    assert.match(await blob.text(), /assetAdministrationShells/)
    assert.deepEqual((await api.get('/api/data')).data, {assetAdministrationShells:[]})
  } finally { globalThis.fetch = previous }
})

test('failed downloads preserve the backend JSON error explanation', async () => {
  const previous = globalThis.fetch
  globalThis.fetch = async () => new Response('{"detail":"Target instance not found"}', {status:404,headers:{'Content-Type':'application/json'}})
  try {
    const {api} = await clientModule()
    await assert.rejects(api.downloadFile('/api/download/json/Device'), /Target instance not found/)
  } finally { globalThis.fetch = previous }
})
