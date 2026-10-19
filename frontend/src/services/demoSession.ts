import {ref} from 'vue'
import {api} from './api'

export const demoSession = ref<{id:string; started_at:number} | null>(null)

export function acceptDemoSession(next:{id:string; started_at:number}) {
  if (!next?.id || !Number.isFinite(next.started_at)) return
  // A response from an earlier demo must never reinstate its state.
  if (demoSession.value && next.started_at < demoSession.value.started_at) return
  if (next.id !== demoSession.value?.id) demoSession.value = next
}

export async function refreshDemoSession() {
  acceptDemoSession((await api.get<any>('/api/demo/festo/session')).data)
}
