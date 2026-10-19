// apiPath addresses the existing target: a parent for create, a leaf for write.
export function targetIdentity(target) {
  return target.submodelId && (target.apiPath || target.type === 'Submodel' || target.targetType === 'Submodel') ? `${target.submodelId}::${target.apiPath || ''}`
    : target.semanticPath || target.idShort
}

export function matchingLocations(match) {
  const selections = match.aasProperties?.length ? match.aasProperties : [match]
  return selections.flatMap(selection => {
    if (typeof selection === 'string') return []
    const manual = selection !== match
    const path = selection.apiPath || (!manual ? match.apiPath : '') || ''
    const semantic = selection.semanticPath || (!manual ? match.semanticPath : '') || ''
    const suffix = path ? `/${path}` : ''
    const submodel = selection.submodelIdShort || (!manual ? match.submodelIdShort : '') ||
      (suffix && semantic.endsWith(suffix) ? semantic.slice(0, -suffix.length) : '')
    if (!path && !submodel) return []
    const type = selection.type || match.targetType
    const create = manual ? ['Submodel', 'SubmodelElementCollection', 'SubmodelElementList', 'Entity'].includes(type)
      : match.action === 'create'
    const parts = path.split('.').filter(Boolean)
    const parent = create ? parts : parts.slice(0, -1)
    return [{submodel: submodel || match.submodelId || 'Unknown submodel',
      parent: parent.join(' → '), create, targetType: type,
      path, label: [submodel || match.submodelId || 'Unknown submodel', ...parent].join(' → ')}]
  })
}
