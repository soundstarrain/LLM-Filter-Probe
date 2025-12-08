"""
配置管理器模块 (重构版)

提供一个完全异步的单例 ConfigManager 类，用于加载、合并和保存多层配置。
所有文件 I/O 操作都在独立的线程中执行，以避免阻塞 asyncio 事件循环。

主要方法:
- load_credentials(): 异步加载 API 凭证
- save_credentials(): 异步保存 API 凭证
- load_settings(): 异步加载合并后的高级设置
- save_settings(): 异步保存高级设置
- load_presets_list(): 异步加载所有可用的预设列表
- load_rules(): 异步加载指定预设的规则
"""
from pathlib import Path
import asyncio
import logging
from typing import Dict, Any, Optional, List

# 检查 to_thread 是否可用 (Python 3.9+)
try:
    from asyncio import to_thread
except ImportError:
    # 为旧版本 Python 提供备用方案
    import functools
    def to_thread(func, /, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, functools.partial(func, *args, **kwargs))

from . import config_loader as loader
from .config_schema import APIConfig, SettingsConfig, PresetsConfig

logger = logging.getLogger(__name__)

class ConfigManager:
    """统一的异步配置管理器。"""
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def load_credentials(self) -> Dict[str, Any]:
        """异步加载 API 凭证。"""
        if not loader.API_CONFIG_PATH.exists():
            logger.warning(f"API 凭证文件不存在: {loader.API_CONFIG_PATH}")
            return {"api_url": "", "api_key": "", "api_model": "gpt-4o-mini"}
        
        data = await to_thread(loader._load_json_sync, loader.API_CONFIG_PATH)
        return APIConfig(**data).dict()

    async def save_credentials(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """异步保存 API 凭证。"""
        async with self._lock:
            existing_data = await to_thread(loader._load_json_sync, loader.API_CONFIG_PATH, default={})
            current_config = APIConfig(**existing_data)
            updated_data = current_config.dict()
            updated_data.update(updates)
            new_config = APIConfig(**updated_data)
            await to_thread(loader._save_json_sync, loader.API_CONFIG_PATH, new_config.dict())
            return new_config.dict()

    async def load_settings(self) -> Dict[str, Any]:
        """异步加载合并后的高级设置。"""
        default_data, user_data = await asyncio.gather(
            to_thread(loader._load_json_sync, loader.DEFAULT_SETTINGS_PATH, default={}),
            to_thread(loader._load_json_sync, loader.SETTINGS_CONFIG_PATH, default={})
        )
        default_settings = SettingsConfig(**default_data).dict()
        user_settings = SettingsConfig(**user_data).dict(exclude_unset=True)
        default_settings.update(user_settings)
        return default_settings

    async def save_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """异步保存高级设置，只保留与默认设置不同的值。"""
        async with self._lock:
            default_data, user_data = await asyncio.gather(
                to_thread(loader._load_json_sync, loader.DEFAULT_SETTINGS_PATH, default={}),
                to_thread(loader._load_json_sync, loader.SETTINGS_CONFIG_PATH, default={})
            )
            
            user_data.update(updates)

            diff_settings = {}
            for key, value in user_data.items():
                if key not in default_data or value != default_data.get(key):
                    diff_settings[key] = value
            
            new_config = SettingsConfig(**diff_settings)
            await to_thread(loader._save_json_sync, loader.SETTINGS_CONFIG_PATH, new_config.dict(exclude_unset=True))
            
            full_config = default_data
            full_config.update(new_config.dict(exclude_unset=True))
            return full_config

    async def load_presets_list(self) -> List[Dict[str, Any]]:
        """异步加载所有可用的预设列表。"""
        return await to_thread(loader._get_available_presets_sync)

    async def load_rules(self, preset_name: str) -> Dict[str, Any]:
        """异步加载指定预设的规则。"""
        path = loader.PRESETS_DIR / f"{preset_name}.json"
        if not path.exists():
            return {}
        data = await to_thread(loader._load_json_sync, path, default={})
        return PresetsConfig(**data).dict() if data else {}

    async def save_rules(self, preset_name: str, rules: Dict[str, Any]) -> Dict[str, Any]:
        """异步保存指定预设的规则。仅支持保存 custom 预设。"""
        async with self._lock:
            if preset_name != 'custom':
                raise ValueError(f"Cannot save rules for preset '{preset_name}'. Only 'custom' preset is writable.")

            path = loader.PRESETS_DIR / f"{preset_name}.json"
            existing_data = await to_thread(loader._load_json_sync, path, default={})
            current_config = PresetsConfig(**existing_data)

            if not current_config.name:
                current_config.name = 'custom'
            if not current_config.display_name:
                current_config.display_name = 'Custom'
            if not current_config.description:
                current_config.description = '用户自定义配置，所有参数均可调整。'

            update_payload = rules.get('custom_rules', {})
            current_config.block_status_codes = update_payload.get('block_status_codes', current_config.block_status_codes)
            current_config.block_keywords = update_payload.get('block_keywords', current_config.block_keywords)
            current_config.retry_status_codes = update_payload.get('retry_status_codes', current_config.retry_status_codes)

            await to_thread(loader._save_json_sync, path, current_config.dict())
            return current_config.dict()

    async def load(self, runtime_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """异步加载并合并所有配置层级。"""
        # 并行加载所有基础配置
        results = await asyncio.gather(
            self.load_settings(),
            self.load_credentials()
        )
        merged_config = results[0]
        api_config = results[1]
        
        # 过滤掉 None 值并合并 API 凭证
        api_config_filtered = {k: v for k, v in api_config.items() if v is not None}
        merged_config.update(api_config_filtered)
        
        # 加载预设规则
        preset_name = merged_config.get('preset', 'relay')
        try:
            preset_rules = await self.load_rules(preset_name)
            if preset_rules:
                merged_config.update(preset_rules)
        except Exception as e:
            logger.warning(f"加载预设 '{preset_name}' 失败: {e}")
        
        # 应用运行时覆盖
        if runtime_overrides:
            merged_config.update(runtime_overrides)
        
        return merged_config

_config_manager_instance: Optional[ConfigManager] = None

def init_config_manager() -> ConfigManager:
    """初始化并返回 ConfigManager 的单例。"""
    global _config_manager_instance
    if _config_manager_instance is None:
        _config_manager_instance = ConfigManager()
    return _config_manager_instance

def get_config_manager() -> ConfigManager:
    """获取 ConfigManager 的单例。"""
    return init_config_manager()
