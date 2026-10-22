export function populationTitle(result) {
  if (!result) return 'Population run finished'
  const {applied,failed,notAttempted,total} = result.counts
  if (result.success !== false && total > 0 && applied === total && !failed && !notAttempted) return result.cleanup?.failed?.length ? 'Values applied; cleanup incomplete' : 'AAS populated successfully'
  return applied > 0 ? 'AAS population partially completed' : 'No values were populated'
}

export function populationTranscript(result, aas) {
  const c = result.counts
  const lines = [`Population results for ${aas}:`,
    `${c.applied} of ${c.total} planned values applied; ${c.failed} failed; ${c.notAttempted} not attempted.`]
  if (c.unverified) lines.push(`${c.unverified} values could not be verified after an interrupted update.`)
  if (result.revisionId) lines.push(`Revision: ${result.revisionId}; status: ${result.status}.`)
  if (result.unrecorded) lines.push(`Ledger record unavailable: ${result.unrecorded}. The update revision remains in history.`)
  for (const failure of result.failed || []) lines.push(`Failed: ${failure.path || failure.entity || ''} — ${failure.error}`)
  for (const row of result.unresolved || []) lines.push(`Unresolved: ${row.entity || ''} — ${row.reason}`)
  if (result.cleanup?.status === 'completed' || result.cleanup?.status === 'incomplete') {
    lines.push(`Empty elements removed (properties and collections): ${result.cleanup.removed.length}.`)
    if (result.cleanup.omitted?.length) lines.push(`Unused empty template slots omitted: ${result.cleanup.omitted.length}.`)
    for (const failure of result.cleanup.failed || []) lines.push(`Cleanup failed: ${failure.submodel}/${failure.path} — ${failure.error}`)
  }
  return lines.join('\n')
}
