<template>
  <n-tooltip trigger="hover" :show-arrow="true" placement="top">
    <template #trigger>
      <div class="positions-display-wrapper">
        <span class="positions-display">{{ displayText }}</span>
        <span v-if="locations.length > truncateAt" class="expand-indicator">
          <svg class="expand-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </span>
      </div>
    </template>
    <div class="positions-tooltip">
      <div class="tooltip-header">
        <span class="tooltip-title">全部位置 ({{ locations.length }})</span>
      </div>
      <div class="tooltip-content">
        <div
          v-for="(loc, index) in locations"
          :key="`${loc.start}-${loc.end}-${index}`"
          class="position-item"
        >
          <span class="position-number">{{ index + 1 }}.</span>
          <span class="position-range">{{ loc.start }}-{{ loc.end }}</span>
        </div>
      </div>
    </div>
  </n-tooltip>
</template>

<script setup>
/**
 * @file DisplayPositions.vue
 * @description 一个用于显示敏感词位置列表的组件。
 *
 * 当位置数量较多时，它会截断列表并显示一个摘要（例如 "1-3, 5-7 ... (+3 more)"）。
 * 完整的列表会在鼠标悬停时通过工具提示显示。
 */
import { computed } from 'vue';
import { NTooltip } from 'naive-ui';

const props = defineProps({
  /**
   * 敏感词位置的数组。
   * @type {Array<{start: number, end: number}>}
   * @example [{start: 3, end: 5}, {start: 103, end: 105}]
   */
  locations: {
    type: Array,
    required: true,
    default: () => [],
  },
  /**
   * 在主视图中显示的位置数量的截断阈值。
   * 超过此数量的其余位置将在工具提示中显示。
   * @type {number}
   */
  truncateAt: {
    type: Number,
    default: 5,
  },
});

/**
 * 计算用于显示的截断后的位置字符串。
 * 如果位置数量超过 `truncateAt` 阈值，则显示摘要信息（例如 "1-3, 5-7 ... (+3 more)"）。
 * @returns {string} 格式化后的位置字符串。
 */
const displayText = computed(() => {
  if (!props.locations || props.locations.length === 0) {
    return '无';
  }

  const displayedLocations = props.locations.slice(0, props.truncateAt);
  const positionStrings = displayedLocations.map((loc) => `${loc.start}-${loc.end}`);
  const mainText = positionStrings.join(', ');

  if (props.locations.length > props.truncateAt) {
    const moreCount = props.locations.length - props.truncateAt;
    return `${mainText} ... (+${moreCount} more)`;
  }

  return mainText;
});
</script>

<style scoped>
.positions-display-wrapper {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: help;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all 0.2s ease;
}

.positions-display-wrapper:hover {
  background-color: #f0f7ff;
}

.positions-display {
  color: #0066cc;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 12px;
  line-height: 1.4;
  word-break: break-all;
  flex: 1;
}

.expand-indicator {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  color: #0066cc;
  opacity: 0.6;
  transition: opacity 0.2s ease;
}

.positions-display-wrapper:hover .expand-indicator {
  opacity: 1;
}

.expand-icon {
  width: 12px;
  height: 12px;
  stroke-width: 2;
}

.positions-tooltip {
  max-height: 300px;
  overflow-y: auto;
  padding: 0;
  background: #fff;
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  border: 1px solid #e0e0e0;
  min-width: 200px;
}

.tooltip-header {
  padding: 10px 12px;
  background: #f5f7fa;
  border-bottom: 1px solid #e0e0e0;
  border-radius: 6px 6px 0 0;
  position: sticky;
  top: 0;
}

.tooltip-title {
  font-size: 12px;
  font-weight: 600;
  color: #1f2937;
}

.tooltip-content {
  padding: 8px 0;
  max-height: 260px;
  overflow-y: auto;
}

.position-item {
  padding: 8px 12px;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 12px;
  color: #333;
  line-height: 1.6;
  display: flex;
  gap: 8px;
  align-items: center;
  transition: background-color 0.15s ease;
}

.position-item:hover {
  background-color: #f0f7ff;
}

.position-number {
  color: #999;
  min-width: 20px;
  text-align: right;
  font-weight: 500;
}

.position-range {
  color: #0066cc;
  font-weight: 600;
}

/* 滚动条美化 */
.positions-tooltip::-webkit-scrollbar {
  width: 6px;
}

.positions-tooltip::-webkit-scrollbar-track {
  background: transparent;
}

.positions-tooltip::-webkit-scrollbar-thumb {
  background: #d0d0d0;
  border-radius: 3px;
}

.positions-tooltip::-webkit-scrollbar-thumb:hover {
  background: #999;
}
</style>
