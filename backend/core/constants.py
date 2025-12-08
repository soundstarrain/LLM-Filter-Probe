"""
系统常量定义 (Constants)
所有硬编码的配置值都应该在这里定义
单一事实源：从配置文件读取默认值
"""
import json
import os
from pathlib import Path
from .config_schema import ConfigSchema

# ============ 定位并加载配置文件 ============
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "settings" / "default.json"
ALGORITHM_CONFIG_PATH = BASE_DIR / "config" / "algorithm" / "default.json"
SYSTEM_CONSTANTS_PATH = BASE_DIR / "config" / "system" / "constants.json"
SYSTEM_HTTP_PATH = BASE_DIR / "config" / "system" / "http.json"
SYSTEM_CACHE_PATH = BASE_DIR / "config" / "system" / "cache.json"
SYSTEM_MONITOR_PATH = BASE_DIR / "config" / "system" / "monitor.json"
SYSTEM_ERROR_RECOVERY_PATH = BASE_DIR / "config" / "system" / "error_recovery.json"


def load_json_file(path):
    """加载 JSON 文件"""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️  Error loading {path}: {e}")
    return {}


def load_defaults():
    """
    加载默认配置
    使用 model_construct 绕过严格校验，允许缺少 api_key 等凭证字段
    """
    try:
        if DEFAULT_CONFIG_PATH.exists():
            with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 使用 model_construct (Pydantic v2) 来创建对象
                # 即使缺少 api_key 也可以成功创建
                return ConfigSchema.model_construct(**data)
        else:
            print(f"⚠️  CRITICAL WARNING: Default config not found at {DEFAULT_CONFIG_PATH}")
            return ConfigSchema.model_construct()
    except Exception as e:
        print(f"❌ Error loading defaults: {e}")
        return ConfigSchema.model_construct()


# 初始化全局默认值对象
_defaults = load_defaults()
_algorithm_config = load_json_file(ALGORITHM_CONFIG_PATH)
_system_constants = load_json_file(SYSTEM_CONSTANTS_PATH)
_system_http = load_json_file(SYSTEM_HTTP_PATH)
_system_cache = load_json_file(SYSTEM_CACHE_PATH)
_system_monitor = load_json_file(SYSTEM_MONITOR_PATH)
_system_error_recovery = load_json_file(SYSTEM_ERROR_RECOVERY_PATH)

# ============ 连接配置常量 ============
# 注意：这些值从 config/settings/default.json 加载，不应该硬编码
DEFAULT_API_URL = getattr(_defaults, 'api_url', None) or ""
"""默认 API 基础地址"""

DEFAULT_API_KEY = getattr(_defaults, 'api_key', None) or ""
"""默认 API 密钥"""

DEFAULT_API_MODEL = getattr(_defaults, 'api_model', None) or ""
"""默认 API 模型"""

# ============ 性能配置常量 ============
# 注意：这些值从 config/settings/default.json 加载，不应该硬编码
DEFAULT_CONCURRENCY = getattr(_defaults, 'concurrency', None) or 15
"""默认并发数"""

DEFAULT_TIMEOUT_SECONDS = getattr(_defaults, 'timeout_seconds', None) or 30
"""默认请求超时（秒）"""

DEFAULT_USE_SYSTEM_PROXY = getattr(_defaults, 'use_system_proxy', None) if getattr(_defaults, 'use_system_proxy', None) is not None else True
"""默认是否使用系统代理"""

# ============ 扫描参数常量 ============
# 注意：这些值从 config/settings/default.json 加载，不应该硬编码
DEFAULT_CHUNK_SIZE = getattr(_defaults, 'chunk_size', None) or 30000
"""默认分块大小（字符数）"""

DEFAULT_TOKEN_LIMIT = getattr(_defaults, 'token_limit', None) or 20
"""默认 Token 上限"""

DEFAULT_DELIMITER = getattr(_defaults, 'delimiter', None) or "\n"
"""默认文本分割符"""

DEFAULT_MAX_RETRIES = getattr(_defaults, 'max_retries', None) or 3
"""默认最大重试次数"""

DEFAULT_JITTER = getattr(_defaults, 'jitter', None) if getattr(_defaults, 'jitter', None) is not None else 0.5
"""默认重试抖动（秒）"""

# ============ 算法配置常量 ============
# 注意：这些值从 config/settings/default.json 加载，不应该硬编码
DEFAULT_MIN_GRANULARITY = getattr(_defaults, 'min_granularity', None) or 1
"""默认二分查找最小粒度（字符数）"""

DEFAULT_OVERLAP_SIZE = getattr(_defaults, 'overlap_size', None) if getattr(_defaults, 'overlap_size', None) is not None else 10
"""默认重叠分割大小（字符数）"""

# ============ 算法切换阈值（从 config/algorithm/default.json 加载） ============
# 注意：这个值现在从配置文件加载，不再硬编码
DEFAULT_ALGORITHM_SWITCH_THRESHOLD = _algorithm_config.get("algorithm_switch_threshold", 35)
"""
算法切换阈值（字符数）。
当文本长度小于或等于此值时，二分查找将停止，并将任务交接给微观的"剥洋葱"式精确定位算法。
默认值 35 是一个基于经验的平衡点：
- 对于更长的文本，二分查找能快速缩小范围，效率高。
- 对于短于 35 的文本，二分查找的优势不再明显，直接进行精确定位的成本更低、效率更高。

【重要】此参数与 overlap_size 有强依赖关系：
必须满足 algorithm_switch_threshold > 2 * overlap_size
否则会导致无限递归（死循环）。
"""

# 为了向后兼容，保留这两个别名
HYBRID_HANDOVER_THRESHOLD = DEFAULT_ALGORITHM_SWITCH_THRESHOLD
MICRO_SCAN_THRESHOLD = DEFAULT_ALGORITHM_SWITCH_THRESHOLD

# ============ 规则配置常量 ============
# 注意：这些值从 config/settings/default.json 加载，不应该硬编码
DEFAULT_BLOCK_STATUS_CODES = getattr(_defaults, 'block_status_codes', None) or []
"""默认阻止状态码列表"""

DEFAULT_BLOCK_KEYWORDS = getattr(_defaults, 'block_keywords', None) or []
"""默认阻止关键词列表"""

DEFAULT_RETRY_STATUS_CODES = getattr(_defaults, 'retry_status_codes', None) or [429, 502, 503, 504]
"""默认重试状态码列表"""

# ============ 预设常量 ============
DEFAULT_PRESET = getattr(_defaults, 'preset', None) or "relay"
"""默认预设名称"""

# ============ 系统级常量（来自 config/system/constants.json） ============
DEFAULT_SEGMENT_SIZE = _system_constants.get('segment_size', 500)
"""默认分段大小（字符数）"""

DEFAULT_MAX_CONCURRENT_REQUESTS = _system_constants.get('max_concurrent_requests', 5)
"""默认最大并发请求数"""

DEFAULT_POLLING_INTERVAL = _system_constants.get('polling_interval', 3000)
"""默认轮询间隔（毫秒）"""

DEFAULT_MAX_HISTORY_SIZE = _system_constants.get('max_history_size', 50)
"""默认历史记录最大长度"""

DEFAULT_DICT_SCANNER_MAX_CHUNK_SIZE = _system_constants.get('dict_scanner_max_chunk_size', 1000)
"""字典扫描最大分块大小"""

# ============ HTTP 客户端常量（来自 config/system/http.json） ============
DEFAULT_HTTP_KEEP_ALIVE = _system_http.get('keep_alive', True)
"""HTTP 客户端默认启用 keep-alive"""

DEFAULT_HTTP_VERIFY_SSL = _system_http.get('verify_ssl', True)
"""HTTP 客户端默认验证 SSL"""

DEFAULT_HTTP_MAX_KEEPALIVE_CONNECTIONS = _system_http.get('max_keepalive_connections', 10)
"""HTTP 客户端默认最大 keep-alive 连接数"""

DEFAULT_HTTP_MAX_CONNECTIONS = _system_http.get('max_connections', 100)
"""HTTP 客户端默认最大连接数"""

HTTP_DEFAULT_TIMEOUT = DEFAULT_TIMEOUT_SECONDS
"""HTTP 客户端默认超时"""

HTTP_DEFAULT_MAX_RETRIES = 0
"""HTTP 客户端默认重试次数（由 engine 控制）"""

# ============ 缓存常量（来自 config/system/cache.json） ============
DEFAULT_CACHE_ENABLED = _system_cache.get('enabled', True)
"""默认是否启用缓存"""

DEFAULT_CACHE_MAX_SIZE = _system_cache.get('max_size', 1000)
"""默认最大缓存条目数"""

DEFAULT_CACHE_DEFAULT_TTL = _system_cache.get('default_ttl', 3600)
"""默认缓存过期时间（秒）"""

# ============ 监控常量（来自 config/system/monitor.json） ============
DEFAULT_MONITOR_ENABLED = _system_monitor.get('enabled', True)
"""默认是否启用性能监控"""

DEFAULT_MONITOR_MAX_HISTORY = _system_monitor.get('max_history', 3600)
"""默认最大历史记录数"""

DEFAULT_MONITOR_COLLECTION_INTERVAL = _system_monitor.get('collection_interval', 10)
"""默认监控数据收集间隔（秒）"""

# ============ 错误恢复常量（来自 config/system/error_recovery.json） ============
DEFAULT_ERROR_RECOVERY_ENABLED = _system_error_recovery.get('enabled', True)
"""默认是否启用错误恢复"""

DEFAULT_ERROR_RECOVERY_MAX_RETRIES = _system_error_recovery.get('max_retries', 3)
"""默认错误恢复最大重试次数"""

DEFAULT_ERROR_RECOVERY_INITIAL_BACKOFF = _system_error_recovery.get('initial_backoff', 1.0)
"""默认错误恢复初始退避时间（秒）"""

DEFAULT_ERROR_RECOVERY_MAX_BACKOFF = _system_error_recovery.get('max_backoff', 60.0)
"""默认错误恢复最大退避时间（秒）"""

# ============ 文本扫描常量 ============
DEFAULT_TEXT_SCANNER_MIN_GRANULARITY = DEFAULT_MIN_GRANULARITY
"""文本扫描最小粒度"""

# ============ 验证常量 ============
MIN_CONCURRENCY = 1
"""最小并发数"""

MAX_CONCURRENCY = 50
"""最大并发数"""

MIN_TIMEOUT_SECONDS = 1
"""最小超时时间（秒）"""

MAX_TIMEOUT_SECONDS = 120
"""最大超时时间（秒）"""

MIN_CHUNK_SIZE = 10
"""最小分块大小（字符数）"""

MAX_CHUNK_SIZE = 100000
"""最大分块大小（字符数）"""

MIN_TOKEN_LIMIT = 100
"""最小 Token 上限"""

MAX_TOKEN_LIMIT = 16000
"""最大 Token 上限"""

MIN_GRANULARITY = 2
"""最小粒度（字符数）"""

MAX_GRANULARITY = 1000
"""最大粒度（字符数）"""

MIN_OVERLAP_SIZE = 0
"""最小重叠大小（字符数）"""

MAX_OVERLAP_SIZE = 500
"""最大重叠大小（字符数）"""

MIN_JITTER = 0.0
"""最小抖动（秒）"""

MAX_JITTER = 5.0
"""最大抖动（秒）"""

MIN_MAX_RETRIES = 1
"""最小重试次数"""

MAX_MAX_RETRIES = 10
"""最大重试次数"""

MIN_ALGORITHM_SWITCH_THRESHOLD = 20
"""最小算法切换阈值（字符数）"""

MAX_ALGORITHM_SWITCH_THRESHOLD = 100
"""最大算法切换阈值（字符数）"""

# ============ 系统级算法配置常量 ============
# 注意：这些值从 config/algorithm/default.json 加载
DEFAULT_ALGORITHM_CONFIG = {
    "algorithm_switch_threshold": DEFAULT_ALGORITHM_SWITCH_THRESHOLD,
    "enable_triple_probe": True,
    "max_recursion_depth": 30,
    "enable_deduplication": True,
    "dedup_overlap_threshold": 0.5,
    "dedup_adjacent_distance": 30,
    "enable_middle_chunk_probe": True,
    "middle_chunk_overlap_factor": 1.0
}
"""系统级算法配置（用于后备）"""

# ============ 预设名称常量 ============
PRESET_RELAY = "relay"
"""中转网关预设"""

PRESET_OFFICIAL = "official"
"""官方 API 预设"""

PRESET_CUSTOM = "custom"
"""自定义预设"""

VALID_PRESETS = [PRESET_RELAY, PRESET_OFFICIAL, PRESET_CUSTOM]
"""有效的预设列表"""
