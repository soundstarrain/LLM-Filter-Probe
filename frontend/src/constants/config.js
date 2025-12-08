/**
 * 应用配置常量定义
 * 集中管理所有魔法数字和配置参数
 */

// WebSocket 重连配置
export const WEBSOCKET_CONFIG = {
  MAX_RETRIES: 5,
  INITIAL_DELAY: 1000, // 初始重连延迟 (ms)
  MAX_DELAY: 30000, // 最大重连延迟 (ms)
  BACKOFF_MULTIPLIER: 2, // 指数退避倍数
};

// HTTP 请求配置
export const HTTP_CONFIG = {
  TIMEOUT: 30000, // 请求超时 (ms)
  RETRY_ATTEMPTS: 3, // 重试次数
};

// 日志配置
export const LOG_CONFIG = {
  MAX_SIZE: 100000, // 日志最大条数
  RETENTION_TIME: 24 * 60 * 60 * 1000, // 日志保留时间 (24小时)
};

// 扫描配置
export const SCAN_CONFIG = {
  DEFAULT_PRESET: 'relay',
  DEFAULT_MODEL: 'gpt-4o-mini',
};

// 缓存配置
export const CACHE_CONFIG = {
  CONFIG_TTL: 5 * 60 * 1000, // 配置缓存有效期 (5分钟)
};

// 延迟监控配置
export const MONITOR_CONFIG = {
  LATENCY_HISTORY_SIZE: 50, // 延迟历史记录大小
  LATENCY_WARNING_THRESHOLD: 200, // 延迟警告阈值 (ms)
  LATENCY_ERROR_THRESHOLD: 500, // 延迟错误阈值 (ms)
};

// 健康检查配置
export const HEALTH_CHECK_CONFIG = {
  MAX_RETRIES: 3,
  RETRY_INTERVAL: 2000, // 重试间隔 (ms)
};
