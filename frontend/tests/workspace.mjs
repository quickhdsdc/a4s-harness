// Generated test modules live in disposable work/, while dependencies stay here.
export function workspaceDirectory(name) {
  return new URL(`../../work/temp/frontend/${name}/`, import.meta.url)
}

export function workspaceModule(code) {
  return code.replace(/(from\s+)(['"])([^'"]+)\2/g, (match, prefix, quote, specifier) => {
    if (specifier === './services/uploadIdentity.mjs') {
      return `${prefix}${quote}${new URL('../src/services/uploadIdentity.mjs', import.meta.url).href}${quote}`
    }
    if (specifier.startsWith('../../src/')) {
      return `${prefix}${quote}${new URL('../src/' + specifier.slice('../../src/'.length), import.meta.url).href}${quote}`
    }
    if (specifier.startsWith('.') || specifier.startsWith('/') || specifier.includes(':')) return match
    return `${prefix}${quote}${import.meta.resolve(specifier)}${quote}`
  })
}
