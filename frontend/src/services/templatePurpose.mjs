// Concise UI copy; template definitions and identifiers remain unchanged.
const purposes = {
  digitalnameplate: 'Identifies the product, manufacturer, model and serial number.',
  nameplate: 'Identifies the product, manufacturer, model and serial number.',
  technicaldata: "Stores the product's technical specifications, ratings and operating limits.",
  technicaldataagv: 'Describes the vehicle dimensions, payload, drive and operating limits.',
  kinematicmodel: 'Describes the moving parts, joints and motion relationships of a machine.',
  circularity: 'Describes resource use, reuse, recycling and end-of-life handling.',
  carbonfootprint: 'Records greenhouse gas emissions and the scope of their calculation.',
  materialcomposition: 'Lists the materials and substances in a product and their proportions.',
  productcondition: 'Describes the current condition, wear and remaining service life of a product.',
  relationship: 'Links a product to related assets, components and lifecycle records.',
  capability: 'Describes the functions a machine can perform and their operating constraints.',
  operationsstatus: 'Describes the operating state and availability of an asset.',
  printrecords: 'Records printing jobs, process results and traceability information.',
  processsegment: 'Describes a production step, its required resources and process parameters.',
  productionordermes: 'Links production orders to MES scheduling and execution information.',
  simulationmodels: 'References simulation models and describes their parameters and interfaces.',
  uaserverdatasheet: 'Describes an OPC UA server, its connection details and exposed data.',
  servicesdelegated: 'Lists services exposed by the asset and how to invoke them.',
  contactinformation: 'Provides contact details for manufacturers, suppliers and service teams.',
  documentation: 'References technical documents, operating instructions and maintenance manuals.',
  timeseries: 'Organizes timestamped measurements and other data that changes over time.',
}

export function templatePurpose(template) {
  const name = template.name || template.idShort || ''
  const key = name.toLowerCase().replace(/[^a-z]/g, '')
  if (purposes[key]) return purposes[key]
  // Keep the supplier's wording for templates outside the local collection.
  const description = (template.description || '').replace(/\s+/g, ' ').trim()
  if (description) return description.split(/(?<=[.!?])\s+/)[0]
  const label = name.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' ')
  return `Provides a structured template for ${label || 'asset'} information.`
}
