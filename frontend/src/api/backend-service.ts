import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function postWorkflow<T = any>(path: string, payload: Record<string, unknown> = {}): Promise<T> {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return await response.json() as T
}

export const previewValueCast = (payload: Record<string, unknown>) =>
  postWorkflow('/api/value_cast/preview', payload)

export const createFormalCastBatch = (payload: Record<string, unknown>) =>
  postWorkflow('/api/value_cast/formal-batches', payload)

export const submitFormalCastBatch = (payload: Record<string, unknown>) =>
  postWorkflow('/api/value_cast/submit', payload)

export const retryFormalCastBatch = (batchNo: string, payload: Record<string, unknown> = {}) =>
  postWorkflow(`/api/value_cast/formal-batches/${encodeURIComponent(batchNo)}/retry`, payload)

export const correctFormalCastBatch = (batchNo: string, payload: Record<string, unknown>) =>
  postWorkflow(`/api/value_cast/formal-batches/${encodeURIComponent(batchNo)}/correct`, payload)

export const normalizeFormalCastBatch = (payload: Record<string, unknown>) =>
  postWorkflow('/api/value_cast/normalize', payload)

export async function getFormalCastReceipt(batchNo: string): Promise<any> {
  const response = await request(`/api/value_cast/receipts/${encodeURIComponent(batchNo)}`)
  if (!response.ok) throw new Error('正式批回执恢复失败')
  return await response.json()
}

export async function downloadFormalCastResult(batchNo: string): Promise<void> {
  const response = await request(`/api/value_cast/receipts/${encodeURIComponent(batchNo)}/download`)
  if (!response.ok) throw new Error('旧结果下载失败')
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${batchNo}-cast-result.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}
