<template>
  <div class="advanced-config">
    <n-form label-placement="top">
      <!-- ============ 区块 1：网络与性能 ============ -->
      <div class="section-header">🌐 网络与性能</div>
      <n-grid :cols="2" :x-gap="12" :y-gap="0">
        <!-- 并发数 - 占满整行 -->
        <n-gi span="2">
          <n-form-item label="并发数" path="concurrency">
            <n-popover trigger="focus" placement="top" :show-arrow="true">
              <template #trigger>
                <n-slider
                  v-model:value="settingsConfig.concurrency"
                  :min="1"
                  :max="50"
                  :step="1"
                  :disabled="disabled"
                />
              </template>
              <div style="max-width: 300px; line-height: 1.6">
                <strong>并发数说明</strong><br />
                <strong>范围：1-50</strong><br />
                同时发送的 HTTP 请求数量。<br />
                • <strong>1-5</strong>：低并发，适合网络不稳定或服务器限制严格的环境<br />
                • <strong>5-15</strong>：推荐值，平衡速度和服务器压力<br />
                • <strong>15-30</strong>：高并发，适合网络稳定且服务器性能好的环境<br />
                • <strong>30-50</strong>：极高并发，可能导致请求被拒绝或 IP 被限制<br />
                💡 并发数越高，扫描速度越快，但也会增加服务器压力
              </div>
            </n-popover>
          </n-form-item>
        </n-gi>

        <!-- 超时时间 + 最大重试次数 -->
        <n-gi span="1">
          <n-form-item label="超时时间 (秒)" path="timeout_seconds">
            <n-popover trigger="focus" placement="top" :show-arrow="true">
              <template #trigger>
                <n-input-number
                  v-model:value="settingsConfig.timeout_seconds"
                  :min="1"
                  :max="120"
                  :step="5"
                  :disabled="disabled"
                  :show-button="false"
                  size="small"
                  style="width: 100%"
                  placeholder="建议 20-50"
                />
              </template>
              <div style="max-width: 300px; line-height: 1.6">
                <strong>超时时间说明</strong><br />
                <strong>范围：1-120 秒</strong><br />
                • <strong>1-10</strong>：快速超时，适合网络快速的环境<br />
                • <strong>20-50</strong>：推荐值，适合大多数 API 服务<br />
                • <strong>50-120</strong>：网络较慢或大模型处理时间长时使用<br />
                💡 超时过短会导致请求中断，过长会影响扫描效率
              </div>
            </n-popover>
          </n-form-item>
        </n-gi>

        <n-gi span="1">
          <n-form-item label="最大重试次数" path="max_retries">
            <n-popover trigger="focus" placement="top" :show-arrow="true">
              <template #trigger>
                <n-input-number
                  v-model:value="settingsConfig.max_retries"
                  :min="1"
                  :max="10"
                  :step="1"
                  :disabled="disabled"
                  :show-button="false"
                  size="small"
                  style="width: 100%"
                  placeholder="建议 3-5 次"
                />
              </template>
              <div style="max-width: 300px; line-height: 1.6">
                <strong>最大重试次数说明</strong><br />
                <strong>范围：1-10</strong><br />
                • <strong>1-3 次</strong>：快速扫描，适合网络稳定的环境<br />
                • <strong>3-5 次</strong>：推荐值，平衡速度和可靠性<br />
                • <strong>5-10 次</strong>：网络不稳定时使用，增加成功率<br />
                💡 每次重试间隔会加入随机抖动以避免请求堆积
              </div>
            </n-popover>
          </n-form-item>
        </n-gi>

        <!-- 分块大小 - 占满整行 -->
        <n-gi span="2">
          <n-form-item label="分块大小 (字符)" path="chunk_size">
            <n-popover trigger="focus" placement="top" :show-arrow="true">
              <template #trigger>
                <n-input-number
                  v-model:value="settingsConfig.chunk_size"
                  :min="100"
                  :max="1000000"
                  :step="100"
                  :disabled="disabled"
                  :show-button="false"
                  size="small"
                  style="width: 100%"
                  placeholder="建议 20000-50000"
                />
              </template>
              <div style="max-width: 300px; line-height: 1.6">
                <strong>分块大小说明</strong><br />
                <strong>范围：100-1,000,000 字符</strong><br />
                • <strong>100-1,000</strong>：极小块，用于精细扫描<br />
                • <strong>1,000-10,000</strong>：小块，如果频繁遇到 Token 限制，可使用此值<br />
                • <strong>10,000-20,000</strong>：平衡方案，适合混合内容<br />
                • <strong>20,000-50,000</strong>：推荐值，可显著减少请求数<br />
                • <strong>50,000-1,000,000</strong>：大块，适合处理长文本<br />
                💡 更大的块可以一次扫描更多文本，但如果超过模型上下文限制会自动分割
              </div>
            </n-popover>
          </n-form-item>
        </n-gi>

        <!-- 系统代理 - 横向布局 -->
        <n-gi span="2">
          <n-form-item label="系统代理" path="use_system_proxy" class="horizontal-form-item">
            <n-popover trigger="hover" placement="top" :show-arrow="true">
              <template #trigger>
                <n-switch v-model:value="settingsConfig.use_system_proxy" :disabled="disabled">
                  <template #checked> 开启 </template>
                  <template #unchecked> 关闭 </template>
                </n-switch>
              </template>
              <div style="max-width: 300px; line-height: 1.6">
                <strong>系统代理说明</strong><br />
                是否使用操作系统的代理设置进行网络请求。<br />
                • <strong>开启</strong>：所有网络请求将通过系统配置的代理服务器。<br />
                • <strong>关闭</strong>：网络请求将直接发送，不使用任何代理。<br />
                💡 如果你处于需要代理才能访问外部网络的环境（如公司内网），请开启此选项。
              </div>
            </n-popover>
          </n-form-item>
        </n-gi>
      </n-grid>

      <!-- ============ 区块 2：算法精度微调 ============ -->
      <div class="section-header">⚙️ 算法精度微调</div>
      <n-grid :cols="2" :x-gap="12" :y-gap="0">
        <!-- 重叠大小 -->
        <n-gi span="1">
          <n-form-item label="边界重叠 (字符)" path="overlap_size">
            <n-popover trigger="focus" placement="top" :show-arrow="true">
              <template #trigger>
                <n-input-number
                  v-model:value="settingsConfig.overlap_size"
                  :min="0"
                  :max="1000"
                  :step="1"
                  :disabled="disabled"
                  :show-button="false"
                  size="small"
                  style="width: 100%"
                  placeholder="建议 15"
                />
              </template>
              <div style="max-width: 300px; line-height: 1.6">
                <strong>边界重叠说明 (防漏检)</strong><br />
                <strong>范围：0-1000 字符</strong><br />
                二分切分时的重叠安全区，防止敏感词被分割。<br />
                • <strong>15</strong>：推荐值，覆盖长词<br />
                • <strong>0-10</strong>：较小重叠，适合短敏感词<br />
                • <strong>20-50</strong>：更安全但会增加重复检测<br />
                💡 中文检测设置为 15 即可。建议设为最大敏感词长度的 2 倍。
              </div>
            </n-popover>
          </n-form-item>
        </n-gi>

        <!-- 切换阈值 (新增) -->
        <n-gi span="1">
          <n-form-item label="切换阈值 (字符)" path="algorithm_switch_threshold">
            <n-popover trigger="focus" placement="top" :show-arrow="true">
              <template #trigger>
                <n-slider
                  v-model:value="settingsConfig.algorithm_switch_threshold"
                  :min="20"
                  :max="100"
                  :step="1"
                  :disabled="disabled"
                />
              </template>
              <div style="max-width: 300px; line-height: 1.6">
                <strong>切换阈值说明</strong><br />
                <strong>范围：20-100 字符</strong><br />
                当文本片段小于此长度时，启动微观精确扫描。<br />
                • <strong>30-40</strong>：推荐值，平衡二分和精确定位<br />
                • <strong>20-30</strong>：更多使用精确定位，速度较慢<br />
                • <strong>40-60</strong>：更多使用二分查找，速度较快<br />
                <br />
                <strong style="color: #ff6b6b">⚠️ 重要：必须满足 threshold > 2 × overlap</strong><br />
                当前：{{ settingsConfig.algorithm_switch_threshold }} >
                {{
                  settingsConfig.overlap_size * 2
                }}
                <span
                  v-if="
                    settingsConfig.algorithm_switch_threshold >
                    settingsConfig.overlap_size * 2
                  "
                  style="color: #52c41a"
                  >✓ 安全</span
                >
                <span v-else style="color: #ff6b6b">✗ 危险（可能死循环）</span>
              </div>
            </n-popover>
          </n-form-item>
        </n-gi>

      </n-grid>

      <!-- 保存按钮 -->
      <div class="action-buttons">
        <div v-if="!isThresholdValid" class="validation-warning">
          ⚠️ 切换阈值必须大于 2 × 重叠大小，否则会导致死循环
        </div>
        <div class="buttons-wrapper">
          <n-button type="primary" ghost :disabled="disabled" size="medium" @click="handleReset">
            重置为默认
          </n-button>
          <n-button
            type="primary"
            :loading="settingsConfig.isSaving"
            :disabled="disabled || !isThresholdValid"
            size="medium"
            @click="handleSave"
          >
            保存高级设置
          </n-button>
        </div>
      </div>
    </n-form>
  </div>
</template>

<script setup>
/**
 * @file AdvancedConfig.vue
 * @description 高级设置配置组件（精简版）。
 *
 * 该组件提供用于调整应用核心行为的表单字段，分为两个区块：
 * 
 * 区块 1：网络与性能
 * - 并发数、超时时间、最大重试次数、分块大小、系统代理
 * 
 * 区块 2：算法精度微调
 * - 边界重叠、切换阈值（新增）
 *
 * 前端隐藏的参数（后端仍支持通过 JSON 配置）：
 * - 重试抖动（jitter）：后端默认 0.5，可通过 config/settings/default.json 修改
 * - 最小粒度（min_granularity）：后端默认 1，可通过 config/settings/default.json 修改
 * - Token 上限（token_limit）：后端默认 20，可通过 config/settings/default.json 修改
 * - 文本分割符（delimiter）：后端默认 \n，可通过 config/settings/default.json 修改
 */
import { storeToRefs } from 'pinia';
import { computed } from 'vue';
import {
  NForm,
  NFormItem,
  NGrid,
  NGi,
  NSlider,
  NInputNumber,
  NSwitch,
  NButton,
  NPopover,
  useMessage,
} from 'naive-ui';
import { useRootStore } from '../../stores/rootStore';

defineProps({
  disabled: {
    type: Boolean,
    default: false,
  },
});

const rootStore = useRootStore();
const message = useMessage();

const { settingsConfig } = storeToRefs(rootStore);

/**
 * 计算切换阈值是否有效
 * 必须满足：algorithm_switch_threshold > 2 * overlap_size
 */
const isThresholdValid = computed(() => {
  return settingsConfig.value.algorithm_switch_threshold > settingsConfig.value.overlap_size * 2;
});

/**
 * 保存高级设置
 */
const handleSave = async () => {
  // 验证阈值
  if (!isThresholdValid.value) {
    message.error(
      `❌ 切换阈值必须大于 2 × 重叠大小 (当前：${settingsConfig.value.algorithm_switch_threshold} ≤ ${settingsConfig.value.overlap_size * 2})`
    );
    return;
  }

  try {
    await rootStore.saveSettings();
    message.success('✅ 高级设置已保存');
  } catch (error) {
    console.error('[AdvancedConfig] 保存失败:', error);
    message.error(`❌ 保存失败: ${error.message}`);
  }
};

/**
 * 重置为默认值
 */
const handleReset = async () => {
  try {
    // 创建一个包含默认值的对象
    const defaultSettings = {
      concurrency: 15,
      timeout_seconds: 30,
      max_retries: 3,
      chunk_size: 30000,
      use_system_proxy: true,
      overlap_size: 12,
      algorithm_switch_threshold: 35,
    };

    // 遍历并更新 store 中的每个字段
    for (const key in defaultSettings) {
      rootStore.updateSettingField(key, defaultSettings[key]);
    }

    // 保存重置后的配置
    await rootStore.saveSettings();
    message.success('✅ 已重置为默认值并保存');
  } catch (error) {
    console.error('[AdvancedConfig] 重置失败:', error);
    message.error(`❌ 重置失败: ${error.message}`);
  }
};
</script>

<style scoped>
.advanced-config {
  width: 100%;
}

.section-header {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  margin: 16px 0 10px 0; /* 减小垂直外边距 */
  padding-bottom: 6px;
  border-bottom: 1px solid #e0e6ed;
}

.section-header:first-of-type {
  margin-top: 0;
}

:deep(.n-form-item) {
  margin-bottom: 0 !important;
}

:deep(.n-form-item__label) {
  margin-bottom: 4px;
  font-size: 13px;
  font-weight: 500;
}

:deep(.n-form-item__content) {
  font-size: 13px;
}

/* 新增：用于水平布局的样式 */
.horizontal-form-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 4px 0; /* 增加一点内边距以保持对齐 */
}

.horizontal-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--n-label-text-color);
  margin-right: 12px;
}

.action-buttons {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 4px; /* 大幅减小与上方元素的间距 */
}

.validation-warning {
  color: #ff6b6b;
  font-size: 12px;
  line-height: 1.4;
  flex-basis: 100%;
  order: 1;
}

.buttons-wrapper {
  display: flex;
  gap: 8px;
  order: 2;
  margin-left: auto;
}

.validation-warning + .buttons-wrapper {
  margin-top: 4px;
  width: 100%;
  justify-content: flex-end;
}
</style>
