<template>
  <section class="update-review" aria-label="Reviewed AAS changes">
    <div class="review-heading"><h3>{{ resultView ? 'Update details' : 'Review changes' }}</h3><span>{{ preview.changes.length }} {{ preview.changes.length === 1 ? 'change' : 'changes' }}</span></div>
    <p v-if="!resultView" class="review-description">These changes are prepared for confirmation.</p>
    <ul v-if="preview.automatic && preview.replacementGroups?.length" class="replacement-summary">
      <li v-for="group in preview.replacementGroups" :key="group.candidateId"><strong>{{ group.name }}</strong><span>{{ group.replaces.length ? `Replacement for ${group.replaces.length} existing ${group.replaces.length === 1 ? 'submodel' : 'submodels'}` : 'New submodel' }}</span></li>
    </ul>
    <p v-if="preview.conflicts?.length" role="alert">Resolve {{ preview.conflicts.length }} incompatible mappings before applying.</p>
    <div class="change-counts"><span v-for="(count, action) in counts" :key="action"><strong>{{ count }}</strong> {{ actionLabel(action, count) }}</span></div>
    <details v-if="preview.validation?.issues.length" class="validation-notes">
      <summary>Template coverage <span>{{ preview.validation.issues.length }} unfilled items</span></summary>
      <p>The template declares these items as required, but no values were provided. Empty fields, files and collections were omitted during cleanup, so template completeness remains incomplete. This count does not mean failed writes; write results are shown above.</p>
      <ul class="coverage-items"><li v-for="(issue, i) in preview.validation.issues" :key="i">{{ issue.path }}</li></ul>
    </details>
    <details>
      <summary>Show changes and previous values</summary>
      <div class="table-wrap" tabindex="0" aria-label="Scrollable change list">
        <table><thead><tr><th>Change</th><th>Destination</th><th>Previous</th><th>Proposed</th></tr></thead>
          <tbody><tr v-for="(change, i) in preview.changes" :key="i">
            <td>{{ change.action }}</td><td>{{ change.path || change.submodel }}</td>
            <td><pre>{{ printable(change.before) }}</pre></td><td><pre>{{ printable(change.after) }}</pre></td>
          </tr></tbody>
        </table>
      </div>
    </details>
    <p v-if="!resultView" class="review-description">Confirming saves a new revision with the previous values in history.</p>
  </section>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import type {UpdatePreview} from '@/services/instanceUpdates'
const props = defineProps<{preview: UpdatePreview; resultView?: boolean}>()
const counts = computed(() => props.preview.changes.reduce((result: Record<string, number>, row) => {
  result[row.action] = (result[row.action] || 0) + 1
  return result
}, {}))
const printable = (value: any) => value == null ? '—' : JSON.stringify(value, null, 2)
const actionLabels: Record<string, [string, string]> = {
  'add-submodel':['submodel added','submodels added'], 'detach-submodel':['submodel detached','submodels detached'],
  create:['element added','elements added'], remove:['element removed','elements removed'],
  update:['value updated','values updated'], 'schema-update':['metadata change','metadata changes']}
const actionLabel = (action: string | number, count: number) => actionLabels[action]?.[count === 1 ? 0 : 1] || action
</script>
<style scoped>
.update-review {padding:16px;color:#23443a;text-align:left;font-size:14px;min-width:0;}
.review-heading {display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px;}
.review-heading h3 {font-size:16px;margin:0;}.review-heading > span {font-size:12px;color:#536b61;white-space:nowrap;}
p {margin:0 0 10px;line-height:1.6;}.review-description {color:#536b61;}
.replacement-summary {list-style:none;padding:0;margin:0 0 14px;display:grid;gap:8px;}
.replacement-summary li {padding:10px 12px;background:#f2f8f5;border:1px solid #d7e5df;border-radius:6px;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;}
.replacement-summary strong {overflow-wrap:anywhere;}.replacement-summary span {color:#52675e;font-size:13px;}
.change-counts{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px;}
.change-counts > span {display:inline-flex;gap:5px;align-items:center;border:1px solid #dde6e1;border-radius:5px;padding:5px 8px;background:#f8faf9;color:#52675e;font-size:12px;}
.change-counts strong {color:#294d3d;}
summary{cursor:pointer;padding:10px 0;font-weight:600;line-height:1.5;}summary:focus-visible{outline:2px solid #10836e;outline-offset:2px;} .table-wrap{overflow:auto;max-height:420px;}
.validation-notes{border:1px solid #e1e5e2;border-radius:6px;padding:0 12px;margin-bottom:12px;background:#fafbf9;}
.validation-notes summary {display:list-item;color:#536348;}
.validation-notes summary > span {font-size:12px;font-weight:400;margin-left:8px;}
.validation-notes p {font-size:13px;color:#596757;}
.coverage-items {list-style:none;margin:0 0 12px;padding:0;max-height:240px;overflow:auto;}
.coverage-items li {font:12px/1.6 ui-monospace,Consolas,monospace;padding:5px 0;border-bottom:1px solid #e8ece7;overflow-wrap:anywhere;}
table{width:100%;border-collapse:collapse;}th,td{padding:8px;border-bottom:1px solid #cbded6;vertical-align:top;text-align:left;}
pre{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere;max-width:320px;min-width:90px;}
</style>
