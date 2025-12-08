<template>
  <n-card :bordered="false" size="small">
    <!-- API 设置 -->
    <n-divider style="margin-top: 0; margin-bottom: 12px">
      <span class="divider-text">API 设置</span>
    </n-divider>
    <ConnectionForm />

    <!-- 预设与规则 -->
    <n-divider style="margin: 12px 0 8px">
      <span class="divider-text">预设与规则</span>
    </n-divider>

    <!-- 预设选择器 -->
    <n-form-item label="预设 (Preset)" path="preset">
      <n-select
        :value="settingsConfig.preset"
        :options="presetOptions"
        placeholder="选择预设"
        clearable
        filterable
        @update:value="handlePresetChange"
      >
        <template #header>
          <div class="preset-select-header">
            <span>选择预设配置</span>
          </div>
        </template>
      </n-select>
    </n-form-item>

    <!-- 预设描述 -->
    <div v-if="presetDescription" class="preset-description">
      <strong>预设说明：</strong> {{ presetDescription }}
    </div>

    <!-- 提示信息 -->
    <n-alert
      v-if="!isCustomPreset"
      type="info"
      style="margin-top: 12px; margin-bottom: 12px"
      closable
    >
      <template #icon>

      </template>
      当前为只读预设。如需编辑参数，请切换到 <strong>"Custom"</strong> 预设。
    </n-alert>

    <!-- 自定义预设配置 -->
    <CustomPreset :disabled="!isCustomPreset" />

    <!-- 高级设置 -->
    <n-divider style="margin: 12px 0 8px">
      <span class="divider-text">高级设置</span>
    </n-divider>
    <AdvancedConfig />
  </n-card>
</template>

<script setup>
/**
 * @file Settings.vue
 * @description 设置页面的主容器组件。
 *
 * 该组件整合了所有与设置相关的子组件，包括：
 * - API 连接表单 (ConnectionForm)
 * - 自定义预设配置 (CustomPreset)
 * - 高级算法设置 (AdvancedConfig)
 *
 * 它还包含预设选择器，并根据当前选择的预设动态显示相关信息和组件。
 */
import { onMounted } from 'vue';
import { storeToRefs } from 'pinia';
import { NCard, NDivider, NAlert, NFormItem, NSelect } from 'naive-ui';
import ConnectionForm from './ConnectionForm.vue';
import CustomPreset from './CustomPreset.vue';
import AdvancedConfig from './AdvancedConfig.vue';
import { useRootStore } from '../../stores/rootStore';

const rootStore = useRootStore();

// Destructure reactive state and computed properties from the root store
const { settingsConfig, presetOptions, isCustomPreset, presetDescription } = storeToRefs(rootStore);

/**
 * 处理预设更改
 * @param {string} newPreset - 新选择的预设名称
 */
const handlePresetChange = (newPreset) => {
  rootStore.setPreset(newPreset);
};
</script>

<style scoped>
.divider-text {
  font-size: 13px;
  font-weight: 700;
}

.preset-select-header {
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #333;
  border-bottom: 1px solid #e0e0e0;
}

.preset-description {
  font-size: 12px;
  color: #555;
  background-color: #f5f7fa;
  padding: 10px 12px;
  border-radius: 4px;
  margin-top: 8px;
  margin-bottom: 12px;
  line-height: 1.6;
  border-left: 3px solid #3b82f6;
}

.preset-description strong {
  color: #333;
}
</style>
