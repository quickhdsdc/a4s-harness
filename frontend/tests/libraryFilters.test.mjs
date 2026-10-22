import {test} from 'node:test'
import assert from 'node:assert/strict'
import {filterTemplates, reconcileTemplateSelection} from '../src/services/templateFilter.mjs'
import {blueprintCards} from '../src/services/blueprintLibrary.mjs'

test('template keywords cover names, descriptions and version without changing selections', () => {
  const templates = [
    {id:'urn:nameplate', name:'DigitalNameplate', version:'3', revision:'0'},
    {id:'urn:technical', name:'TechnicalData_IMM', description:'Clamping pressure specifications', version:'1', revision:'2'},
  ]
  const selected = ['urn:nameplate']
  assert.deepEqual(filterTemplates(templates,'digital nameplate').map(row=>row.id), selected)
  assert.equal(filterTemplates(templates,'CLAMPING pressure')[0].id, 'urn:technical')
  assert.equal(filterTemplates(templates,'3.0')[0].id, 'urn:nameplate')
  assert.equal(filterTemplates(templates,'technical_data')[0].id, 'urn:technical')
  assert.equal(filterTemplates(templates,'manufacturer')[0].id, 'urn:nameplate')
  assert.deepEqual(filterTemplates(templates,'does-not-exist'), [])
  assert.deepEqual(filterTemplates(templates,'  '), templates)
  assert.deepEqual(selected, ['urn:nameplate'])
})

test('known and unknown blueprints carry discovered identities, never a fixed repository namespace', () => {
  const rows = [{id:'urn:publisher:new-cnc-id', idShort:'MachiningCenter', endpoint:'http://library'},
    {id:'https://vendor.example/custom/lathe', idShort:'NewLathe', endpoint:'http://library'}]
  const cards = blueprintCards(rows)
  assert.equal(cards[0].type, 'machine')
  assert.equal(cards[0].blueprintId, rows[0].id)
  assert.equal(cards[1].blueprintId, rows[1].id)
  assert.equal(cards[1].label, 'NewLathe')
  assert.ok(cards.every(card=>card.blueprintEndpoint==='http://library'))
  const replacement = blueprintCards([{...rows[0],id:'urn:another-publisher:replacement'}])
  assert.equal(replacement[0].blueprintId, 'urn:another-publisher:replacement')
})

test('catalog refresh clears stale persisted IDs and preserves current choices regardless of search filters', () => {
  const current = [{id:'urn:new:nameplate'}, {id:'urn:technical'}]
  const selected = ['urn:old:nameplate', 'urn:technical']
  assert.deepEqual(reconcileTemplateSelection(current, selected), ['urn:technical'])
  assert.deepEqual(selected, ['urn:old:nameplate', 'urn:technical'])
  assert.deepEqual(reconcileTemplateSelection(current, 'urn:technical'), ['urn:technical'])
  assert.deepEqual(reconcileTemplateSelection(current, []), [])
  assert.deepEqual(reconcileTemplateSelection([], selected), [])
})
