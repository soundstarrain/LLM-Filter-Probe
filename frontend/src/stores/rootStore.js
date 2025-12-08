import { defineStore } from 'pinia';
import { reactive, computed, watch } from 'vue';
import { apiPost } from '../utils/apiClient';
import { loadConfig } from '../utils/configLoader';
import { API_ENDPOINTS } from '../constants/api';
import { MONITOR_CONFIG, LOG_CONFIG } from '../constants/config';
import { saveLogs, loadLogs } from '../utils/logManager';

export const useRootStore = defineStore('root', () => {
  // ============ State Definition ============

  // 配置数据（纯数据，不包含 UI 状态）
  const apiConfig = reactive({
    api_url: '',
    api_key: '',
    api_model: 'gpt-4o-mini',
  });

  // API 配置的 UI 状态
  const apiConfigUI = reactive({
    isValid: false,
    isLoading: false,
    isSaving: false,
    isTesting: false,
    testStatus: 'untested', // 'untested', 'passed', 'failed'
  });

  const settingsConfig = reactive({
    concurrency: 15,
    timeout_seconds: 30,
    use_system_proxy: true,
    jitter: 0.5,
    token_limit: 20,
    delimiter: '\n',
    chunk_size: 30000,
    max_retries: 3,
    min_granularity: 1,
    overlap_size: 12,
    algorithm_mode: 'hybrid',
    algorithm_switch_threshold: 35,
    preset: 'relay',
  });

  // 设置配置的 UI 状态
  const settingsConfigUI = reactive({
    isLoading: false,
    isSaving: false,
  });

  const presetsConfig = reactive({
    availablePresets: [],
    customRules: {
      block_status_codes: [],
      block_keywords: [],
      retry_status_codes: [],
    },
  });

  // 预设配置的 UI 状态
  const presetsConfigUI = reactive({
    isLoading: false,
    isSaving: false,
  });
  const scanState = reactive({
    isScanning: false,
    currentText: '',
    progress: 0,
    scannedBytes: 0,
    totalBytes: 0,
    startTime: null,
    endTime: null,
    error: null,
  });
  const results = reactive({
    grouped: {},
    statistics: { total_results: 0, found: 0, duration: 0, total_requests: 0 },
    // 【新增】未知状态码统计和敏感词判断依据
    unknownStatusCodeCounts: {},
    sensitiveWordEvidence: {},
  });
  const logs = reactive({ 
    messages: [], 
    maxSize: LOG_CONFIG.MAX_SIZE,
    autoClearOnRefresh: true, // 刷新时自动清空日志
  });
  const system = reactive({
    connectionStatus: 'offline', // 'offline', 'online', 'reconnecting'
    sessionId: '',
    activeTab: 'scanner',
    wsSend: null, // 用于存储 WebSocket 的 send 方法
    isPageRefreshing: false, // 标记页面是否正在刷新
  });
  const monitor = reactive({
    currentLatency: 0,
    averageLatency: 0,
    latencyHistory: [],
    latencySumCache: 0, // 用于 O(1) 计算平均值
    apiDomain: '',
    currentModel: '',
  });

  // ============ Computed Properties ============

  const isReadyToScan = computed(
    () => apiConfigUI.isValid && system.connectionStatus === 'online' && system.sessionId
  );
  const scanDuration = computed(() => {
    if (!scanState.startTime) return 0;

    // 扫描已完成时，使用 endTime
    if (scanState.endTime) {
      return Math.round((scanState.endTime - scanState.startTime) / 1000);
    }

    // 扫描进行中时，使用当前时间
    if (scanState.isScanning) {
      return Math.round((Date.now() - scanState.startTime) / 1000);
    }

    return 0;
  });
  const isCustomPreset = computed(() => settingsConfig.preset === 'custom');
  const presetOptions = computed(() =>
    Array.isArray(presetsConfig.availablePresets)
      ? presetsConfig.availablePresets.map((p) => ({ label: p.display_name, value: p.name }))
      : []
  );
  const presetDescription = computed(
    () =>
      (Array.isArray(presetsConfig.availablePresets)
        ? presetsConfig.availablePresets.find((p) => p.name === settingsConfig.preset)?.description
        : '') || ''
  );
  const latencyStatus = computed(() => {
    if (monitor.currentLatency > 500) return 'error';
    if (monitor.currentLatency > 200) return 'warning';
    return 'success';
  });
  const resultKeywords = computed(() => Object.keys(results.grouped));
  const totalSensitiveCount = computed(() =>
    Object.values(results.grouped).reduce((sum, locations) => sum + locations.length, 0)
  );

  // ============ Actions ============

  // --- API Actions ---
  function updateApiField(field, value) {
    if (field in apiConfig) {
      apiConfig[field] = value;
      apiConfigUI.testStatus = 'untested';
      apiConfigUI.isValid = false;
    }
  }
  async function loadApiConfig() {
    apiConfigUI.isLoading = true;
    try {
      const config = await loadConfig(API_ENDPOINTS.CONFIG.API, {});

      apiConfig.api_url = config.api_url || '';
      apiConfig.api_key = config.api_key || '';
      apiConfig.api_model = config.api_model || 'gpt-4o-mini';

      // 检查是否加载了有效的配置
      const hasValidConfig = !!(apiConfig.api_url && apiConfig.api_key);

      if (hasValidConfig) {
        console.log('✅ API 配置加载成功:', {
          url: !!apiConfig.api_url,
          key: !!apiConfig.api_key,
          model: apiConfig.api_model,
        });
      } else {
        console.warn('⚠️ API 配置为空，请在设置中配置 API 凭证');
        addLog('⚠️ 未检测到 API 凭证，请在设置中配置', 'warning');
      }
    } catch (err) {
      console.error('❌ 加载 API 配置失败:', err);
      addLog(`加载 API 配置失败: ${err.message}`, 'error');
      // 设置默认值
      apiConfig.api_url = '';
      apiConfig.api_key = '';
      apiConfig.api_model = 'gpt-4o-mini';
    } finally {
      apiConfigUI.isLoading = false;
    }
  }

  async function saveApiConfig() {
    apiConfigUI.isSaving = true;
    try {
      const payload = {
        api_url: apiConfig.api_url,
        api_key: apiConfig.api_key,
        api_model: apiConfig.api_model,
      };
      await apiPost(API_ENDPOINTS.CONFIG.API, payload);
      apiConfigUI.isValid = true;
    } catch (err) {
      apiConfigUI.isValid = false;
      throw err;
    } finally {
      apiConfigUI.isSaving = false;
    }
  }

  async function testConnection() {
    apiConfigUI.isTesting = true;
    apiConfigUI.testStatus = 'untested';
    try {
      const payload = {
        api_url: apiConfig.api_url,
        api_key: apiConfig.api_key,
        api_model: apiConfig.api_model, // 统一使用 api_model 字段
      };
      const result = await apiPost(API_ENDPOINTS.VERIFY, payload);
      if (!result.ok) {
        const errorDetail = result.response?.error?.message || result.message || '未知错误';
        throw new Error(errorDetail);
      }
      apiConfigUI.testStatus = 'passed';
    } catch (err) {
      apiConfigUI.testStatus = 'failed';
      throw err;
    } finally {
      apiConfigUI.isTesting = false;
    }
  }

  // --- Settings Actions ---
  function updateSettingField(field, value) {
    if (field in settingsConfig) settingsConfig[field] = value;
  }

  async function loadSettings() {
    settingsConfigUI.isLoading = true;
    try {
      const settings = await loadConfig(API_ENDPOINTS.CONFIG.SETTINGS, {});

      // 确保所有字段都被正确加载
      const fieldsToUpdate = {
        concurrency: settings.concurrency ?? settingsConfig.concurrency,
        timeout_seconds: settings.timeout_seconds ?? settingsConfig.timeout_seconds,
        use_system_proxy: settings.use_system_proxy ?? settingsConfig.use_system_proxy,
        jitter: settings.jitter ?? settingsConfig.jitter,
        token_limit: settings.token_limit ?? settingsConfig.token_limit,
        delimiter: settings.delimiter ?? settingsConfig.delimiter,
        chunk_size: settings.chunk_size ?? settingsConfig.chunk_size,
        max_retries: settings.max_retries ?? settingsConfig.max_retries,
        min_granularity: settings.min_granularity ?? settingsConfig.min_granularity,
        overlap_size: settings.overlap_size ?? settingsConfig.overlap_size,
        algorithm_mode: settings.algorithm_mode ?? settingsConfig.algorithm_mode,
        algorithm_switch_threshold: settings.algorithm_switch_threshold ?? settingsConfig.algorithm_switch_threshold,
        preset: settings.preset ?? settingsConfig.preset,
      };

      Object.assign(settingsConfig, fieldsToUpdate);
      console.log('✅ 高级设置加载成功:', fieldsToUpdate);
    } catch (err) {
      console.error('❌ 加载高级设置失败:', err);
      addLog(`加载高级设置失败: ${err.message}`, 'error');
    } finally {
      settingsConfigUI.isLoading = false;
    }
  }

  async function saveSettings() {
    settingsConfigUI.isSaving = true;
    try {
      await apiPost(API_ENDPOINTS.CONFIG.SETTINGS, settingsConfig);
    } finally {
      settingsConfigUI.isSaving = false;
    }
  }

  // --- Presets Actions ---
  function setPreset(newPreset) {
    settingsConfig.preset = newPreset;
    
    // 从 availablePresets 中查找对应的预设数据
    const selectedPreset = presetsConfig.availablePresets.find(p => p.name === newPreset);
    if (selectedPreset) {
      // 更新 customRules 为选中预设的规则数据
      presetsConfig.customRules = {
        block_status_codes: selectedPreset.block_status_codes || [],
        block_keywords: selectedPreset.block_keywords || [],
        retry_status_codes: selectedPreset.retry_status_codes || [429, 502, 503, 504],
      };
      console.log(`✅ 预设已切换为 '${newPreset}'，规则数据已更新:`, presetsConfig.customRules);
    } else {
      console.warn(`⚠️ 未找到预设 '${newPreset}' 的数据`);
    }
  }

  async function loadPresetsConfig() {
    presetsConfigUI.isLoading = true;
    try {
      const config = await loadConfig(API_ENDPOINTS.CONFIG.PRESETS, {});

      presetsConfig.availablePresets = config.available_presets || [];
      settingsConfig.preset = config.preset || 'relay';

      if (config.custom_rules) {
        presetsConfig.customRules = {
          block_status_codes: config.custom_rules.block_status_codes || [],
          block_keywords: config.custom_rules.block_keywords || [],
          retry_status_codes: config.custom_rules.retry_status_codes || [],
        };
      }

      console.log('✅ 预设配置加载成功:', {
        presets: presetsConfig.availablePresets.length,
        currentPreset: settingsConfig.preset,
        customRules: presetsConfig.customRules,
      });
    } catch (err) {
      console.error('❌ 加载预设配置失败:', err);
      addLog(`加载预设配置失败: ${err.message}`, 'error');
      // 设置默认值
      presetsConfig.availablePresets = [];
      settingsConfig.preset = 'relay';
      presetsConfig.customRules = {
        block_status_codes: [],
        block_keywords: [],
        retry_status_codes: [],
      };
    } finally {
      presetsConfigUI.isLoading = false;
    }
  }

  async function saveCustomRules() {
    if (settingsConfig.preset !== 'custom') return;
    presetsConfigUI.isSaving = true;
    try {
      const payload = { custom_rules: presetsConfig.customRules };
      await apiPost(API_ENDPOINTS.CONFIG.PRESETS, payload);
    } finally {
      presetsConfigUI.isSaving = false;
    }
  }

  // --- Load All Configs ---
  async function loadAllConfigurations() {
    const startTime = Date.now();
    addLog('🔄 正在加载所有配置...', 'info');

    try {
      // 并行加载所有配置（使用 allSettled 以处理部分失败）
      const results = await Promise.allSettled([
        loadApiConfig(),
        loadSettings(),
        loadPresetsConfig(),
      ]);

      const loadTime = Date.now() - startTime;
      addLog(`✅ 配置加载完成 (耗时 ${loadTime}ms)`, 'success');

      // 只有在 loadApiConfig 成功时才测试连接
      if (
        results[0].status === 'fulfilled' &&
        apiConfig.api_url &&
        apiConfig.api_key &&
        apiConfig.api_model
      ) {
        addLog('检测到现有配置，正在自动验证...', 'info');
        try {
          await testConnection(); // 执行测试
          if (apiConfigUI.testStatus === 'passed') {
            addLog('✅ 自动验证成功', 'success');
            apiConfigUI.isValid = true; // 将状态标记为有效
          } else {
            addLog(`⚠️ 自动验证未通过: ${apiConfigUI.testStatus}`, 'warning');
            apiConfigUI.isValid = false;
          }
        } catch (error) {
          addLog(`❌ 自动验证失败: ${error.message}`, 'error');
          apiConfigUI.isValid = false; // 确保验证失败时状态为无效
        }
      } else {
        addLog('⚠️ 未检测到完整的 API 配置，请在设置中配置', 'warning');
        apiConfigUI.isValid = false;
      }

      return true; // 表示加载成功
    } catch (error) {
      const loadTime = Date.now() - startTime;
      addLog(`❌ 配置加载失败 (耗时 ${loadTime}ms): ${error.message}`, 'error');
      apiConfigUI.isValid = false;
      return false; // 表示加载失败
    }
  }

  // --- Session and System Actions ---
  function createSession(id) {
    system.sessionId = id;
  }
  function destroySession() {
    if (system.sessionId) system.sessionId = '';
  }
  function setConnectionStatus(status) {
    system.connectionStatus = status;
  }

  function setWebSocketSendFunction(sendFunc) {
    system.wsSend = sendFunc;
  }

  // --- Monitor Actions ---
  /**
   * 记录 API 延迟并计算移动平均值
   * 使用增量计算避免每次都遍历整个数组
   * @param {number} latency - 单次请求延迟 (ms)
   */
  function recordLatency(latency) {
    monitor.currentLatency = latency;

    // 维护滑动窗口（最多 LATENCY_HISTORY_SIZE 条记录）
    if (monitor.latencyHistory.length >= MONITOR_CONFIG.LATENCY_HISTORY_SIZE) {
      const removed = monitor.latencyHistory.shift();
      monitor.latencySumCache -= removed;
    }

    monitor.latencyHistory.push(latency);
    monitor.latencySumCache += latency;

    // O(1) 计算平均值
    monitor.averageLatency =
      Math.round(monitor.latencySumCache / monitor.latencyHistory.length) || 0;
  }
  function setMonitorInfo({ apiDomain, currentModel }) {
    if (apiDomain) monitor.apiDomain = apiDomain;
    if (currentModel) monitor.currentModel = currentModel;
  }

  // --- Scan Actions ---

  /**
   * 重置扫描状态
   * @param {string} text - 要扫描的文本
   */
  function resetScanState(text) {
    Object.assign(scanState, {
      isScanning: true,
      currentText: text,
      progress: 0,
      scannedBytes: 0,
      totalBytes: 0,
      startTime: Date.now(),
      endTime: null,
      error: null,
    });
    results.grouped = {};
    Object.assign(results.statistics, {
      total_results: 0,
      found: 0,
      duration: 0,
      total_requests: 0,
    });
    // 使用分隔符而非清空，便于追溯历史日志
    if (logs.messages.length > 0) {
      addLog('─'.repeat(50), 'info');
    }
  }

  /**
   * 发送扫描请求
   * @param {string} text - 要扫描的文本
   * @returns {boolean} 是否成功发送
   */
  function sendScanRequest(text) {
    // 验证前置条件
    if (!system.wsSend) {
      addLog('WebSocket 未连接，无法发送扫描请求。', 'error');
      return false;
    }

    if (!text || !text.trim()) {
      addLog('扫描文本不能为空。', 'warning');
      return false;
    }

    try {
      // 重置状态
      resetScanState(text);

      // 发送请求
      const payload = {
        type: 'scan_text',
        data: { text },
      };

      system.wsSend(payload);
      addLog('扫描请求已发送。', 'info');
      return true;
    } catch (error) {
      // 错误时恢复状态
      setScanError(new Error(`发送扫描请求失败: ${error.message}`));
      return false;
    }
  }

  /**
   * 启动扫描（内部使用，用于兼容性）
   * @deprecated 使用 resetScanState 代替
   */
  function startScan(text) {
    resetScanState(text);
  }
  function updateScanProgress(progressData) {
    const { scanned, total, sensitive_count, results: newResults } = progressData;

    scanState.scannedBytes = scanned;
    scanState.totalBytes = total;
    scanState.progress = total > 0 ? Math.round((scanned / total) * 100) : 0;

    if (sensitive_count !== null && sensitive_count !== undefined) {
      results.statistics.found = sensitive_count;
    }

    // 实时更新结果列表
    // 【修复】合并结果，而不是替换，以防止数据丢失
    if (newResults) {
      for (const [keyword, locations] of Object.entries(newResults)) {
        if (results.grouped[keyword]) {
          // 合并并去重
          const existingLocations = new Set(results.grouped[keyword].map(loc => `${loc.start}-${loc.end}`));
          for (const loc of locations) {
            if (!existingLocations.has(`${loc.start}-${loc.end}`)) {
              results.grouped[keyword].push(loc);
            }
          }
        } else {
          results.grouped[keyword] = locations;
        }
      }
    }
  }
  function completeScan(data) {
    scanState.isScanning = false;
    scanState.endTime = Date.now();
    results.statistics.found = data.sensitive_count || 0;
    results.statistics.total_requests = data.total_requests || 0;
    results.statistics.duration = scanDuration.value;
    if (data.results) results.grouped = data.results;
    // 【新增】保存未知状态码统计和敏感词判断依据
    if (data.unknown_status_code_counts) {
      results.unknownStatusCodeCounts = data.unknown_status_code_counts;
    }
    if (data.sensitive_word_evidence) {
      results.sensitiveWordEvidence = data.sensitive_word_evidence;
    }
  }
  async function cancelScan() {
    if (!scanState.isScanning) return;

    addLog('正在停止扫描...', 'info');
    try {
      await apiPost(API_ENDPOINTS.SCAN.CANCEL(system.sessionId), {});
      // 后端将通过 WebSocket 发送 'scan_complete' 或 'error' 消息
      // 我们也可以在客户端乐观地更新状态
      scanState.isScanning = false;
      scanState.endTime = Date.now();
      addLog('扫描已手动停止', 'warning');
    } catch (error) {
      addLog(`停止扫描失败: ${error.message}`, 'error');
      // 即使后端调用失败，我们可能也希望停止 UI 显示“正在扫描”
      scanState.isScanning = false;
    }
  }
  function initializeScan(data) {
    scanState.totalBytes = data.total_length || 0;
    scanState.progress = 0;
    scanState.scannedBytes = 0;

    // 【新增】清空上一轮结果与统计（包括敏感词判断依据与未知状态码统计）
    results.grouped = {};
    results.statistics.found = 0;
    results.statistics.total_requests = 0;
    results.statistics.duration = 0;
    results.unknownStatusCodeCounts = {};
    results.sensitiveWordEvidence = {};
  }

  function setScanError(error) {
    scanState.error = error;
    scanState.isScanning = false;
    scanState.endTime = Date.now();
    addLog(`扫描错误: ${error.message}`, 'error');
  }

  // --- Results Actions ---
  function getLocationsByKeyword(keyword) {
    return results.grouped[keyword] || [];
  }

  // --- Log Actions ---
  function addLog(message, level = 'info') {
    // 追加到数组尾部：新日志在下方显示
    logs.messages.push({ message, level, timestamp: new Date().toISOString() });
    // 若超过上限，从头部丢弃最早的
    if (logs.messages.length > logs.maxSize) logs.messages.shift();
  }
  function clearLogs() {
    logs.messages = [];
  }

  /**
   * 设置刷新时是否自动清空日志
   * @param {boolean} enabled - 是否启用自动清空
   */
  function setAutoClearOnRefresh(enabled) {
    logs.autoClearOnRefresh = enabled;
  }

  /**
   * 标记页面正在刷新
   * @param {boolean} isRefreshing - 是否正在刷新
   */
  function setPageRefreshing(isRefreshing) {
    system.isPageRefreshing = isRefreshing;
  }

  /**
   * 初始化日志管理
   * 加载已保存的日志并设置自动保存
   */
  function initializeLogManagement() {
    // 加载已保存的日志
    const savedLogs = loadLogs();
    if (savedLogs.length > 0) {
      logs.messages = savedLogs;
      console.log(`✅ 已加载 ${savedLogs.length} 条历史日志`);
    }

    // 设置日志自动保存（每次日志变化时）
    // 注意：这里使用简单的防抖避免过频繁的保存
    let saveTimeout;
    watch(
      () => logs.messages.length,
      () => {
        clearTimeout(saveTimeout);
        saveTimeout = setTimeout(() => {
          saveLogs(logs.messages);
        }, 1000); // 延迟 1 秒保存，避免频繁写入
      }
    );
  }

  // 在 store 创建时初始化日志管理
  initializeLogManagement();

  return {
    // State - 配置数据
    apiConfig,
    apiConfigUI,
    settingsConfig,
    settingsConfigUI,
    presetsConfig,
    presetsConfigUI,
    scanState,
    results,
    logs,
    system,
    monitor,
    // Computed
    isReadyToScan,
    scanDuration,
    isCustomPreset,
    presetOptions,
    presetDescription,
    latencyStatus,
    resultKeywords,
    totalSensitiveCount,
    // Actions
    updateApiField,
    loadApiConfig,
    saveApiConfig,
    testConnection,
    updateSettingField,
    loadSettings,
    saveSettings,
    setPreset,
    loadPresetsConfig,
    saveCustomRules,
    loadAllConfigurations,
    createSession,
    destroySession,
    setConnectionStatus,
    setWebSocketSendFunction,
    recordLatency,
    setMonitorInfo,
    resetScanState,
    sendScanRequest, // 发送扫描请求
    startScan, // 保留：用于兼容性
    updateScanProgress,
    completeScan,
    cancelScan,
    initializeScan,
    setScanError,
    getLocationsByKeyword,
    addLog,
    clearLogs,
    setAutoClearOnRefresh,
    setPageRefreshing,
    initializeLogManagement,
  };
});
