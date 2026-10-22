<template>
  <section class="instance-update-setup" aria-label="Existing device information">
    <p v-if="loading" role="status">Loading existing submodels...</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <div v-if="catalog" class="existing-submodels">
      <div class="inventory-caption">Submodels <span>{{ catalog.submodels.length }}</span></div>
      <p v-if="!catalog.submodels.length" class="empty-inventory">No submodels yet</p>
      <ul v-else aria-label="Existing submodels">
        <li v-for="sm in catalog.submodels" :key="sm.id" :title="sm.id" class="submodel-block">
          <svg aria-hidden="true" viewBox="0 0 20 20" fill="none"><path d="m10 2 7 4v8l-7 4-7-4V6l7-4Z M3 6l7 4 7-4 M10 10v8" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" /></svg>
          <span class="submodel-name">{{ sm.name }}</span>
          <span v-if="sm.version" class="submodel-version">v{{ sm.version }}<template v-if="sm.revision">.{{ sm.revision }}</template></span>
        </li>
      </ul>
    </div>
    <details v-if="history.length" class="history"><summary>Update history ({{ history.length }})</summary>
      <article v-for="entry in history" :key="entry.id">
        <strong>{{ new Date(entry.createdAt * 1000).toLocaleString() }} · {{ entry.status }}</strong>
        <div class="history-actions"><button class="btn btn-secondary" @click="download(entry.id)">Download snapshots</button>
          <button v-if="['applying','partial','uncertain'].includes(entry.status)" class="btn btn-secondary" @click="reconcile(entry.id)" :disabled="busy">Check actual result</button>
          <button v-if="['committed','partial','uncertain'].includes(entry.status)" class="btn btn-secondary" @click="restore(entry.id)" :disabled="busy">Preview restore</button></div>
      </article>
    </details>
    <UpdateChangeReview v-if="restoration" :preview="restoration" />
    <button v-if="restoration" class="btn btn-primary" @click="applyRestore" :disabled="busy">{{ busy ? 'Restoring…' : 'Apply reviewed restore' }}</button>
    <p v-if="restoreStatus" role="status">{{ restoreStatus }}</p>
  </section>
</template>
<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {instanceUpdates, type UpdatePreview} from '@/services/instanceUpdates'
import UpdateChangeReview from './UpdateChangeReview.vue'
const props = defineProps<{aas: string; endpoint: string}>()
const catalog = ref<any>(null), loading = ref(false), busy = ref(false), error = ref('')
const restoration = ref<UpdatePreview | null>(null), restoreStatus = ref('')
let sequence = 0
const history = computed(() => (catalog.value?.history || []).filter((row: any) => row.status !== 'draft' && row.status !== 'reviewed').slice(0, 20))
async function load() {
  const current = ++sequence
  catalog.value = null; error.value = ''; restoration.value = null
  if (!props.aas || !props.endpoint) return
  loading.value = true
  try { const value = await instanceUpdates.existing(props.aas, props.endpoint); if (current === sequence) catalog.value = value }
  catch (e: any) { if (current === sequence) error.value = e.message }
  finally { if (current === sequence) loading.value = false }
}
async function download(id: string) {
  try { const value = await instanceUpdates.snapshot(id); const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}))
    const a = document.createElement('a'); a.href = url; a.download = `aas-revision-${id}.json`; a.click(); URL.revokeObjectURL(url)
  } catch (e: any) { error.value = e.message }
}
async function restore(id: string) {
  busy.value = true; error.value = ''
  try { restoration.value = await instanceUpdates.restore(id) } catch (e: any) { error.value = e.message }
  finally { busy.value = false }
}
async function reconcile(id: string) {
  busy.value = true; error.value = ''
  try { await instanceUpdates.reconcile(id); await load() } catch (e: any) { error.value = e.message }
  finally { busy.value = false }
}
async function applyRestore() {
  if (!restoration.value) return
  busy.value = true; error.value = ''
  try { const result = await instanceUpdates.commit(restoration.value, props.aas, props.endpoint)
    restoreStatus.value = result.success ? 'Restored as a new revision.' : 'Restore incomplete. Download snapshots to inspect the actual result.'
    restoration.value = null; await load()
  } catch (e: any) { error.value = e.message }
  finally { busy.value = false }
}
watch(() => [props.aas, props.endpoint], load, {immediate:true})
</script>
<style scoped>
.instance-update-setup{margin:12px 0;padding:0 16px;border-left:1px solid #d3e6de;min-width:0;align-self:center;}p{margin:0;line-height:1.5;font-size:13px;}
.inventory-caption{display:flex;align-items:center;gap:8px;font-size:12px;font-weight:600;color:#4b6259;margin-bottom:8px;}
.inventory-caption span{font-size:11px;min-width:20px;text-align:center;border-radius:10px;background:#deeee6;padding:1px 5px;color:#285e4c;}
ul{display:flex;flex-wrap:wrap;gap:6px;list-style:none;padding:0;margin:0;}
.submodel-block{display:inline-flex;align-items:center;gap:6px;max-width:100%;padding:7px 9px;background:#fff;border:1px solid #c9ded4;border-radius:6px;color:#245440;line-height:1.35;font-size:12px;font-weight:500;}
.submodel-block svg{width:16px;height:16px;flex-shrink:0;color:#46775f;}
.submodel-name{overflow-wrap:anywhere;min-width:0;}
.submodel-version{font-size:11px;color:#54665e;background:#edf4f0;border-radius:3px;padding:1px 4px;white-space:nowrap;}
.empty-inventory{color:#52645e;}
.error{color:#9b3c28;overflow-wrap:anywhere;}summary{cursor:pointer;font-weight:600;padding:12px 0;}
.history article{padding:12px 0;border-top:1px solid #ddd;}.history-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;}
@container wizard-input (max-width:640px){.instance-update-setup{margin:0 16px 14px;padding:12px 0 0;border-left:0;border-top:1px solid #d3e6de;}}
</style>
