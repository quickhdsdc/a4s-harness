<template>
  <span class="agent-reset">
    <button @click="reset" :disabled="busy || agentLocked" :title="agentLocked ? 'Stop the Agent task first.' : 'Clear Agent context and incidents; stop monitoring. Preserve MES data.'">{{ busy ? 'Resetting…' : 'Reset Agent' }}</button>
    <small v-if="error" role="alert">{{ error }}</small>
  </span>
</template>
<script setup lang="ts">
import {ref} from 'vue'
import {api} from '../services/api'
import {acceptDemoSession} from '../services/demoSession'
const props = defineProps<{agentLocked?:boolean}>()
const busy = ref(false), error = ref('')
async function reset() {
  if (busy.value || props.agentLocked) return
  busy.value = true; error.value = ''
  try {
    const {data} = await api.post<any>('/api/demo/festo/session/reset', {})
    acceptDemoSession(data.demo_session)
  } catch (e:any) { error.value = e.message || String(e) }
  finally { busy.value = false }
}
</script>
<style scoped>
.agent-reset{display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap}button{padding:8px 12px;background:#172632;color:#dce9f1;border:1px solid #35516a;cursor:pointer}button:disabled{opacity:.5;cursor:default}small{color:#ffb3a7;max-width:340px}
</style>
