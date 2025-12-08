"""
配置加载器模块 (重构版 - 跨平台路径处理)

负责从文件系统同步加载和保存不同层级的配置。
所有函数都是同步的，设计为在独立的线程中被调用。
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

from .config_schema import SystemConfig, APIConfig, SettingsConfig, PresetsConfig

logger = logging.getLogger(__name__)

# --- 路径常量（使用 pathlib.Path 确保跨平台兼容性）---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"
SYSTEM_CONFIG_PATH = CONFIG_DIR / "system.json"
API_CONFIG_PATH = CONFIG_DIR / "API" / "credentials.json"
SETTINGS_CONFIG_PATH = CONFIG_DIR / "settings" / "user.json"
DEFAULT_SETTINGS_PATH = CONFIG_DIR / "settings" / "default.json"
PRESETS_DIR = CONFIG_DIR / "presets"

# --- 同步 I/O 帮助函数 ---

def _load_json_sync(path, default: Any = None) -> Any:
    """同步加载 JSON 文件。"""
    path = Path(path) if not isinstance(path, Path) else path
    if not path.exists():
        logger.debug(f"配置文件不存在: {path}")
        return default if default is not None else {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content:
                logger.warning(f"配置文件为空: {path}")
                return default if default is not None else {}
            return json.loads(content)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"读取或解析配置文件失败 {path}: {e}", exc_info=True)
        return default if default is not None else {}

def _save_json_sync(path, data: Dict[str, Any]):
    """同步保存字典到 JSON 文件。"""
    path = Path(path) if not isinstance(path, Path) else path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[SAVE] 配置文件写入成功: {path}")
    except (IOError, TypeError) as e:
        logger.error(f"[SAVE] 写入配置文件失败: {path}, 错误: {e}", exc_info=True)
        raise

def _get_available_presets_sync() -> List[Dict[str, Any]]:
    """同步获取所有可用的预设列表，包含完整的规则数据。"""
    presets = []
    if not PRESETS_DIR.is_dir():
        logger.warning(f"预设目录不存在: {PRESETS_DIR}")
        return []
    for path in PRESETS_DIR.glob('*.json'):
        preset_data = _load_json_sync(path)
        if 'name' in preset_data and 'display_name' in preset_data:
            presets.append({
                'name': preset_data['name'],
                'display_name': preset_data['display_name'],
                'description': preset_data.get('description', ''),
                'block_status_codes': preset_data.get('block_status_codes', []),
                'block_keywords': preset_data.get('block_keywords', []),
                'retry_status_codes': preset_data.get('retry_status_codes', [429, 502, 503, 504])
            })
    return presets

# --- 系统配置加载 (应用启动时调用，保持同步) ---

_system_config_cache: Optional[SystemConfig] = None
def load_system_config() -> SystemConfig:
    """同步加载系统配置，仅在应用启动时调用。"""
    global _system_config_cache
    if _system_config_cache:
        return _system_config_cache
    data = _load_json_sync(SYSTEM_CONFIG_PATH)
    _system_config_cache = SystemConfig(**data)
    return _system_config_cache
