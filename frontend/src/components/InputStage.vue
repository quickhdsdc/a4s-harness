<template>
  <div class="input-stage">
    <div v-if="preparationPhase" class="preparation-status" role="status" aria-live="polite">
      <span class="preparation-spinner" aria-hidden="true"></span>{{ preparationPhase }}
    </div>
    <fieldset class="input-fields" :disabled="busy" aria-label="AAS and input configuration">
    <!-- Block 2: AAS Configuration -->
    <h2 class="section-title" style="margin-top: 40px">AAS Configuration</h2>

    <!-- Mode Selection -->
    <div class="form-group">
      <label>Mode</label>
      <div class="tabs" style="margin-bottom: 20px">
        <button
          :class="['tab', { active: data.mode === 'create' }]"
          @click="setMode('create')"
        >
          Create New AAS
        </button>
        <button
          :class="['tab', { active: data.mode === 'edit' }]"
          @click="setMode('edit')"
        >
          Edit Existing AAS
        </button>
      </div>
    </div>

    <!-- Create Mode Content -->
    <div v-if="data.mode === 'create'" class="mode-content">
      <!-- Target AAS ID (Moved to top as requested) -->
      <div class="form-group">
        <label for="targetAAS">Target AAS ID Short *</label>
        <input
          id="targetAAS"
          type="text"
          :value="data.targetAAS"
          @input="emit('update', 'targetAAS', $event.target.value)"
          placeholder="NewProductAAS"
        />
        <HelpTip text="Enter the ID Short for the new AAS (e.g. NewProductAAS)" />
      </div>

    </div>

    <!-- Edit Mode Content -->
    <div v-if="data.mode === 'edit'" class="mode-content">
      <!-- Select Target AAS -->
      <div class="form-group">
        <label>Select Target AAS *</label>
        
        <div v-if="aasListLoading" class="loading-state">
          Loading existing AASs...
        </div>
        <div v-else-if="aasListError" class="error-state">
          {{ aasListError }}
        </div>
        <div v-else class="template-list aas-instance-list">
          <div
            v-for="aas in aasList"
            :key="aas.id"
            class="aas-instance-card"
            :class="{ selected: data.targetAAS === aas.id || data.targetAAS === aas.idShort }"
          >
            <label class="aas-instance-choice">
            <input
              type="radio"
              name="targetAAS"
              :value="aas.id"
              :checked="data.targetAAS === aas.id || data.targetAAS === aas.idShort"
              @change="onAASSelect"
            />
            <div class="aas-instance-identity">
              <strong>{{ aas.idShort }}</strong>
              <span class="aas-instance-id">{{ aas.id }}</span>
            </div>
            </label>
            <InstanceUpdateSetup v-if="data.targetAAS === aas.id || data.targetAAS === aas.idShort"
              :aas="aas.id" :endpoint="data.aasServerEndpoint || environmentStore.aasServerUrl" />
          </div>
        </div>
      </div>
    </div>

    <div v-if="data.mode === 'create' || data.targetAAS" class="form-group standardized-templates">
      <div class="templates-heading">
        <h3>Submodel templates <span v-if="data.mode === 'create'">*</span></h3>
        <HelpTip :text="data.mode === 'edit'
          ? 'Choose standardized templates to add or update device information. Existing values and your new input are matched together for review before saving. Leave templates unselected to update the current structure.'
          : 'Choose standardized templates for the information you want to include in your new AAS.'" />
        <button type="button" class="template-refresh" @click="fetchTemplates" :disabled="templatesLoading">
          {{ templatesLoading ? 'Refreshing...' : 'Refresh' }}
        </button>
      </div>
      <p v-if="templateNotice" class="template-notice" role="status">{{ templateNotice }}</p>
      <div v-if="templatesLoading" class="loading-state">Loading templates...</div>
      <div v-else-if="templatesError" class="error-state">{{ templatesError }}</div>
      <div v-else>
        <div class="template-filters">
          <label for="template-search" class="visually-hidden">Search templates</label>
          <div class="template-search-row">
            <input id="template-search" v-model="templateSearch" type="search"
              placeholder="Find a template by name, keyword or version" aria-controls="smt-template-list"
              aria-describedby="template-filter-summary" />
            <button v-if="templateSearch" type="button" class="btn btn-secondary" @click="templateSearch = ''">Clear</button>
          </div>
          <div class="template-filter-meta">
            <p id="template-filter-summary" role="status" aria-live="polite" aria-atomic="true">{{ filteredTemplates.length }} of {{ availableTemplates.length }} templates · {{ selectedTemplateCount }} selected</p>
            <label class="template-selected-toggle"><input v-model="selectedTemplatesOnly" type="checkbox" />Selected only</label>
          </div>
        </div>
        <div id="smt-template-list" class="template-list" v-if="filteredTemplates.length">
        <label v-for="template in filteredTemplates" :key="template.id" class="template-item"
               :class="{ selected: isTemplateSelected(template.id) }">
          <input type="checkbox" :value="template.id" :checked="isTemplateSelected(template.id)" @change="toggleTemplate(template.id)" />
          <div class="template-info">
            <strong>{{ template.name }}</strong>
            <span v-if="template.version" class="template-version">Version {{ template.version }}<template v-if="template.revision"> / revision {{ template.revision }}</template></span>
            <span class="template-description">{{ templatePurpose(template) }}</span>
          </div>
        </label>
        </div>
        <div v-else class="template-empty" role="status">
          <p v-if="!availableTemplates.length">No templates are available. Check the library connection and refresh.</p>
          <template v-else><p>No templates match these filters. Try a shorter keyword or clear the filters.</p>
            <button type="button" class="btn btn-secondary" @click="templateSearch = ''; selectedTemplatesOnly = false">Clear filters</button></template>
        </div>
      </div>
    </div>

    <details class="connection-settings"><summary>Connection settings</summary>
    <!-- Block 1: Endpoint Configuration -->
    <h2 class="section-title">Endpoint Configuration</h2>

    <div class="form-group">
      <label for="aasServerEndpoint">AAS Server Endpoint *</label>
      <div class="input-with-button">
        <input
          id="aasServerEndpoint"
          type="text"
          :value="data.aasServerEndpoint"
          @input="emit('update', 'aasServerEndpoint', $event.target.value)"
          :placeholder="environmentStore.aasServerUrl"
        />
        <button
          class="btn btn-secondary"
          @click="refreshData"
          :disabled="templatesLoading || aasListLoading"
          title="Refresh Templates and AAS List"
        >
          Refresh
        </button>
      </div>
      <HelpTip text="Enter the AAS server API endpoint. Click Refresh to reload templates and existing AASs." />
    </div>

    <div class="form-group">
      <label for="aasUIEndpoint">BaSyx UI Endpoint</label>
      <input
        id="aasUIEndpoint"
        type="text"
        :value="data.aasUIEndpoint"
        @input="emit('update', 'aasUIEndpoint', $event.target.value)"
        :placeholder="environmentStore.aasUiUrl"
      />
      <HelpTip text="Enter the BaSyx web UI endpoint for viewing the AAS" />
    </div>

    </details>

    <!-- Block 3: Data Source (Header already exists in next lines) -->

    <h2 class="section-title" style="margin-top: 40px">Data Source</h2>

    <div class="tabs">
      <button
        :class="['tab', { active: data.dataSourceType === 'url' }]"
        @click="setDataSourceType('url')"
      >
        Website URL
      </button>
      <button
        :class="['tab', { active: data.dataSourceType === 'pdf' }]"
        @click="setDataSourceType('pdf')"
      >
        PDF Document
      </button>
      <button
        :class="['tab', { active: data.dataSourceType === 'structured' }]"
        @click="setDataSourceType('structured')"
      >
        Structured File
      </button>
      <button
        :class="['tab', { active: data.dataSourceType === 'text' }]"
        @click="setDataSourceType('text')"
      >
        Text Input
      </button>
    </div>

    <div v-if="data.dataSourceType === 'text'" class="tab-content">
      <div class="alert alert-info">
        Paste the text content directly to extract technical information.
      </div>
      <textarea
        :value="data.dataSourceValue"
        @input="emit('update', 'dataSourceValue', ($event.target as HTMLTextAreaElement).value)"
        placeholder="Paste specification text here..."
        style="width: 100%; min-height: 200px; padding: 16px; font-size: 14px; border-radius: 8px; border: 2px solid #ddd; resize: vertical;"
      ></textarea>
    </div>

    <div v-if="data.dataSourceType === 'url'" class="tab-content">
      <div class="alert alert-info">
        Enter the URL of a product page or datasheet to extract technical information.
      </div>
      <div class="input-with-button">
        <input
          type="url"
          :value="data.dataSourceValue"
          @input="emit('update', 'dataSourceValue', $event.target.value)"
          placeholder="https://example.com/products/motor-xm2000"
          style="flex: 1; padding: 16px; font-size: 18px; height: 60px; border-radius: 8px; border: 2px solid #ddd;"
        />
      </div>
    </div>

    <div v-if="data.dataSourceType === 'pdf' || data.dataSourceType === 'structured'" class="tab-content">
      <div class="alert alert-info">
        {{ data.dataSourceType === 'structured' ? 
           'Upload a CSV or JSON file with "entity", "value", and "description" columns.' : 
           'Upload a PDF datasheet to extract product specifications and technical data.' 
        }}
      </div>

      <div
        v-if="!data.uploadedFiles || data.uploadedFiles.length === 0"
        class="upload-area"
        :class="{ 'drag-over': isDragging }"
        @click="triggerFileInput"
        @dragover.prevent="isDragging = true"
        @dragenter.prevent="isDragging = true"
        @dragleave.prevent="isDragging = false"
        @drop.prevent="handleDrop"
      >
        <div class="upload-icon">📄</div>
        <h3>Click to upload {{ data.dataSourceType === 'structured' ? 'File(s)' : 'PDF(s)' }}</h3>
        <p>or drag and drop multiple files</p>
        <p style="color: #999; font-size: 12px; margin-top: 8px">
            {{ data.dataSourceType === 'structured' ? 'Supported: .csv, .json' : 'Maximum file size: 10MB per file' }}
        </p>
      </div>

      <div v-else class="uploaded-files-container">
        <div v-for="(file, index) in data.uploadedFiles" :key="index" class="uploaded-file">
          <div class="file-icon">📄</div>
          <div style="flex: 1">
            <strong>{{ file.name }}</strong>
            <p style="color: #666; font-size: 12px; margin-top: 4px">
              {{ formatFileSize(file.size) }}
            </p>
          </div>
          <button class="btn btn-secondary" @click="removeFile(index)">Remove</button>
        </div>
        <button class="btn btn-primary" @click="triggerFileInput" style="margin-top: 12px">
          Add More Files
        </button>
      </div>

      <input
        ref="fileInput"
        type="file"
        :accept="data.dataSourceType === 'structured' ? '.csv, .json, application/json, text/csv' : '.pdf, application/pdf'"
        multiple
        class="file-input"
        @change="handleFileUpload"
      />
    </div>
    </fieldset>
  </div>
</template>

<script setup lang="ts">
import InstanceUpdateSetup from './InstanceUpdateSetup.vue'
import { computed, ref, type Ref, watch } from 'vue'
import { useEnvStore } from '@/stores/environmentStore'
import { fileService } from '@/services/fileService'
import { templatePurpose } from '@/services/templatePurpose.mjs'
import { filterTemplates, reconcileTemplateSelection } from '@/services/templateFilter.mjs'
import { aasService } from '@/services/aasService'
import { ApiError } from '@/services/api'
import type { WizardData, SubmodelTemplate } from '@/types'

// Props
interface Props {
  data: WizardData
  preparationPhase?: string
  busy?: boolean
}

const props = defineProps<Props>()

// Emits
const emit = defineEmits<{
  update: [key: keyof WizardData, value: any]
}>()

// Environment store
const environmentStore = useEnvStore()

// Refs
const fileInput = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)

// AAS List Logic
const aasList = ref<any[]>([])
const aasListLoading = ref(false)
const aasListError = ref<string | null>(null)

const fetchAASList = async () => {
    aasListLoading.value = true
    aasListError.value = null
    try {
        const endpoint = props.data.aasServerEndpoint || environmentStore.aasServerUrl
        const list = await aasService.getAASList(endpoint)
        
        // Filter: only show Instance AAS (not Type/Template blueprints or SMT collections)
        aasList.value = list.filter((aas: any) => {
            const idShort = aas.idShort || ''
            const assetKind = aas.assetKind || 'Unknown'
            
            const isCollection = idShort.toLowerCase().includes('collectionofsmt')
            const isInstance = assetKind === 'Instance'
            
            return !isCollection && isInstance
        })
    } catch (e: any) {
        console.error("Failed to fetch AAS list", e)
        aasListError.value = e.message || "Failed to load AAS list"
    } finally {
        aasListLoading.value = false
    }
}

const refreshData = async () => {
    await fetchTemplates()
    if (props.data.mode === 'edit') {
        await fetchAASList()
    }
}

const setMode = (mode: 'create' | 'edit') => {
    if (mode === props.data.mode) return
    emit('update', 'targetAAS', '')
    emit('update', 'mode', mode)
    if (mode === 'edit') {
        fetchAASList()
    }
}

const onAASSelect = (event: Event) => {
    const target = event.target as HTMLSelectElement
    const idShort = target.value
    emit('update', 'targetAAS', idShort)
    
    // Find selected AAS to stick endpoint if needed
    const selectedAAS = aasList.value.find(a => a.id === idShort || a.idShort === idShort)
    if (selectedAAS && selectedAAS.endpoint) {
         emit('update', 'aasServerEndpoint', selectedAAS.endpoint)
    }
}

// Watch endpoint changes to refresh list in edit mode
watch(() => props.data.aasServerEndpoint, (newVal) => {
    if (props.data.mode === 'edit' && newVal) {
        // Debounce could be added here, but for now relying on manual refresh button 
        // or just letting it fire (though it might be spammy)
        // actually, user asked for button, so maybe we SHOULD remove auto-watch?
        // But keeping it for now as "live" feel is often nice, but if user explicitly asked for button...
        // "should add a button allowing user to change the default endpoint to re-fetch"
        // This implies the fetch shouldn't happen automatically on type, potentially.
        // But let's keep it for now, it's safer functionality-wise.
        // fetchAASList() 
    }
})

// Data Source Logic
const setDataSourceType = (type: 'url' | 'pdf' | 'text' | 'structured') => {
    // Only update if changing
    if (props.data.dataSourceType === type) return

    emit('update', 'dataSourceType', type)
    
    // Clear data from other mode
    emit('update', 'dataSourceValue', '')
    emit('update', 'uploadedFiles', [])
    
    // Reset file input if exists
    if (fileInput.value) {
        fileInput.value.value = ''
    }
}

// Available submodel templates - fetched from backend
const availableTemplates: Ref<SubmodelTemplate[]> = ref([])
const templatesLoading = ref(true)
const templatesError: Ref<string | null> = ref(null)
const templateNotice = ref('')
let templateLoadSequence = 0
const templateSearch = ref('')
const selectedTemplatesOnly = ref(false)
const selectedTemplateIds = computed(() => Array.isArray(props.data.submodelTemplate)
  ? props.data.submodelTemplate : props.data.submodelTemplate ? [props.data.submodelTemplate] : [])
const selectedTemplateCount = computed(() => selectedTemplateIds.value.length)
const filteredTemplates = computed(() => filterTemplates(availableTemplates.value, templateSearch.value)
  .filter(template => !selectedTemplatesOnly.value || selectedTemplateIds.value.includes(template.id)))

// Fetch templates from backend on mount
const fetchTemplates = async (): Promise<boolean> => {
  const sequence = ++templateLoadSequence
  try {
    templatesLoading.value = true
    templatesError.value = null

    // The backend owns the SMT source, independently of the target AAS repository.
    const templates = await fileService.getTemplates()
    if (sequence !== templateLoadSequence) return false
    availableTemplates.value = templates
    const selected = selectedTemplateIds.value
    const retained = reconcileTemplateSelection(templates, selected)
    if (retained.length !== selected.length) {
      emit('update', 'submodelTemplate', retained)
      templateNotice.value = 'Template list updated. Unavailable selections were cleared; your other selections are kept.'
    } else {
      templateNotice.value = ''
    }
    return true
  } catch (error) {
    if (sequence !== templateLoadSequence) return false
    console.error('Error fetching templates:', error)
    templatesError.value = error instanceof ApiError ? error.message : 'Failed to load templates'

    availableTemplates.value = []
    return false
  } finally {
    if (sequence === templateLoadSequence) templatesLoading.value = false
  }
}

defineExpose({ refreshTemplates: fetchTemplates })

// Fetch templates on component mount
fetchTemplates()
if (props.data.mode === 'edit') fetchAASList()

// Check if a template is selected
const isTemplateSelected = (templateId: string): boolean => {
  if (Array.isArray(props.data.submodelTemplate)) {
    return props.data.submodelTemplate.includes(templateId)
  }
  return props.data.submodelTemplate === templateId
}

// Toggle template selection
const toggleTemplate = (templateId: string): void => {
  let selectedTemplates: string[] = Array.isArray(props.data.submodelTemplate)
    ? [...props.data.submodelTemplate]
    : props.data.submodelTemplate
    ? [props.data.submodelTemplate]
    : []

  const index = selectedTemplates.indexOf(templateId)
  if (index > -1) {
    // Remove if already selected
    selectedTemplates.splice(index, 1)
  } else {
    // Add if not selected
    selectedTemplates.push(templateId)
  }

  emit('update', 'submodelTemplate', selectedTemplates)
}

const triggerFileInput = (): void => {
  fileInput.value?.click()
}

const handleDrop = async (event: DragEvent): Promise<void> => {
  isDragging.value = false
  if (!event.dataTransfer) return

  const files = Array.from(event.dataTransfer.files)
  
  // Define allowed types based on mode
  const isStructured = props.data.dataSourceType === 'structured'
  
  // Filter relevant files
  const validFiles = files.filter(f => {
      if (isStructured) {
          const name = f.name.toLowerCase()
          return name.endsWith('.csv') || name.endsWith('.json')
      }
      return f.type === 'application/pdf'
  })

  const typeLabel = isStructured ? 'CSV or JSON' : 'PDF'

  if (validFiles.length === 0) {
    alert(`Please drop ${typeLabel} files only`)
    return
  }

  if (validFiles.length !== files.length) {
    alert(`Some files were skipped (only ${typeLabel} files are accepted)`)
  }

  await processFiles(validFiles)
}

const processFiles = async (files: File[]): Promise<void> => {
  // Create a copy of existing files array to avoid mutation
  const currentFiles = [...(props.data.uploadedFiles || [])]
  const previousPaths = (props.data.dataSourceValue || "").split(",").filter(Boolean)
  const filePaths: string[] = [...previousPaths]
  
  const isStructured = props.data.dataSourceType === 'structured'
  const allowedTypes = isStructured 
      ? ['.csv', '.json', 'text/csv', 'application/json', 'application/vnd.ms-excel'] 
      : ['application/pdf']

  for (const file of files) {
    // Validate file before upload
    const validation = fileService.validateFile(file, {
      maxSize: 10 * 1024 * 1024, // 10MB
      allowedTypes: allowedTypes
    })

    if (!validation.valid) {
      alert(`${file.name}: ${validation.error}`)
      continue
    }

    // Upload file to server
    try {
      const result = await fileService.uploadFile(file)
      console.log('File uploaded successfully:', result)

      // Add to uploaded files list (store serializable metadata)
      const metadata = {
        name: file.name,
        serverName: result.filename,
        contentHash: result.contentHash,
        serverPath: result.path,
        size: file.size,
        type: file.type,
        lastModified: file.lastModified
      }
      const replaceIndex = currentFiles.findIndex(f => f.name === file.name)
      if (replaceIndex >= 0) {
        currentFiles.splice(replaceIndex, 1, metadata)
        filePaths[replaceIndex] = result.path
      } else {
        currentFiles.push(metadata)
        filePaths.push(result.path)
      }
    } catch (error) {
      console.error('File upload failed:', error)
      const errorMsg = error instanceof ApiError
        ? `${file.name}: Upload failed: ${error.message}`
        : `${file.name}: Failed to upload file. Please try again.`
      alert(errorMsg)
    }
  }

  // Update state with all uploaded files
  emit('update', 'uploadedFiles', currentFiles)

  // Update dataSourceValue with comma-separated file paths for the agent
  // Append new paths to existing ones
  emit('update', 'dataSourceValue', currentFiles.map((f: any, i: number) => f.serverPath || filePaths[i]).filter(Boolean).join(','))
}

const handleFileUpload = async (event: Event): Promise<void> => {
  const target = event.target as HTMLInputElement
  if (!target.files) return

  const files = Array.from(target.files)
  const isStructured = props.data.dataSourceType === 'structured'
  
  const validFiles = files.filter(f => {
      if (isStructured) {
          const name = f.name.toLowerCase()
          return name.endsWith('.csv') || name.endsWith('.json')
      }
      return f.type === 'application/pdf'
  })

  if (validFiles.length > 0) {
    await processFiles(validFiles)
  }

  // Reset file input so the same file can be selected again if needed
  if (fileInput.value) {
    fileInput.value.value = ''
  }
}

const removeFile = (index: number): void => {
  const currentFiles = [...(props.data.uploadedFiles || [])]
  currentFiles.splice(index, 1)
  const remainingPaths = (props.data.dataSourceValue || "").split(",").filter(Boolean)
  remainingPaths.splice(index, 1)
  emit("update", "dataSourceValue", currentFiles.map((f: any, i: number) => f.serverPath || remainingPaths[i]).filter(Boolean).join(","))

  emit('update', 'uploadedFiles', currentFiles)

  // If no files left, clear dataSourceValue
  if (currentFiles.length === 0) {
    emit('update', 'dataSourceValue', '')
    if (fileInput.value) {
      fileInput.value.value = ''
    }
  }
}



const formatFileSize = fileService.formatFileSize
</script>

<style scoped>
.loading-state,
.error-state {
  padding: 20px;
  text-align: center;
  background: #f5f5f5;
  border-radius: 8px;
  color: #666;
}

.error-state {
  color: #d32f2f;
  background: #ffebee;
}

.small-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
  margin-top: 10px;
}

.template-item.compact {
  padding: 10px;
  min-height: auto;
}

.template-item.compact .template-info strong {
  font-size: 13px;
}

/* Fix for radio buttons inheriting 100% width from form-group */
.template-item input[type="radio"] {
  width: 18px;
  height: 18px;
  margin-top: 2px;
  cursor: pointer;
  flex-shrink: 0;
}
</style>

<style scoped>
.aas-instance-list {padding:12px;gap:10px;}
.aas-instance-card {display:grid;grid-template-columns:minmax(0,1fr);border:1px solid #d6e1df;border-radius:10px;background:#fff;transition:border-color .15s,background-color .15s;}
.aas-instance-card.selected {grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);border-color:#10836e;background:#f3faf7;}
.aas-instance-card:focus-within {outline:2px solid #10836e;outline-offset:2px;}
.aas-instance-choice {display:flex;align-items:flex-start;gap:12px;padding:18px 16px;margin:0;cursor:pointer;min-width:0;}
.aas-instance-choice input[type="radio"] {width:18px;height:18px;margin:2px 0 0;flex-shrink:0;accent-color:#10836e;}
.aas-instance-identity {display:flex;flex-direction:column;gap:6px;min-width:0;}
.aas-instance-identity strong {font-size:14px;line-height:1.4;overflow-wrap:anywhere;}
.aas-instance-id {font-size:12px;font-weight:400;color:#52645e;line-height:1.5;overflow-wrap:anywhere;}
.templates-heading {display:flex;gap:4px;align-items:center;}
.templates-heading h3 {font-size:16px;line-height:1.5;margin:0;}
.template-refresh {margin-left:auto;border:1px solid #c9ded4;background:white;color:#245440;border-radius:5px;padding:6px 10px;font-size:12px;cursor:pointer;}
.template-refresh:disabled {opacity:.6;cursor:wait;}
.template-refresh:focus-visible {outline:2px solid #10836e;outline-offset:2px;}
.template-notice {font-size:13px;line-height:1.5;color:#52645e;margin-top:8px;}
.preparation-status {position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:10px;padding:14px 16px;border:1px solid #b7d6cc;border-radius:8px;background:#f2f8f6;color:#245440;line-height:1.5;}
.preparation-spinner {width:16px;height:16px;flex-shrink:0;border:2px solid #b7d6cc;border-top-color:#10836e;border-radius:50%;animation:preparation-spin .8s linear infinite;}
@keyframes preparation-spin {to {transform:rotate(360deg);}}
@media (prefers-reduced-motion:reduce){.preparation-spinner{animation:none;}}
.visually-hidden {position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0;}
@container wizard-input (max-width:640px) {
  .aas-instance-card.selected {grid-template-columns:minmax(0,1fr);}
}
.input-stage {container-type:inline-size;container-name:wizard-input;}
.input-fields {border:0;padding:0;margin:0;min-width:0;width:100%;}
.connection-settings {margin-top:24px;} .connection-settings summary {cursor:pointer;font-weight:600;padding:8px 0;}
.template-version { display:block; font-size:12px; color:#596675; margin:4px 0; }
.template-filters {padding:12px 0;}
.template-search-row {display:flex;gap:8px;align-items:center;}
.template-search-row input {flex:1;min-width:0;}
.template-filter-meta {display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center;justify-content:space-between;margin-top:10px;}
.template-filter-meta p {margin:0;color:#52616c;font-size:13px;}
.template-filter-meta .template-selected-toggle {display:inline-flex;gap:8px;align-items:center;font-weight:400;margin:0;}
.template-selected-toggle input {width:18px;height:18px;flex-shrink:0;}
.template-empty {padding:20px;background:#f5f8f7;border:1px solid #d7e3df;border-radius:6px;line-height:1.5;}
.template-empty p {margin:0 0 10px;}
</style>
