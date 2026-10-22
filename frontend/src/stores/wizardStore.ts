import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type { WizardData } from '../types'
import { useEnvStore } from './environmentStore'
import { api } from '../services/api'
import { useSharedWebSocket } from '../services/websocketService'

export const useWizardStore = defineStore('wizard', () => {
    const environmentStore = useEnvStore()

    // State
    const currentStep = ref(0)
    const highestVisitedStep = ref(0)
    const isProcessing = ref(false)
    // Flag to prevent echo loops when applying remote updates
    const isRemoteUpdate = ref(false)

    // Heavy result sets are loaded locally over REST (loadExtractedEntities /
    // loadMatchingResults). They also travel through the websocket state-sync,
    // where the backend's empty copy (e.g. pushed on every reconnect, or echoed
    // back) would clobber freshly-loaded data and blank the table. Treat them as
    // locally-authoritative: never overwrite a non-empty local set with a remote one.
    const LOCAL_AUTHORITATIVE_FIELDS = ['extractedEntities', 'matchedProperties']

    // Apply update from WebSocket without triggering send
    function applyRemoteUpdate(key: string, value: any) {
        isRemoteUpdate.value = true

        try {
            if (key === 'currentStep') {
                currentStep.value = value
            } else if (key === 'wizardData') {
                // Full object update — keep local result sets unless they're empty here.
                const merged = { ...wizardData.value, ...value }
                for (const f of LOCAL_AUTHORITATIVE_FIELDS) {
                    const local = (wizardData.value as any)[f]
                    if (Array.isArray(local) && local.length > 0) {
                        merged[f] = local
                    }
                }
                wizardData.value = merged
            } else if (key.startsWith('wizardData.')) {
                const field = key.split('.')[1]
                if (field && field in wizardData.value) {
                    // Don't let a remote empty result set wipe a populated local one.
                    const local = (wizardData.value as any)[field]
                    const wipingLocal = LOCAL_AUTHORITATIVE_FIELDS.includes(field) &&
                        Array.isArray(local) && local.length > 0 &&
                        (!Array.isArray(value) || value.length === 0)
                    if (!wipingLocal) {
                        (wizardData.value as any)[field] = value
                    }
                }
            }
        } finally {
            // Reset flag after update is applied
            // Use setTimeout to ensure watchers have fired (and skipped) before resetting
            setTimeout(() => {
                isRemoteUpdate.value = false
            }, 0)
        }
    }

    const wizardData = ref<WizardData>({
        // Input stage data
        viewMode: 'shop-floor', // 'shop-floor' | 'wizard'
        mode: 'create',
        submodelTemplate: [],
        aasServerEndpoint: environmentStore.aasServerUrl,
        aasUIEndpoint: environmentStore.aasUiUrl,
        targetAAS: '',
        dataSourceType: 'url',
        dataSourceValue: '',
        uploadedFiles: [],

        // Extraction stage data
        extractedEntities: [],
        isExtracting: false,
        editedEntitiesFile: null,
        extractionConfigurations: [],
        chosenConfiguration: '',
        extractionWarnings: [],

        // Matching stage data
        matchedProperties: [],
        isMatching: false,

        // Generation stage data
        isGenerating: false,
        generationComplete: false,
        populationResult: null,
        populationError: null,

        pendingAgentQuestion: '',

        // Shop Floor
        assets: [],
        connections: []
    })

    function setHydrating(active: boolean) {
        if (active) isRemoteUpdate.value = true
        else setTimeout(() => { isRemoteUpdate.value = false }, 0)
    }

    // Getters
    const canProceed = computed(() => {
        if (currentStep.value === 0) {
            const hasTemplates = wizardData.value.mode === 'edit' || (Array.isArray(wizardData.value.submodelTemplate)
                ? wizardData.value.submodelTemplate.length > 0
                : !!wizardData.value.submodelTemplate)

            return hasTemplates &&
                !!wizardData.value.aasServerEndpoint &&
                !!wizardData.value.targetAAS &&
                ((wizardData.value.dataSourceType === 'url' && !!wizardData.value.dataSourceValue) ||
                    (wizardData.value.dataSourceType === 'text' && !!wizardData.value.dataSourceValue) ||
                    ((wizardData.value.dataSourceType === 'pdf' || wizardData.value.dataSourceType === 'structured') && wizardData.value.uploadedFiles && wizardData.value.uploadedFiles.length > 0))
        }
        if (currentStep.value === 1) {
            return wizardData.value.extractedEntities.length > 0
        }
        if (currentStep.value === 2) {
            return wizardData.value.matchedProperties.length > 0
        }
        return true
    })

    const workflowBusy = computed(() => isProcessing.value || wizardData.value.isExtracting ||
        wizardData.value.isMatching || wizardData.value.isGenerating)
    function canVisitStep(step: number) {
        return Number.isInteger(step) && step >= 0 && step <= Math.max(currentStep.value, highestVisitedStep.value) && step < 4
    }
    watch(currentStep, step => {
        highestVisitedStep.value = Math.max(highestVisitedStep.value, step)
    }, { flush: 'sync' })

    async function resetWorkflow(filename: string | null) {
        if (workflowBusy.value) throw new Error('Wait for the current stage to finish before resetting.')
        isProcessing.value = true
        try {
            await api.post('/api/wizard/reset', {
                filename,
                uploads: (wizardData.value.uploadedFiles || []).map(file => (file as any).serverName || file.name),
                aas_id_short: wizardData.value.updateId ? `update_${wizardData.value.updateId}` : wizardData.value.targetAAS || null,
            })
            resetPopulation()
        } finally {
            isProcessing.value = false
        }
    }

    // Actions
    function setStep(step: number) {
        if (!Number.isInteger(step) || step < 0 || step > 3) return
        // Viewing an executed stage does not execute it again.
        if (canVisitStep(step)) {
            currentStep.value = step
            return
        }

        // Logic check for forward navigation
        // Step 1 (Extraction) requires valid inputs
        const hasValidInputs =
            (wizardData.value.mode === 'edit' || (Array.isArray(wizardData.value.submodelTemplate) ? wizardData.value.submodelTemplate.length > 0 : !!wizardData.value.submodelTemplate)) &&
            !!wizardData.value.aasServerEndpoint &&
            !!wizardData.value.targetAAS &&
            ((wizardData.value.dataSourceType === 'url' && !!wizardData.value.dataSourceValue) ||
                (wizardData.value.dataSourceType === 'text' && !!wizardData.value.dataSourceValue) ||
                ((wizardData.value.dataSourceType === 'pdf' || wizardData.value.dataSourceType === 'structured') && wizardData.value.uploadedFiles && wizardData.value.uploadedFiles.length > 0))

        if (step >= 1 && !hasValidInputs) {
            return // Input stage not complete
        }

        // Step 2 (Matching) requires extracted entities
        const hasEntities = wizardData.value.extractedEntities.length > 0
        if (step >= 2 && !hasEntities) {
            return // Extraction not complete
        }

        // Step 3 (Generation) requires matched properties
        const hasMatches = wizardData.value.matchedProperties.length > 0
        if (step >= 3 && !hasMatches) {
            return // Matching not complete
        }

        currentStep.value = step
    }

    // Watch for critical input changes to reset downstream data
    watch(
        () => [
            wizardData.value.uploadedFiles,
            wizardData.value.dataSourceValue,
            wizardData.value.targetAAS,
            wizardData.value.mode,
            wizardData.value.dataSourceType,
            wizardData.value.submodelTemplate,
            wizardData.value.aasServerEndpoint
        ],
        () => {
            if (isRemoteUpdate.value) return

            highestVisitedStep.value = 0
            currentStep.value = 0
            wizardData.value.updateId = null
            wizardData.value.updateReview = null

            // Always drop a stale edited-entities pointer when inputs change. It is
            // persisted (persist:true) and previously survived across unrelated
            // sessions, leaking a wrong-domain "use this edited file" instruction
            // into the agent prompt and derailing extraction.
            wizardData.value.editedEntitiesFile = null
            wizardData.value.extractionWarnings = []
            wizardData.value.extractionConfigurations = []
            wizardData.value.chosenConfiguration = ""

            // If critical inputs change, invalidate downstream results
            if (wizardData.value.extractedEntities.length > 0 || wizardData.value.matchedProperties.length > 0) {
                wizardData.value.extractedEntities = []
                wizardData.value.matchedProperties = []
                wizardData.value.matchingProgress = null
                wizardData.value.isExtracting = false
                wizardData.value.isMatching = false
                wizardData.value.isGenerating = false
                wizardData.value.generationComplete = false
                wizardData.value.populationResult = null
                wizardData.value.populationError = null
            }
        },
        { deep: true }
    )

    function nextStep() {
        setStep(currentStep.value + 1)
    }

    watch(() => wizardData.value.matchedProperties, () => {
        wizardData.value.updateReview = null
    }, {deep:true})

    function previousStep() {
        if (currentStep.value > 0) {
            currentStep.value--
        }
    }

    function updateData(key: keyof WizardData, value: any) {
        (wizardData.value as any)[key] = value
    }

    function setProcessing(status: boolean) {
        isProcessing.value = status
    }

    function reset() {
        highestVisitedStep.value = 0
        currentStep.value = 0
        wizardData.value = {
            viewMode: 'shop-floor',
            mode: 'create',
            submodelTemplate: [],
            aasServerEndpoint: environmentStore.aasServerUrl,
            aasUIEndpoint: environmentStore.aasUiUrl,
            targetAAS: '',
            dataSourceType: 'url',
            dataSourceValue: '',
            uploadedFiles: [],
            extractedEntities: [],
            isExtracting: false,
            editedEntitiesFile: null,
            extractionConfigurations: [],
            chosenConfiguration: '',
            extractionWarnings: [],
            matchedProperties: [],
            isMatching: false,
            isGenerating: false,
            generationComplete: false,
            populationResult: null,
            populationError: null,
            pendingAgentQuestion: '',
            assets: [],
            connections: []
        }
    }

    function resetPopulation() {
        highestVisitedStep.value = 0
        currentStep.value = 0
        wizardData.value.pendingAgentQuestion = ''
        wizardData.value.submodelId = undefined
        wizardData.value.submodelIdShort = undefined
        wizardData.value.updateId = null
        wizardData.value.updateReview = null
        // Partial reset: Keep viewMode, assets, connections
        // Reset workflow data
        wizardData.value.mode = 'create'
        wizardData.value.submodelTemplate = []
        wizardData.value.targetAAS = ''
        wizardData.value.dataSourceType = 'url'
        wizardData.value.dataSourceValue = ''
        wizardData.value.uploadedFiles = []

        wizardData.value.extractedEntities = []
        wizardData.value.isExtracting = false
        wizardData.value.editedEntitiesFile = null
        wizardData.value.extractionConfigurations = []
        wizardData.value.chosenConfiguration = ''
        wizardData.value.extractionWarnings = []

        wizardData.value.matchedProperties = []
        wizardData.value.matchingProgress = null
        wizardData.value.isMatching = false

        wizardData.value.isGenerating = false
        wizardData.value.generationComplete = false
        wizardData.value.populationResult = null
        wizardData.value.populationError = null
    }

    function enterWizard(mode: 'create' | 'edit', aasId: string = '') {
        wizardData.value.viewMode = 'wizard'
        wizardData.value.mode = mode
        wizardData.value.targetAAS = aasId
        // Reset steps if starting fresh (optional, maybe keep state?)
        // currentStep.value = 0 
    }

    function exitWizard() {
        wizardData.value.viewMode = 'shop-floor'
        // Optional: clear data?
    }

    // Watchers for State Sync
    watch(currentStep, (newVal) => {
        if (!isRemoteUpdate.value) {
            useSharedWebSocket().sendStateUpdate('currentStep', newVal)
        }
    })

    watch(wizardData, (newVal) => {
        if (!isRemoteUpdate.value) {
            useSharedWebSocket().sendStateUpdate('wizardData', newVal)
        }
    }, { deep: true })

    // Subscribe to incoming state updates
    const { onMessage } = useSharedWebSocket()
    onMessage((data) => {
        if (data.type === 'state_update' && data.key) {
            applyRemoteUpdate(data.key, data.value)
        }
    })

    return {
        // State
        currentStep,
        highestVisitedStep,
        workflowBusy,
        canVisitStep,
        resetWorkflow,
        isProcessing,
        wizardData,

        // Getters
        canProceed,

        // Actions
        setStep,
        nextStep,
        previousStep,
        updateData,
        setProcessing,
        reset,
        resetPopulation,
        applyRemoteUpdate,
        setHydrating,
        enterWizard,
        exitWizard
    }
}, {
    // Persist inputs, results and visited stages. Transient flags and the edited-entities pointer
    // must NOT survive reloads/sessions — a persisted `editedEntitiesFile` from an
    // unrelated session leaked a wrong-domain instruction into the agent prompt,
    // and persisted `isExtracting`/`isMatching` would restore a stuck spinner.
    persist: {
        // Restoring the same workflow is not an input change. Let queued
        // watchers flush before ending hydration, just like remote updates.
        beforeHydrate: ({ store }) => store.setHydrating(true),
        afterHydrate: ({ store }) => store.setHydrating(false),
        omit: [
            'isProcessing',
            'wizardData.isExtracting',
            'wizardData.isMatching',
            'wizardData.matchingProgress',
            'wizardData.isGenerating',
            'wizardData.editedEntitiesFile',
            'wizardData.pendingAgentQuestion',
        ],
    },
})
