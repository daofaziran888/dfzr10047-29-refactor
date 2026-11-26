<template>
  <section class="cast-panel" data-testid="value-cast-panel">
    <div class="cast-panel-head">
      <div>
        <h3>展平取值转型工作台</h3>
        <p>预览只读本次结果；正式批固化输入与规则快照，失败证据按原元素位置展开并写入坏行隔离。</p>
      </div>
      <span v-if="currentBatchNo" class="current-batch" data-testid="current-batch">
        本次可继续正式批：<strong>{{ currentBatchNo }}</strong>
      </span>
    </div>

    <div class="cast-form-grid">
      <label>
        <span>转型规则</span>
        <input v-model="form.castNo" data-testid="cast-no" />
      </label>
      <label>
        <span>正式批号</span>
        <input v-model="form.formalBatchNo" data-testid="formal-batch-no" />
      </label>
      <label>
        <span>关联投递批次</span>
        <input v-model="form.intakeBatch" data-testid="intake-batch" />
      </label>
      <label>
        <span>字段名</span>
        <input v-model="form.field" data-testid="cast-field" />
      </label>
      <label>
        <span>单位归一来源</span>
        <input v-model="form.channel" data-testid="normalize-channel" />
      </label>
      <label>
        <span>命中日期</span>
        <input v-model="form.hitDate" data-testid="normalize-date" />
      </label>
      <label class="wide">
        <span>原文件 / 文档定位</span>
        <input v-model="form.sourceFile" data-testid="source-file" />
      </label>
      <label class="wide">
        <span>展平叶子数据（JSON，保留 element_position）</span>
        <textarea v-model="rowsText" rows="6" data-testid="cast-rows"></textarea>
      </label>
    </div>

    <div class="cast-actions">
      <button class="btn" type="button" data-testid="preview-cast" :disabled="busy" @click="runPreview">
        单次预览
      </button>
      <button class="btn" type="button" data-testid="create-formal-batch" :disabled="busy" @click="createBatch">
        申请正式批
      </button>
      <button class="btn primary" type="button" data-testid="submit-formal-batch" :disabled="busy" @click="submitBatch">
        提交转型并入账
      </button>
      <button class="btn" type="button" data-testid="correct-to-7" :disabled="busy" @click="correctToSeven">
        元素 2 更正为 7
      </button>
      <button class="btn" type="button" data-testid="retry-formal-batch" :disabled="busy" @click="retryBatch">
        原号重试
      </button>
      <button class="btn" type="button" data-testid="normalize-formal-batch" :disabled="busy" @click="normalizeBatch">
        单位归一
      </button>
      <button class="btn ghost" type="button" data-testid="recover-receipt" @click="recoverReceipt">
        恢复回执
      </button>
      <button class="btn ghost" type="button" data-testid="download-result" @click="downloadResult">
        下载旧结果
      </button>
    </div>

    <p v-if="message" class="cast-message" data-testid="cast-message">{{ message }}</p>
    <p v-if="errorMessage" class="error-text" data-testid="cast-error">{{ errorMessage }}</p>

    <div v-if="preview" class="cast-result" data-testid="preview-result">
      <h4>预览结果（不写隔离）</h4>
      <div class="result-stats">
        <span>总数 {{ preview.total }}</span>
        <span>成功 {{ preview.success_count }}</span>
        <span>失败 {{ preview.failure_count }}</span>
      </div>
      <ul class="evidence-list">
        <li
          v-for="evidence in previewFailures"
          :key="`preview-${evidence.elementPosition}-${evidence.field}`"
          :data-testid="`preview-failure-element-${evidence.elementPosition}`"
          class="evidence failure"
        >
          <strong>元素 {{ evidence.elementPosition }} · {{ evidence.field }}</strong>
          <span>原文：{{ String(evidence.raw) }}｜原因：{{ evidence.reason }}</span>
          <small>{{ evidence.originalPath }} · {{ evidence.sourceFile }}</small>
        </li>
      </ul>
    </div>

    <div v-if="receipt" class="cast-result" data-testid="formal-receipt">
      <h4>正式批回执 <small>{{ receipt.receipt_no }}</small></h4>
      <div class="result-stats">
        <span data-testid="receipt-batch">正式批 {{ receipt.formal_batch_no }}</span>
        <span>状态 {{ receipt.formal_status || receipt.status }}</span>
        <span>隔离 {{ receipt.quarantined_count }}</span>
        <span>成功 {{ receipt.success_count }}</span>
      </div>
      <ul class="evidence-list">
        <li
          v-for="evidence in receiptFailures"
          :key="`receipt-${receipt.formal_batch_no}-${evidence.elementPosition}-${evidence.field}`"
          :data-testid="`receipt-failure-element-${evidence.elementPosition}`"
          class="evidence failure"
        >
          <strong>元素 {{ evidence.elementPosition }} · {{ evidence.field }}</strong>
          <span>真实输入：{{ String(evidence.raw) }}｜原因：{{ evidence.reason }}</span>
          <small>{{ evidence.sourceFile }} {{ evidence.documentId }}｜隔离证据已展开</small>
        </li>
      </ul>
    </div>

    <div v-if="normalization" class="cast-result" data-testid="normalize-result">
      <h4>单位归一实际值</h4>
      <p>接受正式成功值 {{ normalization.accepted_count }} 条，归一成功 {{ normalization.normalized_count }} 条。</p>
      <ul>
        <li v-for="(item, index) in normalization.normalized" :key="`norm-${index}`">
          元素 {{ item.element_position }}：{{ item.value }} →
          <strong data-testid="normalized-actual-value">{{ item.normalized_value ?? '拒绝归一' }}</strong>
          <small>{{ item.normalize_message }}</small>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import {
  correctFormalCastBatch,
  createFormalCastBatch,
  downloadFormalCastResult,
  getFormalCastReceipt,
  normalizeFormalCastBatch,
  previewValueCast,
  retryFormalCastBatch,
  submitFormalCastBatch,
} from '@/api/backend-service'
import { currentFormalBatch, failureEvidence } from '@/domain/value_cast'

const form = ref({
  castNo: 'VC-003',
  formalBatchNo: 'FC-ELEMENT-2',
  intakeBatch: 'FI-ELEMENT-2',
  field: 'payload_bytes',
  channel: 'sftp-node-03',
  hitDate: '2026-09-02',
  sourceFile: 'FI-ELEMENT-2/original-document.json',
})
const rowsText = ref(JSON.stringify([
  { element_position: 2, field: 'payload_bytes', raw: 'xx' },
], null, 2))

const busy = ref(false)
const message = ref('')
const errorMessage = ref('')
const preview = ref<any>(null)
const submitResult = ref<any>(null)
const receipt = ref<any>(null)
const normalization = ref<any>(null)

const currentBatchNo = computed(() => currentFormalBatch(submitResult.value) || form.value.formalBatchNo)
const previewFailures = computed(() => failureEvidence(preview.value))
const receiptFailures = computed(() => failureEvidence(receipt.value))

function rowsPayload(): Record<string, unknown>[] {
  const parsed = JSON.parse(rowsText.value)
  if (!Array.isArray(parsed)) throw new Error('展平叶子数据必须是 JSON 数组')
  return parsed
}

function basePayload(): Record<string, unknown> {
  return {
    cast_no: form.value.castNo,
    formal_batch_no: form.value.formalBatchNo,
    intake_batch: form.value.intakeBatch,
    channel: form.value.channel,
    hit_date: form.value.hitDate,
    source_file: form.value.sourceFile,
    field: form.value.field,
    rows: rowsPayload(),
  }
}

async function guard(task: () => Promise<void>) {
  busy.value = true
  errorMessage.value = ''
  message.value = ''
  try {
    await task()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  } finally {
    busy.value = false
  }
}

async function runPreview() {
  await guard(async () => {
    preview.value = await previewValueCast(basePayload())
    message.value = preview.value.message || '预览完成，未新增隔离记录'
  })
}

async function createBatch() {
  await guard(async () => {
    const result = await createFormalCastBatch(basePayload())
    if (!result.ok) throw new Error(result.message)
    receipt.value = result.receipt
    message.value = result.message
  })
}

async function submitBatch() {
  await guard(async () => {
    submitResult.value = await submitFormalCastBatch(basePayload())
    if (!submitResult.value.ok) {
      receipt.value = submitResult.value.receipt
      throw new Error(submitResult.value.message)
    }
    receipt.value = submitResult.value.receipt
    message.value = submitResult.value.message
  })
}

async function correctToSeven() {
  await guard(async () => {
    rowsText.value = JSON.stringify([
      { element_position: 2, field: form.value.field, raw: '7' },
    ], null, 2)
    const result = await correctFormalCastBatch(form.value.formalBatchNo, {
      corrections: { 2: '7' },
      cast_no: form.value.castNo,
      rule: { 目标类型: 'int64' },
    })
    if (!result.ok) throw new Error(result.message)
    receipt.value = result.receipt
    message.value = `${result.message}；已把元素 2 的真实输入更正为 7`
  })
}

async function retryBatch() {
  await guard(async () => {
    submitResult.value = await retryFormalCastBatch(form.value.formalBatchNo, basePayload())
    receipt.value = submitResult.value.receipt
    message.value = submitResult.value.message
  })
}

async function normalizeBatch() {
  await guard(async () => {
    normalization.value = await normalizeFormalCastBatch({
      formal_batch_no: form.value.formalBatchNo,
      channel: form.value.channel,
      hit_date: form.value.hitDate,
      field: form.value.field,
    })
    if (!normalization.value.ok) throw new Error(normalization.value.message)
    message.value = normalization.value.message
  })
}

async function recoverReceipt() {
  await guard(async () => {
    const result = await getFormalCastReceipt(form.value.formalBatchNo)
    if (!result.ok) throw new Error('回执不存在')
    receipt.value = result.receipt
    message.value = `已恢复正式批 ${form.value.formalBatchNo} 的回执`
  })
}

async function downloadResult() {
  await guard(async () => {
    await downloadFormalCastResult(form.value.formalBatchNo)
    message.value = '旧结果下载已开始，文件中保留原文件定位信息'
  })
}
</script>

<style scoped>
.cast-panel {
  margin: 16px 0;
  padding: 18px;
  border: 1px solid var(--border-color, #d9e0ea);
  border-radius: 14px;
  background: #fff;
}
.cast-panel-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.cast-panel-head h3 { margin: 0 0 6px; }
.cast-panel-head p { margin: 0; color: #667085; font-size: 13px; }
.current-batch { padding: 6px 10px; border-radius: 999px; background: #eef4ff; color: #1d4ed8; white-space: nowrap; }
.cast-form-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 16px 0; }
.cast-form-grid label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.cast-form-grid .wide { grid-column: 1 / -1; }
.cast-form-grid input, .cast-form-grid textarea { width: 100%; box-sizing: border-box; border: 1px solid #d0d5dd; border-radius: 8px; padding: 8px 10px; font: inherit; }
.cast-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.cast-message { color: #175cd3; margin: 12px 0 0; }
.cast-result { margin-top: 16px; padding-top: 12px; border-top: 1px dashed #d0d5dd; }
.result-stats { display: flex; gap: 14px; flex-wrap: wrap; font-size: 13px; margin: 8px 0; }
.evidence-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
.evidence { padding: 10px 12px; border-radius: 10px; background: #f9fafb; display: grid; gap: 4px; }
.evidence.failure { background: #fef3f2; color: #7a271a; }
.evidence small { color: #667085; }
@media (max-width: 900px) { .cast-form-grid { grid-template-columns: 1fr; } }
</style>
