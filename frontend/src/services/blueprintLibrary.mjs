// Presentation aliases preserve existing floor types. Repository identities
// always come from discovery, including blueprints unknown to this UI.
const presentation = {
  machiningcenter: ['machine', 'CNC Machine', 'machine.png'],
  metal3dprinter: ['metal_printer', 'Metal 3D Printer', 'printer.png'],
  injectionmoldingmachine: ['injection_molding', 'Injection Molding Machine', 'injection molding.png'],
  roboticdisassemblystation: ['disassembly_robot', 'Robotic Disassembly Station', 'robot.png'],
  agv: ['agv', 'AGV', 'agv.png'],
  productionorder: ['order', 'Production Order', 'order.png'],
  digitalbatterypassport: ['product', 'Digital Battery Passport', 'product.png'],
  process: ['process', 'Process', 'process.png'],
  provisionofsimulationmodelsaas: ['simulation', 'Simulation', 'simulation.png'],
  aps: ['aps', 'APS', 'aps.png'],
  assemblyshop: ['assemblyshop', 'Assembly Shop', 'assembly.png'],
  testingrepairstation: ['testing_repair', 'Testing & Repair Station', 'repair.png'],
  festoworkcenterstamping: ['festo_cp_lab', 'FestoWorkCenterStamping', 'festo cp lab.png'],
}

export function blueprintCards(rows) {
  return rows.map(row => {
    const key = row.idShort.toLowerCase().replace(/[^a-z0-9]/g, '')
    const [type, label, icon] = presentation[key] || [`blueprint:${row.id}`, row.idShort, 'machine.png']
    return {type, label, icon: `/assets/${icon}`, idShort: row.idShort,
      blueprintId: row.id, blueprintEndpoint: row.endpoint}
  })
}
