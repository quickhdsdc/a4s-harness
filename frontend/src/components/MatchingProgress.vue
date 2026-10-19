<template>
  <div class="matching-progress" aria-live="polite">
    <div class="progress-heading"><strong>Matching extracted facts...</strong><span v-if="elapsed > 0">{{ elapsed }}s elapsed</span></div>
    <ol class="phases">
      <li v-for="(name, index) in phases" :key="name" :class="{active: index === phase, done: index < phase}" :aria-current="index === phase ? 'step' : undefined">
        <span><template v-if="index < phase">&#10003;</template><template v-else>{{ index + 1 }}</template></span>{{ name }}
      </li>
    </ol>
    <progress aria-label="Current matching stage" max="1" :value="progress?.status === 'completed' ? 1 : undefined"></progress>
    <p class="stage">{{ progress?.status === 'completed' ? 'Ready for review' : phases[phase] }}</p>
    <p>{{ progress?.detail || 'Preparing the matching request...' }}</p>
    <p v-if="waiting" class="waiting">Still waiting for this stage to finish. No new results have arrived yet.</p>
  </div>
</template>
<script setup lang="ts">
import {ref, computed, onMounted, onUnmounted} from 'vue'
import type {MatchingProgress} from '../types'
const props = defineProps<{progress?: MatchingProgress | null}>()
const now = ref(Date.now() / 1000)
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {timer = setInterval(() => {now.value = Date.now() / 1000}, 1000)})
onUnmounted(() => {if (timer) clearInterval(timer)})
const phases = ['Prepare AAS structure', 'Retrieve candidates', 'Choose placements', 'Prepare results']
const phase = computed(() => {
  const stage = props.progress?.stage || 'Preparing'
  if (stage === 'Complete') return phases.length
  if (['Saving', 'Loading results'].includes(stage)) return 3
  if (['Matching', 'LLM placement'].includes(stage)) return 2
  if (stage === 'Embedding') return 1
  return 0
})
const elapsed = computed(() => Math.max(0, Math.floor(props.progress?.started_at ? now.value - props.progress.started_at : props.progress?.elapsed_seconds || 0)))
const waiting = computed(() => props.progress?.status === 'running' && props.progress.updated_at && now.value - props.progress.updated_at > 30)
</script>
<style scoped>
.matching-progress {max-width:700px;margin:50px auto;padding:24px;}
.progress-heading {display:flex;justify-content:space-between;gap:20px;margin-bottom:18px;}
progress {width:100%;height:12px;accent-color:#179c7d;}
.phases {list-style:none;display:flex;flex-wrap:wrap;gap:12px;padding:0;margin:0 0 20px;}
.phases li {display:flex;align-items:center;gap:7px;color:#85918d;font-size:13px;}
.phases li span {border:1px solid currentColor;border-radius:50%;width:21px;height:21px;display:grid;place-items:center;}
.phases .active {color:#126e59;font-weight:600;}
.phases .done {color:#179c7d;}
p {font-size:14px;color:#59636d;line-height:1.5;margin:10px 0;overflow-wrap:anywhere;}
.stage {font-weight:600;color:#333;}
.waiting {color:#896312;}
</style>
