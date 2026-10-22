import {templatePurpose} from './templatePurpose.mjs'

function normalized(value) {
  return String(value || '').replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .normalize('NFKD').replace(/\p{Diacritic}/gu, '')
    .toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim()
}

export function filterTemplates(templates, query) {
  const terms = normalized(query).split(' ').filter(Boolean)
  if (!terms.length) return templates
  return templates.filter(template => {
    const text = normalized([template.name, template.idShort, template.id,
      template.description, templatePurpose(template), template.version,
      template.revision, `${template.version || ''}.${template.revision || ''}`].join(' '))
    return terms.every(term => text.includes(term))
  })
}

export function reconcileTemplateSelection(templates, selection) {
  const ids = Array.isArray(selection) ? selection : selection ? [selection] : []
  const available = new Set(templates.map(template => template.id))
  return [...new Set(ids)].filter(id => available.has(id))
}
