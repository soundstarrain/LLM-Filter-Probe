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
        <n-button
          v-if="resultKeywords.length > 5"
          size="small"
          type="info"
          @click="showDetailModal = true"
        >
          <template #icon> </template>
          查看全部
        </n-button>
      </div>
    </div>

    <!-- 快速预览（前5个关键词） -->
    <div class="preview-section">
      <div class="table-container">
        <n-data-table
          :columns="previewColumns"
          :data="displayedResults"
          :pagination="false"
          size="small"
          striped
        />
      </div>
    </div>

    <!-- 详情弹窗 -->
    <n-modal
      v-model:show="showDetailModal"
      title="完整检测结果"
      preset="dialog"
      size="large"
      :mask-closable="false"
      style="width: 90%; max-width: 1200px"
    >
      <div class="modal-content">
        <div class="modal-toolbar">
          <n-input-group>
            <n-input
              v-model:value="searchKeyword"
              type="text"
              placeholder="搜索敏感词..."
              clearable
            />
          </n-input-group>
          <span class="modal-count">
            {{ filteredResults.length }} / {{ resultKeywords.length }} 个关键词
          </span>
        </div>

        <div class="modal-table">
          <n-data-table
            :columns="modalColumns"
            :data="pagedResults"
            :pagination="modalPagination"
            size="small"
            striped
          />
        </div>

        <div class="modal-footer">
          <n-button @click="showDetailModal = false">关闭</n-button>
          <n-button type="primary" @click="exportResults"> 导出全部结果 </n-button>
        </div>
      </div>
    </n-modal>

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
 * - 结果的快速预览列表。
 * - 一个包含搜索和分页功能的模态框，用于展示全部结果。
 * - 将结果导出为文本文件的功能。
 */
import { ref, computed, h, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { NButton, NDataTable, NModal, NInput, NInputGroup } from 'naive-ui';
import { useRootStore } from '../stores/rootStore';
import DisplayPositions from './DisplayPositions.vue';

const rootStore = useRootStore();
const { resultKeywords, totalSensitiveCount } = storeToRefs(rootStore);

const isExporting = ref(false);
const exportMessage = ref('');
const exportMessageType = ref('success');
const showDetailModal = ref(false);
const searchKeyword = ref('');

// 分页状态（默认每页 10 条）
const modalPage = ref(1);
const modalPageSize = ref(10);
const modalPageSizes = [10, 20, 50, 100];

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
 * 计算用于主界面快速预览的扫描结果（最多显示前5个关键词）。
 * @returns {Array<object>} 用于数据表的结果数组。
 */
const displayedResults = computed(() => {
  const keywords = resultKeywords.value.slice(0, 5);
  return buildTableData(keywords);
});

/**
 * 计算在“完整结果”模态框中显示的、经过搜索过滤的扫描结果。
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

// 分页后的数据
const pagedResults = computed(() => {
  const start = (modalPage.value - 1) * modalPageSize.value;
  const end = start + modalPageSize.value;
  return filteredResults.value.slice(start, end);
});

// 受控分页对象（Naive UI）
const modalPagination = computed(() => ({
  page: modalPage.value,
  pageSize: modalPageSize.value,
  pageCount: Math.max(1, Math.ceil(filteredResults.value.length / modalPageSize.value) || 1),
  showSizePicker: true,
  pageSizes: modalPageSizes,
  onUpdatePage: (page) => {
    modalPage.value = page;
  },
  onUpdatePageSize: (size) => {
    modalPageSize.value = size;
    modalPage.value = 1; // 切换每页条数时回到第一页
  },
}));

// 搜索或数据变化时，重置到第一页
watch(
  () => [searchKeyword.value, resultKeywords.value.length],
  () => {
    modalPage.value = 1;
  }
);

// 打开弹窗时重置页码
watch(
  () => showDetailModal.value,
  (val) => {
    if (val) modalPage.value = 1;
  }
);

// 预览列（无全局序号偏移）
const previewColumns = [
  { title: '序号', key: 'index', width: 60, render: (_, index) => index + 1 },
  {
    title: '敏感词',
    key: 'keyword',
    width: 150,
    ellipsis: { tooltip: true },
    render: (row) => `"${row.keyword}"`,
  },
  {
    title: '出现次数',
    key: 'count',
    width: 100,
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

// 弹窗列（带全局序号偏移）
const modalColumns = [
  {
    title: '序号',
    key: 'index',
    width: 70,
    align: 'center',
    render: (_, index) => (modalPage.value - 1) * modalPageSize.value + index + 1,
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
/* Styles remain the same */
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
.preview-section {
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
  width: fit-content;
}
.modal-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: 70vh;
}
.modal-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 12px;
  background: #f9f9f9;
  border-radius: 6px;
}
.modal-toolbar :deep(.n-input-group) {
  flex: 1;
}
.modal-count {
  font-size: 12px;
  color: #999;
  white-space: nowrap;
  padding: 0 8px;
}
.modal-table {
  flex: 1;
  overflow: auto;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
}
.modal-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding-top: 12px;
  border-top: 1px solid #e0e0e0;
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
@media (max-width: 768px) {
  .panel-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .header-actions {
    width: 100%;
  }
  .header-actions :deep(.n-button) {
    flex: 1;
  }
  .modal-toolbar {
    flex-direction: column;
  }
  .modal-toolbar :deep(.n-input-group) {
    width: 100%;
  }
  .modal-count {
    width: 100%;
    text-align: right;
  }
}
</style>
