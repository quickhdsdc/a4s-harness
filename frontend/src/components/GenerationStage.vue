<template>
  <div class="generation-stage">
    <h2 class="section-title">AAS Population</h2>

    <div v-if="data.isGenerating" class="progress-indicator">
      <div class="spinner"></div>
      <h3>Populating AAS...</h3>
    </div>

    <p v-else-if="data.populationError" class="population-failure">Population could not be completed. See chat for details.</p>

    <div v-else-if="data.generationComplete" class="success-message">
      <div v-if="fullyApplied" class="success-icon">&#10003;</div>
      <div v-else class="success-icon" style="color: #896312">!</div>
      <h2 :style="{color: fullyApplied ? '#28a745' : '#896312', marginBottom: '10px'}">{{ populationTitle(data.populationResult) }}</h2>
      

      <div style="margin-top: 40px; padding: 30px; background: #f8f9fa; border-radius: 8px; text-align: left; max-width: 600px; margin-left: auto; margin-right: auto">
        <h3 style="margin-bottom: 20px; color: #333">Population Details</h3>

        <div style="margin-bottom: 15px">
          <strong style="color: #666; font-size: 13px">Target AAS:</strong>
          <div style="margin-top: 4px; color: #333; word-break: break-all">{{ data.targetAAS }}</div>
        </div>

        <div v-if="data.populationResult">
          <strong>Values applied: {{ data.populationResult.counts.applied }} / {{ data.populationResult.counts.total }}</strong>
          <p>Failed: {{ data.populationResult.counts.failed }}; Not attempted: {{ data.populationResult.counts.notAttempted }}</p>
          <p v-if="data.populationResult.cleanup?.status === 'completed' || data.populationResult.cleanup?.status === 'incomplete'">Empty properties removed: {{ data.populationResult.cleanup.removed.length }}</p>
          <p v-if="data.populationResult.counts.failed || data.populationResult.counts.notAttempted || data.populationResult.cleanup?.failed.length" class="population-failure">See chat for failure details.</p>
        </div>
        <p v-else>Verified write counts are unavailable for this earlier run.</p>
      </div>

      <div class="download-links">
        <button class="btn btn-primary" @click="downloadAASX">
          📦 Download AASX
        </button>
        <button class="btn btn-primary" @click="downloadJSON">
          📄 Download JSON
        </button>
        <button class="btn btn-secondary" @click="viewOnServer">
          🔗 View on Server
        </button>
      </div>

      <div style="margin-top: 40px">
        <button class="btn btn-success" @click="emit('reset')">
          ✨ Populate Another AAS
        </button>
      </div>

    </div>
  </div>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import {populationTitle} from '@/services/populationPresentation.mjs'
import { useEnvStore } from '@/stores/environmentStore'
import { aasService } from '@/services/aasService'
import { ApiError } from '@/services/api'
import type { WizardData } from '@/types'

// Props
interface Props {
  data: WizardData
}

const props = defineProps<Props>()
const fullyApplied = computed(() => !!props.data.populationResult && props.data.populationResult.counts.total > 0 && props.data.populationResult.counts.applied === props.data.populationResult.counts.total && !props.data.populationResult.counts.failed && !props.data.populationResult.counts.notAttempted && !props.data.populationResult.cleanup?.failed.length)

// Emits
const emit = defineEmits<{
  reset: []
}>()

// Environment store
const environmentStore = useEnvStore()

const downloadAASX = async (): Promise<void> => {
  console.log('Downloading AASX package...')
  const aasIdShort = props.data.targetAAS
  const endpoint = props.data.aasServerEndpoint || environmentStore.aasServerUrl

  try {
    const blob = await aasService.downloadAASX(aasIdShort, endpoint)
    aasService.triggerDownload(blob, `${aasIdShort}.aasx`)
  } catch (error) {
    console.error('Failed to download AASX:', error)
    const errorMsg = error instanceof ApiError
      ? `Download failed: ${error.message}`
      : 'Failed to download AASX file. Please try again.'
    alert(errorMsg)
  }
}

const downloadJSON = async (): Promise<void> => {
  console.log('Downloading JSON...')
  const aasIdShort = props.data.targetAAS
  const endpoint = props.data.aasServerEndpoint || environmentStore.aasServerUrl

  try {
    const blob = await aasService.downloadJSON(aasIdShort, endpoint)
    aasService.triggerDownload(blob, `${aasIdShort}.json`)
  } catch (error) {
    console.error('Failed to download JSON:', error)
    const errorMsg = error instanceof ApiError
      ? `Download failed: ${error.message}`
      : 'Failed to download JSON file. Please try again.'
    alert(errorMsg)
  }
}

const viewOnServer = async (): Promise<void> => {
  console.log('Opening BaSyx UI...')
  const uiEndpoint = props.data.aasUIEndpoint || environmentStore.aasUiUrl
  const serverUrl = props.data.aasServerEndpoint || environmentStore.aasServerUrl
  const aasIdShort = props.data.targetAAS

  // Try to deep-link straight to the populated shell, matching the ShopFloor
  // "view" pattern: {uiUrl}/?aas={serverUrl}/shells/{base64(aasId)}.
  try {
    if (aasIdShort) {
      const res = await aasService.checkAAS(aasIdShort, serverUrl) as { exists?: boolean; aas_id?: string; id?: string }
      const aasId = res?.aas_id || res?.id
      if (aasId) {
        const b64Id = btoa(aasId)
        window.open(`${uiEndpoint}/?aas=${serverUrl}/shells/${b64Id}`, '_blank')
        return
      }
    }
  } catch (error) {
    console.warn('Could not resolve AAS id for deep-link, opening BaSyx UI root instead:', error)
  }

  // Fallback: open the BaSyx UI root.
  window.open(uiEndpoint, '_blank')
}
</script>

<style scoped>
.population-failure {color:#9b3c28;overflow-wrap:anywhere;margin-top:10px;line-height:1.5;}
</style>
