<template>
  <n-layout has-sider class="app-layout">
    <!-- 左侧边栏 -->
    <AppSidebar :disabled="scanState.isScanning" />

    <!-- 主内容区 -->
    <n-layout class="main-layout">
      <n-layout-header class="header">
        <div class="header-content">
          <h1>LLM-Filter-Probe</h1>
          <div class="header-actions"></div>
        </div>
      </n-layout-header>

      <n-layout-content class="content">
        <!-- Mission Control 仪表板 -->
        <DashboardPanel />

        <!-- 文本扫描器 -->
        <TextScanner />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import { storeToRefs } from 'pinia';
import AppSidebar from './components/layout/AppSidebar.vue';
import TextScanner from './components/TextScanner.vue';
import DashboardPanel from './components/DashboardPanel.vue';
import { useRootStore } from './stores/rootStore';
import { useWebSocketReconnect } from './composables/useWebSocketReconnect';
import { API_ENDPOINTS, getWebSocketUrl } from './constants/api';
import { HEALTH_CHECK_CONFIG } from './constants/config';

const rootStore = useRootStore();
const { scanState } = storeToRefs(rootStore);
const wsReconnect = ref(null);

/**
 * 检查后端健康状态，并在失败时进行重试。
 * @param {number} maxRetries - 最大重试次数。
 * @param {number} retryInterval - 重试间隔（毫秒）。
 * @returns {Promise<boolean>} 如果后端健康则返回 true，否则返回 false。
 */
const checkBackendHealth = async (
  maxRetries = HEALTH_CHECK_CONFIG.MAX_RETRIES,
  retryInterval = HEALTH_CHECK_CONFIG.RETRY_INTERVAL
) => {
  for (let i = 0; i < maxRetries; i++) {
    try {
      console.log(`🏥 正在进行健康检查 (尝试 ${i + 1}/${maxRetries})...`);
      const response = await fetch(API_ENDPOINTS.HEALTH);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const healthData = await response.json();
      if (healthData.data?.status === 'healthy') {
        console.log('✅ 后端服务健康:', healthData.data);
        rootStore.addLog('后端服务连接成功', 'success');
        return true;
      }

      throw new Error('后端服务状态异常');
    } catch (error) {
      console.error(`❌ 健康检查失败 (尝试 ${i + 1}):`, error);

      if (i < maxRetries - 1) {
        await new Promise((resolve) => setTimeout(resolve, retryInterval));
      } else {
        rootStore.addLog(`后端服务不可用: ${error.message}`, 'error');
        return false;
      }
    }
  }
  return false;
};

/**
 * 初始化会话和 WebSocket 连接。
 * 此函数负责与后端通信以创建一个新的扫描会话，获取 session_id，
 * 然后使用该 ID 建立一个带自动重连功能的 WebSocket 连接。
 * @returns {Promise<void>}
 */
const initializeSession = async () => {
  // 清理旧连接
  if (wsReconnect.value) {
    console.log('清理旧的 WebSocket 连接...');
    wsReconnect.value.disconnect();
    wsReconnect.value = null;
  }

  console.log('正在创建会话...');
  rootStore.addLog('正在创建会话...', 'info');

  // 调用API创建会话，添加超时控制
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 10000); // 10秒超时

  try {
    const response = await fetch(API_ENDPOINTS.SESSION.CREATE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`会话创建失败: ${response.status} ${response.statusText}`);
    }

    const payload = await response.json();

    if (!payload.data?.session_id) {
      throw new Error('响应中缺少 session_id');
    }

    const sessionId = payload.data.session_id;

    console.log(`✅ 会话创建成功: ${sessionId}`);
    rootStore.addLog(`会话创建成功: ${sessionId}`, 'success');
    rootStore.createSession(sessionId);

    // 使用sessionId建立WebSocket连接
    const socketUrl = getWebSocketUrl(sessionId);
    console.log(`正在连接WebSocket: ${socketUrl}`);
    rootStore.addLog('正在建立 WebSocket 连接...', 'info');

    wsReconnect.value = useWebSocketReconnect(socketUrl, {
      connectionTimeout: 10000, // 10秒超时
      onMessage: (event) => {
        try {
          const data = JSON.parse(event.data);
          // 根据事件类型调用不同的 store action
          switch (data.event) {
            case 'scan_start':
              rootStore.initializeScan(data.data || {});
              break;
            case 'progress':
              rootStore.updateScanProgress(data.data || {});
              break;
            case 'scan_complete':
              rootStore.completeScan(data.data || {});
              break;
            case 'log':
              rootStore.addLog(data.message || '', data.level || 'info');
              break;
            case 'error':
              rootStore.setScanError(new Error(data.message || '未知服务器错误'));
              break;
            case 'warning':
              rootStore.addLog(data.message || '', 'warning');
              break;
            case 'unknown_status_code':
              rootStore.addLog(
                `检测到未知状态码 ${data.status_code}。响应片段: ${(data.response_snippet || '').slice(0, 120)}...`,
                'warning'
              );
              break;
            default:
              console.warn('未知事件类型:', data.event, data);
          }
        } catch (error) {
          console.error('❌ 消息处理错误:', error);
        }
      },
      onOpen: () => {
        console.log('✅ WebSocket连接已建立');
        rootStore.setConnectionStatus('online');
        rootStore.addLog('WebSocket 连接已建立', 'success');
        if (wsReconnect.value && wsReconnect.value.send) {
          rootStore.setWebSocketSendFunction(wsReconnect.value.send);
        }
      },
      onClose: () => {
        console.log('WebSocket连接已关闭');
        rootStore.setConnectionStatus('offline');
        rootStore.addLog('WebSocket 连接已关闭', 'warning');
      },
      onError: (error) => {
        console.error('❌ WebSocket连接错误:', error);
        rootStore.setConnectionStatus('offline');
        rootStore.addLog(`WebSocket 连接错误: ${error.message || '未知错误'}`, 'error');
      },
    });

    // 添加超时控制
    const connectPromise = wsReconnect.value.connect();
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('WebSocket 连接超时')), 15000)
    );
    await Promise.race([connectPromise, timeoutPromise]);
  } catch (error) {
    console.error('❌ 会话初始化失败:', error);
    rootStore.setConnectionStatus('offline');

    // 区分不同的错误类型
    let errorMessage = error.message;
    if (error.name === 'AbortError') {
      errorMessage = '会话创建请求超时 (10秒)';
    } else if (error.message.includes('WebSocket 连接超时')) {
      errorMessage = 'WebSocket 连接超时 (15秒)';
    }

    rootStore.addLog(`无法创建会话: ${errorMessage}`, 'error');

    // 清理失败的连接
    if (wsReconnect.value) {
      wsReconnect.value.disconnect();
      wsReconnect.value = null;
    }
  } finally {
    clearTimeout(timeoutId);
  }
};

/**
 * 清理当前会话资源。
 * 此函数负责断开 WebSocket 连接并通知 Pinia store 销毁当前会话。
 */
function cleanupSession() {
  if (wsReconnect.value) {
    wsReconnect.value.disconnect();
  }
  rootStore.destroySession();
}

// --- 组件挂载与卸载 ---
onMounted(async () => {
  try {
    // 【新增】检查是否是页面刷新，如果是则清空日志
    const isPageRefresh = performance.navigation.type === 1 || 
                          (window.performance && window.performance.getEntriesByType('navigation')[0]?.type === 'reload');
    
    if (isPageRefresh && rootStore.logs.autoClearOnRefresh) {
      console.log('🔄 检测到页面刷新，正在清空日志...');
      rootStore.clearLogs();
      rootStore.addLog('检测到浏览器刷新，自动清空历史日志。', 'info');
    }

    // 第一步：检查后端服务是否健康
    const isHealthy = await checkBackendHealth();
    if (!isHealthy) {
      console.error('❌ [App] 后端服务不可用，初始化中止。');
      return; // 中止初始化流程
    }

    // 第二步：加载所有初始配置（必须等待完成）
    console.log('[App] 开始加载配置...');
    const configLoaded = await rootStore.loadAllConfigurations();

    if (!configLoaded) {
      console.warn('[App] 配置加载失败，但仍尝试初始化会话');
    } else {
      console.log('✅ [App] 配置加载成功');
    }

    // 检查 API 配置是否完整
    if (!rootStore.apiConfig.api_url || !rootStore.apiConfig.api_key) {
      console.warn('⚠️ [App] API 凭证不完整，请在设置中配置');
      rootStore.addLog('⚠️ 请在设置中配置 API 凭证以继续使用', 'warning');
    }

    // 第三步：初始化会话和WebSocket连接（在配置加载完成后）
    console.log('[App] 开始初始化会话和 WebSocket...');
    await initializeSession();
  } catch (error) {
    console.error('❌ [App] 应用初始化失败:', error);
    rootStore.addLog(`应用初始化失败: ${error.message}`, 'error');
  }
});

// 【新增】监听页面卸载事件，标记页面正在刷新
window.addEventListener('beforeunload', () => {
  rootStore.setPageRefreshing(true);
});

// 在组件卸载时清理会话
onUnmounted(() => {
  cleanupSession();
});
</script>

<style scoped>
/* 全局布局容器 */
.app-layout {
  width: 100%;
  height: 100vh;
  display: flex;
  flex-direction: row;
}

/* 主内容区布局 */
.main-layout {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 顶部头部 */
.header {
  background: var(--n-color);
  border-bottom: 1px solid var(--n-border-color);
  padding: 0 20px;
  display: flex;
  align-items: center;
  height: 64px;
  flex-shrink: 0;
  z-index: 5;
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.header-content h1 {
  font-size: 24px;
  font-weight: 700;
  color: var(--n-text-color);
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

/* 主内容区 */
.content {
  flex: 1;
  padding: 20px;
  background: var(--n-color-target);
  overflow: auto;
  /* 确保内容可滚动 */
  min-height: 0;
}

/* 响应式调整 */
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 20;
  }

  .sidebar-content {
    padding: 16px;
  }

  .logo h2 {
    font-size: 16px;
  }

  .header-content h1 {
    font-size: 20px;
  }

  .content {
    padding: 16px;
  }
}
</style>
