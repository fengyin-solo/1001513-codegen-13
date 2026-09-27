<template>
  <section class="page" data-module="transmission">
    <header class="page-head">
      <div>
        <h2>数据传输管理</h2>
        <p class="page-desc">维护传输链路，围绕链路编号、所属站点、传输方式、上报频次做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记传输链路</button>
        <button class="btn" type="button" @click="exportRows">导出数据传输清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <section v-if="incompleteRows.length" class="notice-panel">
      <h3>缺报要素不全的链路（{{ incompleteRows.length }} 条）</h3>
      <p class="notice-desc">以下链路的上报频次或最近上报时刻为空，无法判断缺报情况，请先补齐资料：</p>
      <ul>
        <li v-for="row in incompleteRows" :key="String(row.id)">
          <strong>{{ row['链路编号'] }}</strong>（{{ row['所属站点'] }}）缺少：{{ (row['缺失字段'] as string[]).join('、') }}
        </li>
      </ul>
    </section>

    <section v-if="duplicateGroups.length" class="notice-panel warning">
      <h3>链路编号重复（{{ duplicateGroups.length }} 组）</h3>
      <p class="notice-desc">点击编号可把这些重复记录从列表里点出来核对：</p>
      <div class="dup-tags">
        <button
          v-for="group in duplicateGroups"
          :key="group['链路编号']"
          class="dup-tag"
          type="button"
          @click="showDuplicate(group['链路编号'])"
        >
          {{ group['链路编号'] }} × {{ group['重复条数'] }}
        </button>
      </div>
    </section>

    <div class="batch-bar">
      <button class="btn primary" type="button" :disabled="!selectedIds.length" @click="openConfirm">
        批量确认缺报（已选 {{ selectedIds.length }} 条）
      </button>
      <span class="batch-hint">已停用的链路不参与批量确认，无法勾选</span>
    </div>

    <section v-if="confirmPanelOpen" class="confirm-panel">
      <h3>批量确认缺报</h3>
      <p class="notice-desc">逐条给出确认结论后一次提交；部分失败时已成功的条目不会回滚。</p>
      <table class="data-table">
        <thead>
          <tr>
            <th>链路编号</th>
            <th>所属站点</th>
            <th>缺报次数</th>
            <th>确认结论</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in confirmRows" :key="String(row.id)">
            <td>{{ row['链路编号'] }}</td>
            <td>{{ row['所属站点'] }}</td>
            <td>{{ row['缺报次数'] ?? '—' }}</td>
            <td>
              <label v-for="option in confirmOptions" :key="option" class="confirm-option">
                <input v-model="confirmChoices[Number(row.id)]" type="radio" :value="option" />{{ option }}
              </label>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="confirm-actions">
        <button class="btn primary" type="button" :disabled="submitting" @click="submitConfirm">
          {{ submitting ? '提交中…' : '提交确认结果' }}
        </button>
        <button class="btn ghost" type="button" :disabled="submitting" @click="closeConfirm">取消</button>
      </div>
      <ul v-if="confirmResults.length" class="confirm-results">
        <li v-for="item in confirmResults" :key="String(item.id)" :class="item.ok ? 'result-ok' : 'result-fail'">
          {{ item.message }}
        </li>
      </ul>
    </section>

    <table class="data-table">
      <thead>
        <tr>
          <th>
            <input
              type="checkbox"
              :checked="allSelectableChecked"
              :disabled="!selectableRows.length"
              @change="toggleAll"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'dup-row': isDuplicate(row) }">
          <td>
            <input
              v-if="row.status !== '已停用'"
              v-model="selectedIds"
              type="checkbox"
              :value="Number(row.id)"
            />
            <span v-else class="disabled-tag" title="已停用链路不参与批量确认">已停用</span>
          </td>
          <td v-for="column in columns" :key="column">
            <span v-if="column === '链路编号' && isDuplicate(row)" class="dup-code">{{ row[column] }}</span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无数据传输数据，可先登记传输链路</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据传输记录 · 缺报合计 {{ missingTotal }} 次</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

interface DuplicateGroup {
  链路编号: string
  重复条数: number
  记录ID: number[]
}

const ENDPOINT = '/api/transmission'
const columns = ["链路编号", "所属站点", "传输方式", "上报频次", "最近上报时刻", "缺报次数", "链路带宽", "链路状态"]
const actions = ["开通链路", "确认恢复", "停用链路"]
const confirmOptions = ["通过", "退回"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 统计卡片与页脚缺报合计共用同一份接口数据，保证两处对得上
const stats = ref([{ label: '在用链路', value: 0 }, { label: '缺报链路', value: 0 }, { label: '今日缺报次数', value: 0 }])
const missingTotal = ref(0)

const selectedIds = ref<number[]>([])
const confirmPanelOpen = ref(false)
const confirmChoices = ref<Record<number, string>>({})
const confirmResults = ref<{ id: number; ok: boolean; message: string }[]>([])
const submitting = ref(false)

const incompleteRows = ref<Record<string, unknown>[]>([])
const duplicateGroups = ref<DuplicateGroup[]>([])

const selectableRows = computed(() => rows.value.filter((row) => row.status !== '已停用'))
const allSelectableChecked = computed(
  () => selectableRows.value.length > 0 && selectableRows.value.every((row) => selectedIds.value.includes(Number(row.id))),
)
const confirmRows = computed(() => rows.value.filter((row) => selectedIds.value.includes(Number(row.id))))
const duplicateCodes = computed(() => new Set(duplicateGroups.value.map((group) => String(group['链路编号']))))

function isDuplicate(row: Row) {
  return duplicateCodes.value.has(String(row['链路编号'] ?? ''))
}

function toggleAll() {
  const ids = selectableRows.value.map((row) => Number(row.id))
  selectedIds.value = allSelectableChecked.value ? [] : ids
}

function showDuplicate(code: string) {
  filters.value = { 链路编号: code }
  void reload()
}

function openConfirm() {
  confirmChoices.value = Object.fromEntries(selectedIds.value.map((id) => [id, '通过']))
  confirmResults.value = []
  confirmPanelOpen.value = true
}

function closeConfirm() {
  confirmPanelOpen.value = false
  confirmResults.value = []
}

async function submitConfirm() {
  if (submitting.value) {
    return
  }
  submitting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/batch-confirm`, {
      method: 'POST',
      body: JSON.stringify({
        items: selectedIds.value.map((id) => ({ id, result: confirmChoices.value[id] ?? '通过' })),
      }),
    })
    const payload = await response.json()
    confirmResults.value = payload.results ?? []
    if (!payload.ok) {
      errorMessage.value = payload.message ?? '部分链路确认未生效，请核对逐条结果'
    }
    // 回到列表刷新：已成功的条目保留在链路列表里，统计与页脚同步更新
    selectedIds.value = []
    await Promise.all([reload(), loadStats(), loadIncomplete(), loadDuplicates()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量确认提交失败'
  } finally {
    submitting.value = false
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '传输链路登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('数据传输动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadStats(), loadIncomplete(), loadDuplicates()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据传输操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('传输链路列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据传输列表读取失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      throw new Error('缺报统计读取失败')
    }
    const payload = await response.json()
    stats.value = [
      { label: '在用链路', value: payload['在用链路'] ?? 0 },
      { label: '缺报链路', value: payload['缺报链路'] ?? 0 },
      { label: '今日缺报次数', value: payload['缺报次数合计'] ?? 0 },
    ]
    missingTotal.value = payload['缺报次数合计'] ?? 0
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缺报统计读取失败'
  }
}

async function loadIncomplete() {
  try {
    const response = await request(`${ENDPOINT}/incomplete`)
    if (!response.ok) {
      throw new Error('缺报要素检查失败')
    }
    const payload = await response.json()
    incompleteRows.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缺报要素检查失败'
  }
}

async function loadDuplicates() {
  try {
    const response = await request(`${ENDPOINT}/duplicates`)
    if (!response.ok) {
      throw new Error('重复编号检查失败')
    }
    const payload = await response.json()
    duplicateGroups.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重复编号检查失败'
  }
}

onMounted(() => {
  void reload()
  void loadStats()
  void loadIncomplete()
  void loadDuplicates()
})
</script>
