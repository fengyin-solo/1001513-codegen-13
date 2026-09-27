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
      <article v-for="item in statsCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <!-- 信息不完整链路与重复编号：单独点出来，点击可定位到列表记录 -->
    <div class="quality-panel" v-if="stats">
      <h3>数据质量提醒</h3>
      <ul class="quality-list">
        <li v-for="item in stats.incomplete" :key="'inc-' + String(item.id)">
          <span class="tag tag-warn">信息不全</span>
          <span>{{ item['链路编号'] }}（{{ item['所属站点'] }}）</span>
          <span class="muted-text">{{ item.reason }}</span>
          <button class="link" type="button" @click="locateCode(String(item['链路编号']))">定位链路</button>
        </li>
        <li v-for="dup in stats.duplicates" :key="'dup-' + dup['链路编号']">
          <span class="tag tag-reject">编号重复</span>
          <span>{{ dup['链路编号'] }} 出现 {{ dup.count }} 条记录</span>
          <button class="link" type="button" @click="locateCode(dup['链路编号'])">点出重复记录</button>
        </li>
      </ul>
      <p v-if="!stats.incomplete.length && !stats.duplicates.length" class="quality-empty">
        暂无信息不全或编号重复的链路
      </p>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>链路编号</span>
        <input v-model="filters.keyword" placeholder="按链路编号检索" />
      </label>
      <label class="filter-item">
        <span>链路状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="tool-bar">
      <button class="btn primary" type="button" :disabled="!selectedIds.size" @click="openConfirm">
        批量确认缺报{{ selectedIds.size ? `（已选 ${selectedIds.size} 条）` : '' }}
      </button>
      <span class="select-hint">仅「缺报告警」且上报频次、最近上报时刻齐全的链路可勾选；已停用链路不参与批量确认</span>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th style="width: 38px">
            <input
              type="checkbox"
              :checked="allSelectableChecked"
              :disabled="!selectableRows.length"
              title="全选当前页可确认链路"
              @change="toggleSelectAll(($event.target as HTMLInputElement).checked)"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :id="`transmission-row-${String(row.id)}`"
          :key="String(row.id)"
          :class="{
            'is-duplicate': duplicateIds.has(Number(row.id)),
            'is-flash': flashIds.has(Number(row.id)),
          }"
        >
          <td>
            <input
              v-if="selectable(row)"
              v-model="selectedChecks"
              type="checkbox"
              :value="Number(row.id)"
            />
            <input v-else type="checkbox" disabled :title="disableReason(row)" />
          </td>
          <td v-for="column in columns" :key="column">
            <span v-if="column === '链路编号'" class="cell-code">
              {{ row[column] ?? '—' }}
              <button
                v-if="duplicateIds.has(Number(row.id))"
                class="dup-badge"
                type="button"
                :title="`链路编号 ${row[column]} 存在重复记录，点击筛选定位`"
                @click="locateCode(String(row[column]))"
              >重复</button>
            </span>
            <span v-else-if="column === '确认结果'">
              <span v-if="row[column] === '通过'" class="tag tag-pass">通过</span>
              <span v-else-if="row[column] === '退回'" class="tag tag-reject">退回</span>
              <span v-else class="muted-text">—</span>
            </span>
            <span v-else>{{ row[column] ?? '—' }}</span>
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

    <!-- 页脚缺报次数与统计卡片取同一个 stats.missing_total，保证两处对得上 -->
    <footer class="page-foot">
      <span>
        共 {{ total }} 条数据传输记录，缺报次数合计 <strong>{{ stats?.missing_total ?? 0 }}</strong>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 批量确认弹窗：逐条给通过/退回，提交后逐条回显结果 -->
    <div v-if="confirmOpen" class="modal-mask" @click.self="closeConfirm">
      <div class="modal" role="dialog" aria-modal="true" aria-label="批量确认缺报">
        <div class="modal-head">
          <h3>批量确认缺报告警</h3>
          <button class="btn ghost" type="button" @click="closeConfirm">关闭</button>
        </div>
        <div class="modal-body">
          <p class="modal-note">
            已停用链路、上报频次或最近上报时刻为空的链路已在列表中禁选；
            同一批连续重复提交只生效一次，部分失败时已成功的结果会保留。
          </p>
          <table class="confirm-table" v-if="!batchResult">
            <thead>
              <tr><th>链路编号</th><th>所属站点</th><th>缺报次数</th><th>确认意见</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in selectedRows" :key="String(row.id)">
                <td>{{ row['链路编号'] }}</td>
                <td>{{ row['所属站点'] }}</td>
                <td>{{ row['缺报次数'] ?? 0 }}</td>
                <td>
                  <span class="radio-cell">
                    <label><input v-model="decisions[Number(row.id)]" type="radio" :value="'通过'" /> 通过</label>
                    <label><input v-model="decisions[Number(row.id)]" type="radio" :value="'退回'" /> 退回</label>
                  </span>
                </td>
              </tr>
            </tbody>
          </table>

          <div v-else class="result-box">
            <div class="result-head" :class="batchResult.ok ? '' : 'error-text'">
              {{ batchResult.message }}
            </div>
            <ul class="result-list">
              <li v-for="r in batchResult.results" :key="String(r.id)">
                <span class="r-id">#{{ r.id }}</span>
                <span class="r-status" :class="r.status">
                  {{ r.status === 'success' ? `已${r.decision ?? ''}` : r.status === 'skipped' ? '已跳过' : '失败' }}
                </span>
                <span>{{ r.message }}</span>
              </li>
            </ul>
          </div>
        </div>
        <div class="modal-foot">
          <template v-if="!batchResult">
            <button class="btn" type="button" @click="closeConfirm">取消</button>
            <button class="btn primary" type="button" :disabled="submitting" @click="submitConfirm">
              {{ submitting ? '提交中…' : '提交确认结果' }}
            </button>
          </template>
          <template v-else>
            <button class="btn" type="button" @click="closeConfirm">完成并返回列表</button>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type Decision = '通过' | '退回'

interface IncompleteItem {
  id: number
  链路编号: string
  所属站点: string
  链路状态: string
  missing_fields: string[]
  reason: string
}
interface DuplicateItem {
  链路编号: string
  ids: number[]
  count: number
}
interface Stats {
  active_count: number
  alarm_count: number
  missing_total: number
  incomplete: IncompleteItem[]
  duplicates: DuplicateItem[]
}
interface BatchResultItem {
  id: number
  status: 'success' | 'failed' | 'skipped'
  decision: Decision | null
  message: string
  entry: Row | null
}
interface BatchResult {
  ok: boolean
  message: string
  success_count: number
  failed_count: number
  skipped_count: number
  token: string | null
  results: BatchResultItem[]
}

const ENDPOINT = '/api/transmission'
const columns = ['链路编号', '所属站点', '传输方式', '上报频次', '最近上报时刻', '缺报次数', '链路带宽', '链路状态', '确认结果']
const actions = ['开通链路', '确认恢复', '停用链路']
const statuses = ['待开通', '正常上报', '缺报告警', '已停用']
const CONFIRM_REQUIRED = ['上报频次', '最近上报时刻']

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<Stats | null>(null)
const errorMessage = ref('')
const filters = reactive<{ keyword: string; status: string }>({ keyword: '', status: '' })

const selectedChecks = ref<number[]>([])
const decisions = reactive<Record<number, Decision>>({})
const confirmOpen = ref(false)
const submitting = ref(false)
const batchResult = ref<BatchResult | null>(null)
const batchToken = ref('')
const flashIds = ref<Set<number>>(new Set())
let flashTimer: ReturnType<typeof setTimeout> | undefined

const selectedIds = computed(() => new Set(selectedChecks.value))
const duplicateIds = computed(
  () => new Set((stats.value?.duplicates ?? []).flatMap((dup) => dup.ids)),
)
const statsCards = computed(() => [
  { label: '在用链路', value: stats.value?.active_count ?? 0 },
  { label: '缺报链路', value: stats.value?.alarm_count ?? 0 },
  { label: '缺报次数合计', value: stats.value?.missing_total ?? 0 },
])

function isBlank(value: unknown): boolean {
  return value === null || value === undefined || String(value).trim() === ''
}

function rowStatus(row: Row): string {
  return String(row.status ?? row['链路状态'] ?? '')
}

function missingFields(row: Row): string[] {
  return CONFIRM_REQUIRED.filter((field) => isBlank(row[field]))
}

/** 只有缺报告警且关键信息齐全的链路能参与批量确认，已停用/信息不全一律禁选。 */
function selectable(row: Row): boolean {
  return rowStatus(row) === '缺报告警' && missingFields(row).length === 0
}

function disableReason(row: Row): string {
  if (rowStatus(row) === '已停用') return '已停用链路不参与批量确认'
  const missing = missingFields(row)
  if (missing.length) return `缺少${missing.join('、')}，请先补全`
  return '仅缺报告警链路可批量确认'
}

const selectableRows = computed(() => rows.value.filter(selectable))
const allSelectableChecked = computed(
  () =>
    selectableRows.value.length > 0 &&
    selectableRows.value.every((row) => selectedIds.value.has(Number(row.id))),
)
const selectedRows = computed(() =>
  rows.value.filter((row) => selectedIds.value.has(Number(row.id))),
)

function toggleSelectAll(checked: boolean) {
  const selectableIds = selectableRows.value.map((row) => Number(row.id))
  const rest = selectedChecks.value.filter((id) => !selectableIds.includes(id))
  selectedChecks.value = checked ? [...rest, ...selectableIds] : rest
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  void reload()
}

/** 点重复编号/信息不全提醒后，按链路编号筛选并高亮目标行。 */
function locateCode(code: string) {
  filters.keyword = code
  void reload().then(() => {
    flashIds.value = new Set(rows.value.map((row) => Number(row.id)))
    if (flashTimer) clearTimeout(flashTimer)
    flashTimer = setTimeout(() => {
      flashIds.value = new Set()
    }, 2500)
  })
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
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json()) as { ok: boolean; message?: string }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '数据传输动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据传输操作失败'
  }
}

function makeToken(): string {
  return `batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function openConfirm() {
  if (!selectedChecks.value.length) return
  batchResult.value = null
  // 每次打开给一个新令牌；弹窗内重试沿用，提交拿到响应后轮换，保证连续重复提交只生效一次
  batchToken.value = makeToken()
  for (const row of selectedRows.value) {
    const id = Number(row.id)
    if (!decisions[id]) decisions[id] = '通过'
  }
  confirmOpen.value = true
}

function closeConfirm() {
  confirmOpen.value = false
  batchResult.value = null
  // 回到传输链路列表刷新，并清掉已处理的选择
  void reload().then(() => {
    const stillSelectable = new Set(selectableRows.value.map((row) => Number(row.id)))
    selectedChecks.value = selectedChecks.value.filter((id) => stillSelectable.has(id))
  })
}

async function submitConfirm() {
  if (submitting.value) return
  submitting.value = true
  errorMessage.value = ''
  try {
    const items = selectedRows.value.map((row) => ({
      id: Number(row.id),
      decision: decisions[Number(row.id)] ?? '通过',
    }))
    const response = await request(`${ENDPOINT}/missing-confirm/batch`, {
      method: 'POST',
      body: JSON.stringify({ token: batchToken.value, items }),
    })
    if (!response.ok) {
      throw new Error('批量确认请求失败，请稍后重试')
    }
    batchResult.value = (await response.json()) as BatchResult
    // 已成功的条目直接落库，后台先刷新列表；部分失败的条目保留勾选便于继续处理
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量确认提交失败'
  } finally {
    submitting.value = false
    // 响应无论成败都轮换令牌：失败条目再次提交是新的意图，不应被当作重复提交跳过
    batchToken.value = makeToken()
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.keyword.trim()) params.set('keyword', filters.keyword.trim())
  if (filters.status) params.set('status', filters.status)
  const query = params.toString()
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/stats?${query}`),
    ])
    if (!listResponse.ok) throw new Error('传输链路列表读取失败')
    if (!statsResponse.ok) throw new Error('传输链路统计读取失败')
    const payload = (await listResponse.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = (await statsResponse.json()) as Stats
    // 已翻页/筛选掉或不再可确认的选择要清掉，避免把看不见的链路带进批量确认
    const visibleIds = new Set(rows.value.map((row) => Number(row.id)))
    selectedChecks.value = selectedChecks.value.filter(
      (id) => visibleIds.has(id) && rows.value.some((row) => Number(row.id) === id && selectable(row)),
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据传输列表读取失败'
  }
}

onMounted(reload)
</script>
