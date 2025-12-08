<template>
  <div class="scan-results">
    <div class="panel-header">
      <div class="header-left">
        <h3>检测结果</h3>
        <span class="result-badge">{{ totalSensitiveCount }} 处</span>
        <span v-if="resultKeywords.length > 0" class="keyword-badge"
          >{{ resultKeywords.length }} 词</span
        >
      </div>
      <div class="header-actions">
        <n-input
          v-model:value="searchKeyword"
          type="text"
          placeholder="搜索敏感词..."
          clearable
          style="width: 200px"
        />
        <n-button
          v-if="totalSensitiveCount > 0"
          size="small"
          type="primary"
          :loading="isExporting"
          @click="exportResults"
        >
          <template #icon> </template>
          导出结果
        </n-button>
      </div>
    </div>

    <!-- 【新增】未知状态码统计和敏感词判断依据 -->
    <div v-if="unknownStatusCodeCounts && Object.keys(unknownStatusCodeCounts).length > 0" class="stats-section">
      <div class="stats-header">
        <h4>⚠️ 未知状态码统计</h4>
      </div>
      <div class="stats-content">
        <div v-for="(count, code) in unknownStatusCodeCounts" :key="code" class="stat-item">
          <span class="stat-code">{{ code }}</span>
          <span class="stat-count">出现 {{ count }} 次</span>
        </div>
      </div>
    </div>

    <!-- 【新增】敏感词判断依据 -->
    <div v-if="sensitiveWordEvidence && Object.keys(sensitiveWordEvidence).length > 0" class="evidence-section">
      <div class="evidence-header">
        <h4>敏感词判断依据</h4>
      </div>
      <div class="evidence-content">
        <div v-for="(evidence, key) in sensitiveWordEvidence" :key="key" class="evidence-item">
          <div class="evidence-type" :class="evidence.type">
            {{ evidence.type === 'keyword' ? '关键词' : '状态码' }}
          </div>
          <div class="evidence-value">
            <span v-if="evidence.type === 'keyword'">{{ evidence.value }}</span>
            <span v-else>{{ evidence.value }}</span>
          </div>
          <div v-if="evidence.context" class="evidence-context">
            上下文: {{ evidence.context }}
          </div>
        </div>
      </div>
    </div>

    <!-- 主表格区域（包含分页） -->
    <div class="results-section">
      <div class="table-container">
        <n-data-table
          :columns="tableColumns"
          :data="filteredResults"
          :pagination="tablePagination"
          size="small"
          striped
        />
      </div>
    </div>

    <div v-if="exportMessage" class="export-message" :class="exportMessageType">
      {{ exportMessage }}
    </div>
  </div>
</template>

<script setup>
/**
 * @file ScanResults.vue
 * @description 检测结果显示组件。
 *
 * 该组件负责展示扫描结果，包括：
 * - 结果摘要（总数、关键词数）。
 * - 完整的结果列表，支持搜索、分页和每页条数选择。
 * - 将结果导出为文本文件的功能。
 */
import { ref, computed, h, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { NButton, NDataTable, NInput } from 'naive-ui';
import { useRootStore } from '../stores/rootStore';
import DisplayPositions from './DisplayPositions.vue';

const rootStore = useRootStore();
const { resultKeywords, totalSensitiveCount } = storeToRefs(rootStore);

const isExporting = ref(false);
const exportMessage = ref('');
const exportMessageType = ref('success');
const searchKeyword = ref('');

// 【新增】从 store 获取未知状态码统计和敏感词判断依据
const unknownStatusCodeCounts = computed(() => rootStore.results.unknownStatusCodeCounts || {});
const sensitiveWordEvidence = computed(() => rootStore.results.sensitiveWordEvidence || {});

// 分页状态（默认每页 10 条）
const currentPage = ref(1);
const pageSize = ref(10);
const pageSizes = [10, 20, 50, 100];

/**
 * 根据关键词列表构建用于数据表的数据。
 * @param {string[]} keywords - 敏感关键词列表。
 * @returns {Array<object>} 用于 Naive UI 数据表的数组。
 */
const buildTableData = (keywords) => {
  return keywords.map((keyword) => ({
    keyword,
    locations: rootStore.getLocationsByKeyword(keyword),
    count: rootStore.getLocationsByKeyword(keyword).length,
  }));
};

/**
 * 计算经过搜索过滤的扫描结果。
 * @returns {Array<object>} 用于数据表的结果数组。
 */
const filteredResults = computed(() => {
  const keywords = resultKeywords.value;
  if (!searchKeyword.value.trim()) {
    return buildTableData(keywords);
  }
  const keyword = searchKeyword.value.toLowerCase();
  const filtered = keywords.filter((kw) => kw.toLowerCase().includes(keyword));
  return buildTableData(filtered);
});

// 受控分页对象（Naive UI）
const tablePagination = computed(() => ({
  page: currentPage.value,
  pageSize: pageSize.value,
  pageCount: Math.max(1, Math.ceil(filteredResults.value.length / pageSize.value) || 1),
  itemCount: filteredResults.value.length,
  showSizePicker: true,
  pageSizes: pageSizes,
  prefix: (info) => {
    return `共 ${filteredResults.value.length} 个关键词`;
  },
  onUpdatePage: (page) => {
    currentPage.value = page;
  },
  onUpdatePageSize: (size) => {
    pageSize.value = size;
    currentPage.value = 1; // 切换每页条数时回到第一页
  },
}));

// 搜索或数据变化时，重置到第一页
watch(
  () => [searchKeyword.value, resultKeywords.value.length],
  () => {
    currentPage.value = 1;
  }
);

// 表格列定义
const tableColumns = [
  {
    title: '序号',
    key: 'index',
    width: 70,
    align: 'center',
    render: (_, index) => (currentPage.value - 1) * pageSize.value + index + 1,
  },
  {
    title: '敏感词',
    key: 'keyword',
    width: 180,
    ellipsis: { tooltip: true },
    render: (row) => `"${row.keyword}"`,
  },
  {
    title: '出现次数',
    key: 'count',
    width: 110,
    align: 'center',
    render: (row) => `${row.count} 次`,
  },
  {
    title: '位置',
    key: 'locations',
    ellipsis: { tooltip: false },
    render: (row) => h(DisplayPositions, { locations: row.locations, truncateAt: 5 }),
  },
];

/**
 * 将扫描结果格式化为人类可读的纯文本字符串，用于导出。
 * @returns {string} 格式化后的文本内容。
 */
const formatResultsAsText = () => {
  const keywords = resultKeywords.value;
  const now = new Date();
  const dateStr = now.toLocaleString('zh-CN');

  let text = `扫描结果导出\n`;
  text += `${'='.repeat(60)}\n`;
  text += `导出时间: ${dateStr}\n`;
  text += `总计: ${totalSensitiveCount.value} 个敏感片段，${resultKeywords.value.length} 个关键词\n`;
  text += `${'='.repeat(60)}\n\n`;

  keywords.forEach((keyword, index) => {
    const locations = rootStore.getLocationsByKeyword(keyword);
    text += `敏感词 #${index + 1}: "${keyword}" (共 ${locations.length} 次)\n`;
    text += `位置列表:\n`;
    locations.forEach((loc, locIndex) => {
      text += `  ${locIndex + 1}. ${loc.start}-${loc.end}\n`;
    });
    text += `\n`;
  });

  text += `${'='.repeat(60)}\n`;
  text += `导出完成\n`;

  return text;
};

/**
 * 导出扫描结果为纯文本文件。
 */
const exportResults = async () => {
  if (totalSensitiveCount.value === 0) {
    exportMessage.value = '❌ 没有结果可导出';
    exportMessageType.value = 'error';
    setTimeout(() => (exportMessage.value = ''), 3000);
    return;
  }

  try {
    isExporting.value = true;
    exportMessage.value = '正在导出...';
    exportMessageType.value = 'info';

    const textContent = formatResultsAsText();
    const blob = new Blob([textContent], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const now = new Date();
    const filename = `scan_results_${now.toISOString().slice(0, 19).replace(/[-:T]/g, '')}.txt`;

    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    exportMessage.value = `✅ 导出成功！文件名: ${filename}`;
    exportMessageType.value = 'success';
    setTimeout(() => (exportMessage.value = ''), 3000);
  } catch (error) {
    exportMessage.value = `❌ 导出失败: ${error.message}`;
    exportMessageType.value = 'error';
    setTimeout(() => (exportMessage.value = ''), 3000);
  } finally {
    isExporting.value = false;
  }
};
</script>

<style scoped>
.scan-results {
  display: flex;
  flex-direction: column;
  background: white;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  overflow: hidden;
  height: 100%;
}

.panel-header {
  padding: 16px;
  background: linear-gradient(135deg, #f5f7fa 0%, #f9fafb 100%);
  border-bottom: 1px solid #e0e0e0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #1f2937;
}

.result-badge {
  display: inline-block;
  padding: 4px 12px;
  background: #ef4444;
  color: white;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  min-width: 50px;
  text-align: center;
}

.keyword-badge {
  display: inline-block;
  padding: 4px 12px;
  background: #3b82f6;
  color: white;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  min-width: 50px;
  text-align: center;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.results-section {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}

.table-container {
  flex: 1;
  overflow: auto;
}

.table-container :deep(.n-data-table) {
  width: 100%;
}

.export-message {
  padding: 12px 16px;
  font-size: 13px;
  text-align: center;
  border-top: 1px solid #e0e0e0;
  font-weight: 500;
}

.export-message.success {
  background-color: #f0fdf4;
  color: #166534;
}

.export-message.error {
  background-color: #fef2f2;
  color: #991b1b;
}

.export-message.info {
  background-color: #eff6ff;
  color: #1e40af;
}

/* 【新增】未知状态码统计样式 */
.stats-section {
  padding: 12px 16px;
  background: #fef3c7;
  border-bottom: 1px solid #fcd34d;
}

.stats-header {
  margin-bottom: 8px;
}

.stats-header h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #92400e;
}

.stats-content {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.stat-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: white;
  border-radius: 4px;
  border: 1px solid #fcd34d;
  font-size: 12px;
}

.stat-code {
  font-weight: 600;
  color: #d97706;
}

.stat-count {
  color: #78350f;
}

/* 【新增】敏感词判断依据样式 */
.evidence-section {
  padding: 12px 16px;
  background: #dbeafe;
  border-bottom: 1px solid #93c5fd;
}

.evidence-header {
  margin-bottom: 8px;
}

.evidence-header h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #1e40af;
}

.evidence-content {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.evidence-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 12px;
  background: white;
  border-radius: 4px;
  border: 1px solid #93c5fd;
  font-size: 12px;
}

.evidence-type {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 3px;
  font-weight: 600;
  width: fit-content;
}

.evidence-type.keyword {
  background: #dcfce7;
  color: #166534;
}

.evidence-type.status_code {
  background: #fed7aa;
  color: #92400e;
}

.evidence-value {
  font-weight: 600;
  color: #1f2937;
}

.evidence-context {
  color: #6b7280;
  font-size: 11px;
  margin-top: 2px;
}

@media (max-width: 768px) {
  .panel-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .header-actions {
    width: 100%;
    flex-direction: column;
  }

  .header-actions :deep(.n-input),
  .header-actions :deep(.n-button) {
    width: 100%;
  }
}
</style>


