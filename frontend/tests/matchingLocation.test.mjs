import {test} from 'node:test'
import assert from 'node:assert/strict'
import {matchingLocations,targetIdentity} from '../src/services/matchingLocation.mjs'

test('new SME displays its host collection, including nested ancestors', () => {
  const [location] = matchingLocations({action:'create', aasProperty:'Cooling_system',
    apiPath:'TechnicalProperties.General', semanticPath:'TechnicalData/TechnicalProperties.General',
    targetType:'SubmodelElementCollection'})
  assert.equal(location.label, 'TechnicalData → TechnicalProperties → General')
  assert.equal(location.create, true)
})

test('existing SME displays the containing branch instead of treating the leaf as a parent', () => {
  const [location] = matchingLocations({action:'write', apiPath:'Electrical.NominalVoltage',
    semanticPath:'BatteryPerformance/Electrical.NominalVoltage'})
  assert.equal(location.label, 'BatteryPerformance → Electrical')
  assert.equal(location.create, false)
})

test('root-level existing SME belongs directly to its SM', () => {
  assert.equal(matchingLocations({action:'write', apiPath:'ManufacturerName',
    submodelIdShort:'Nameplate'})[0].label, 'Nameplate')
})

test('manual repicking updates the parent and SM for each selected destination', () => {
  const locations = matchingLocations({action:'create', submodelIdShort:'OldSM', apiPath:'OldHost',
    aasProperties:[{type:'Property', apiPath:'Electrical.Voltage', semanticPath:'Performance/Electrical.Voltage'},
      {type:'SubmodelElementCollection', apiPath:'General', semanticPath:'TechnicalData/General'}]})
  assert.deepEqual(locations.map(x => [x.label,x.create]), [['Performance → Electrical',false], ['TechnicalData → General',true]])
})

test('legacy rows retain a full URI submodel label and list position', () => {
  assert.equal(matchingLocations({action:'create', apiPath:'Groups[0].Items',
    semanticPath:'https://example.org/sm/Groups[0].Items'})[0].label,
    'https://example.org/sm → Groups[0] → Items')
})

test('same idShort and path in different SMs remain separate selection targets', () => {
  assert.notEqual(targetIdentity({submodelId:'urn:one',apiPath:'General.Voltage',idShort:'Voltage'}),
                  targetIdentity({submodelId:'urn:two',apiPath:'General.Voltage',idShort:'Voltage'}))
})

test('manually selected submodel creates at its root and keeps canonical identity', () => {
  const root = {idShort:'TechnicalData',type:'Submodel',apiPath:'',semanticPath:'TechnicalData/',submodelId:'urn:chosen',submodelIdShort:'TechnicalData'}
  const [location] = matchingLocations({action:'write',apiPath:'Old.Path',submodelIdShort:'Old',aasProperties:[root]})
  assert.equal(location.label, 'TechnicalData')
  assert.equal(location.create, true)
  assert.equal(location.parent, '')
  assert.equal(location.path, '')
  assert.equal(targetIdentity(root), 'urn:chosen::')
  assert.notEqual(targetIdentity(root), targetIdentity({...root,submodelId:'urn:other'}))
})
