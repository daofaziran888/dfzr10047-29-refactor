/**
 * 取值转型页面与后端共用的展平字段/结果映射约定。
 * 后端仍保留权威实现；这里只做展示层归一，避免组件里再散写一遍字段别名。
 */

export type Loose = string | number | boolean | null | undefined | Record<string, unknown>

export interface ParsedFlattenField {
  field: string
  rawField: string
  elementPosition: number | null
  elementIndex: number | null
  originalPath: string
}

export interface CastEvidence {
  ok: boolean
  field: string
  raw: unknown
  value: unknown
  reason: string
  elementPosition: number | string | null
  elementIndex: number | null
  originalPath: string
  sourceFile: string
  documentId: string
  rawText: string
  quarantineNo?: string
  conclusion: string
}

const POSITION_KEYS = ['element_position', 'elementPosition', 'position', '原元素位置', '元素位置', '原位置']
const INDEX_KEYS = ['element_index', 'elementIndex', 'index', 'idx']
const PATH_KEYS = ['original_path', 'source_path', 'leaf_path', 'path', '原始路径', '叶节点路径']
const SOURCE_KEYS = ['source_file', 'original_file', 'file_name', 'filename', '原始文件名', '原文件']
const DOC_KEYS = ['document_id', 'doc_id', '文档编号', '文档ID']

function firstKey(row: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    const value = row[key]
    if (value !== undefined && value !== null && value !== '') return value
  }
  return undefined
}

function toNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '' && /^-?\d+$/.test(value.trim())) {
    return Number(value.trim())
  }
  return null
}

export function parseFlattenedField(field: unknown, defaultPosition?: unknown): ParsedFlattenField {
  if (field && typeof field === 'object') {
    const row = field as Record<string, unknown>
    const name = String(firstKey(row, ['field', 'name', 'field_name', '字段', '字段名']) ?? 'value')
    const index = toNumber(firstKey(row, INDEX_KEYS))
    let position = toNumber(firstKey(row, POSITION_KEYS) ?? defaultPosition)
    if (position === null && index !== null) position = index
    return {
      field: name,
      rawField: name,
      elementPosition: position,
      elementIndex: index ?? (position === null ? null : position - 1),
      originalPath: String(firstKey(row, PATH_KEYS) ?? name),
    }
  }

  const rawField = String(field ?? '')
  let position = toNumber(defaultPosition)
  let index: number | null = null
  const bracket = rawField.match(/[.\[](\d+)\]?(?:\.|$)/)
  const suffix = rawField.match(/(?:element|elem|index|idx|pos|position|元素|节点)?[#@_：:]?(\d+)$/i)
  if (bracket) {
    index = Number(bracket[1])
    position = index + 1
  } else if (suffix) {
    position = Number(suffix[1])
  }

  return {
    field: rawField.replace(/[.\[]\d+\]?(?=\.|$)/g, '').replace(/[#@_：:]?\d+$/g, '') || rawField,
    rawField,
    elementPosition: position,
    elementIndex: index ?? (position === null ? null : position - 1),
    originalPath: rawField,
  }
}

export function normalizeCastEvidence(input: unknown): CastEvidence {
  const row = (input ?? {}) as Record<string, unknown>
  const position = firstKey(row, POSITION_KEYS) ?? null
  const ok = Boolean(row.ok ?? row.success ?? row.cast_ok ?? false)
  return {
    ok,
    field: String(firstKey(row, ['field', '字段', '失败字段']) ?? 'value'),
    raw: firstKey(row, ['raw', 'raw_value', '原始值', '原始取值']) ?? null,
    value: firstKey(row, ['value', 'cast_value', '转型取值']) ?? null,
    reason: String(firstKey(row, ['reason', 'error', 'error_reason', '失败原因']) ?? ''),
    elementPosition: (position as number | string | null) ?? null,
    elementIndex: toNumber(firstKey(row, INDEX_KEYS)),
    originalPath: String(firstKey(row, PATH_KEYS) ?? ''),
    sourceFile: String(firstKey(row, SOURCE_KEYS) ?? ''),
    documentId: String(firstKey(row, DOC_KEYS) ?? ''),
    rawText: String(firstKey(row, ['raw_text', '原始行文本']) ?? ''),
    quarantineNo: String(row.quarantine_no ?? row.隔离编号 ?? ''),
    conclusion: String(row.转型结论 ?? (ok ? '转型成功' : '转型失败')),
  }
}

export function evidenceList(result: unknown): CastEvidence[] {
  const row = (result ?? {}) as Record<string, unknown>
  const list = row.failure_evidence ?? row.failures ?? row.items ?? row.results ?? []
  return Array.isArray(list) ? list.map(normalizeCastEvidence) : []
}

export function failureEvidence(result: unknown): CastEvidence[] {
  return evidenceList(result).filter((item) => !item.ok)
}

export function currentFormalBatch(result: unknown): string {
  const row = (result ?? {}) as Record<string, unknown>
  const receipt = (row.receipt ?? {}) as Record<string, unknown>
  return String(
    row.continuable_formal_batch_no
      ?? row.current_formal_batch_no
      ?? row.formal_batch_no
      ?? receipt.continuable_formal_batch_no
      ?? receipt.formal_batch_no
      ?? '',
  )
}

export const FLATTENED_FIELD_CONVENTION = 'element-position-v1'
export const parseFlattenField = parseFlattenedField
export const parseFlattenFields = parseFlattenedField
export const mapCastResult = normalizeCastEvidence
export const buildCastResult = normalizeCastEvidence
export const extractCastResult = normalizeCastEvidence
