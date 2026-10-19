export function populationTitle(result) {
  if (!result) return 'Population run finished'
  const {applied,failed,notAttempted,total} = result.counts
  if (total > 0 && applied === total && !failed && !notAttempted) return result.cleanup?.failed?.length ? 'Values applied; cleanup incomplete' : 'AAS populated successfully'
  return applied > 0 ? 'AAS population partially completed' : 'No values were populated'
}

export function populationTranscript(result, aas) {
  const c = result.counts
  const lines = [`Population results for ${aas}:`,
    `${c.applied} of ${c.total} planned values applied; ${c.failed} failed; ${c.notAttempted} not attempted.`]
  for (const failure of result.failed || []) lines.push(`Failed: ${failure.path || failure.entity || ''} — ${failure.error}`)
  for (const row of result.unresolved || []) lines.push(`Unresolved: ${row.entity || ''} — ${row.reason}`)
  if (result.cleanup?.status === 'completed' || result.cleanup?.status === 'incomplete') {
    lines.push(`Empty properties removed: ${result.cleanup.removed.length}.`)
    for (const failure of result.cleanup.failed || []) lines.push(`Cleanup failed: ${failure.submodel}/${failure.path} — ${failure.error}`)
  }
  return lines.join('\n')
}
