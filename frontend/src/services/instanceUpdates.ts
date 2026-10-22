import {api, MODEL_BOUND_TIMEOUT} from './api'

export interface UpdateSelection {
  templateId: string
  releaseHash?: string
  targetId: string
  mode: 'add' | 'enrich' | 'migrate' | 'replace'
}
export interface UpdatePreview {
  automatic?: boolean
  categoryAssessment?: {method: string; model?: string; retainedIds: string[]}
  replacementGroups?: Array<{name:string; candidateId:string; replaces:string[]}>
  id: string
  status: string
  reviewHash?: string
  changes: Array<{submodel: string; path: string; action: string; before: any; after: any}>
  conflicts: Array<{path: string; reason: string}>
  validation?: {types: string; templateConformance: string; issues: Array<{path: string; reason: string}>}
  result?: any
}
export const instanceUpdates = {
  async existing(aas: string, endpoint: string) {
    return (await api.get<any>('/api/instance-updates/existing', {params:{aas,endpoint}})).data
  },
  async prepareAutomatic(aas: string, endpoint: string, templateIds: string[]) {
    return (await api.post<UpdatePreview>('/api/instance-updates/prepare', {aas,endpoint,templateIds}, {timeout: MODEL_BOUND_TIMEOUT})).data
  },
  async discover(aas: string, endpoint: string) {
    return (await api.get<any>('/api/instance-updates/discover', {params:{aas,endpoint}})).data
  },
  async prepare(aas: string, endpoint: string, selections: UpdateSelection[] = []) {
    return (await api.post<UpdatePreview>('/api/instance-updates/prepare', {aas,endpoint,selections})).data
  },
  async properties(id: string) {
    return (await api.get<any>(`/api/instance-updates/${id}/properties`)).data
  },
  async review(id: string, results: any[], filename: string, aas: string, endpoint: string) {
    return (await api.post<UpdatePreview>(`/api/instance-updates/${id}/review`, {results,filename,aas,endpoint})).data
  },
  async commit(preview: UpdatePreview, aas?: string, endpoint?: string) {
    return (await api.post<any>(`/api/instance-updates/${preview.id}/commit`, {reviewHash:preview.reviewHash,aas,endpoint})).data
  },
  async restore(id: string) {
    return (await api.post<UpdatePreview>(`/api/instance-updates/${id}/restore`, {})).data
  },
  async reconcile(id: string) {
    return (await api.post<UpdatePreview>(`/api/instance-updates/${id}/reconcile`, {})).data
  },
  async snapshot(id: string) {
    return (await api.get<any>(`/api/instance-updates/${id}/snapshot`)).data
  },
}
