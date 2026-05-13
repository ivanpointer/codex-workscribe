<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">Workscribe Explorer</div>
      <button
        v-for="table in tables"
        :key="table.name"
        class="nav-item"
        :class="{ active: table.name === selectedTableName }"
        @click="selectTable(table.name)"
      >
        <span>{{ table.name }}</span>
        <span class="count">{{ table.count }}</span>
      </button>
      <button class="nav-item disabled" disabled>
        <span>timeline</span>
        <span class="count">later</span>
      </button>
    </aside>

    <section class="grid-pane">
      <header class="toolbar">
        <div class="title-block">
          <h1>{{ selectedTableName || 'Tables' }}</h1>
          <p>{{ meta?.database_path || 'Loading database metadata...' }}</p>
        </div>
        <input
          v-model="searchText"
          class="search"
          aria-label="Search current table"
          @keyup.enter="loadRows(0)"
        />
      </header>

      <div v-if="error" class="notice error">{{ error }}</div>
      <div v-else-if="loading" class="notice">Loading...</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th v-for="column in visibleColumns" :key="column.name" @click="sortBy(column.name)">
                {{ column.name }}
                <span v-if="sort === column.name">{{ direction === 'asc' ? '↑' : '↓' }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="row.id"
              :class="{ selected: detail?.row?.id === row.id }"
              @click="selectRow(row)"
            >
              <td v-for="column in visibleColumns" :key="column.name">{{ formatCell(row[column.name]) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="rows.length === 0" class="empty">No rows found.</div>
      </div>

      <footer class="pager">
        <button :disabled="offset === 0" @click="loadRows(Math.max(0, offset - limit))">Previous</button>
        <span>{{ pageStart }}-{{ pageEnd }} of {{ total }}</span>
        <button :disabled="offset + limit >= total" @click="loadRows(offset + limit)">Next</button>
      </footer>
    </section>

    <aside class="detail-pane">
      <h2>Selected Row</h2>
      <div v-if="!detail" class="empty">Select a row to inspect values, JSON, and relationships.</div>
      <template v-else>
        <section class="detail-section">
          <h3>Values</h3>
          <dl>
            <template v-for="(value, key) in detail.row" :key="key">
              <dt>{{ key }}</dt>
              <dd>{{ formatDetail(value) }}</dd>
            </template>
          </dl>
        </section>
        <section v-if="Object.keys(detail.parsed_json).length" class="detail-section">
          <h3>JSON</h3>
          <pre>{{ JSON.stringify(detail.parsed_json, null, 2) }}</pre>
        </section>
        <section v-if="detail.related.length" class="detail-section">
          <h3>Related</h3>
          <button
            v-for="relation in detail.related"
            :key="`${relation.table}-${relation.column}`"
            class="relation"
            @click="selectTable(relation.table, { [relation.column]: String(relation.value) })"
          >
            {{ relation.table }} via {{ relation.column }} ({{ relation.count }})
          </button>
        </section>
      </template>
    </aside>
  </main>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { fetchMeta, fetchRowDetail, fetchRows, fetchTables } from './api'

const meta = ref(null)
const tables = ref([])
const selectedTableName = ref('')
const rows = ref([])
const detail = ref(null)
const loading = ref(false)
const error = ref('')
const searchText = ref('')
const filters = ref({})
const limit = 50
const offset = ref(0)
const total = ref(0)
const sort = ref('id')
const direction = ref('desc')
let searchTimer = null

const selectedTable = computed(() => tables.value.find((table) => table.name === selectedTableName.value))
const visibleColumns = computed(() => (selectedTable.value?.columns || []).slice(0, 8))
const pageStart = computed(() => (total.value === 0 ? 0 : offset.value + 1))
const pageEnd = computed(() => Math.min(offset.value + limit, total.value))

onMounted(async () => {
  try {
    meta.value = await fetchMeta()
    const payload = await fetchTables()
    tables.value = payload.tables
    if (tables.value.length) {
      await selectTable(tables.value[0].name)
    }
  } catch (err) {
    error.value = err.message
  }
})

watch(searchText, () => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => loadRows(0), 250)
})

async function selectTable(name, nextFilters = {}) {
  selectedTableName.value = name
  filters.value = nextFilters
  detail.value = null
  sort.value = 'id'
  direction.value = 'desc'
  await loadRows(0)
}

async function loadRows(nextOffset) {
  if (!selectedTableName.value) return
  loading.value = true
  error.value = ''
  try {
    const payload = await fetchRows({
      table: selectedTableName.value,
      limit,
      offset: nextOffset,
      sort: sort.value,
      direction: direction.value,
      search: searchText.value,
      filters: filters.value
    })
    rows.value = payload.rows
    offset.value = payload.offset
    total.value = payload.total
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function selectRow(row) {
  try {
    detail.value = await fetchRowDetail(selectedTableName.value, row.id)
  } catch (err) {
    error.value = err.message
  }
}

function sortBy(column) {
  if (sort.value === column) {
    direction.value = direction.value === 'asc' ? 'desc' : 'asc'
  } else {
    sort.value = column
    direction.value = 'asc'
  }
  loadRows(0)
}

function formatCell(value) {
  if (value === null || value === undefined) return ''
  const text = String(value)
  return text.length > 90 ? `${text.slice(0, 87)}...` : text
}

function formatDetail(value) {
  if (value === null || value === undefined) return ''
  return String(value)
}
</script>
