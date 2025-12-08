"""
Pydantic模型，用于定义各种配置的结构和类型。
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class SystemConfig(BaseModel):
    """系统配置 (system.json)"""
    host: str = "0.0.0.0"
    port: int = 19002
    log_level: str = "INFO"
    cors_origins: List[str] = ["*"]

class APIConfig(BaseModel):
    """API凭证配置 (credentials.json)"""
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    api_model: Optional[str] = None

class SettingsConfig(BaseModel):
    """高级设置 (user.json / default.json)"""
    preset: str = "relay"
    concurrency: int = 15
    timeout_seconds: int = 30
    use_system_proxy: bool = True
    jitter: float = 0.5
    token_limit: int = 20
    delimiter: str = "\n"
    chunk_size: int = 30000
    max_retries: int = 3
    min_granularity: int = 1
    overlap_size: int = 12
    algorithm_mode: str = "hybrid"
    algorithm_switch_threshold: int = 35
    algorithm: Dict[str, Any] = Field(default_factory=dict)

class PresetsConfig(BaseModel):
    """预设规则配置 (presets/*.json)"""
    name: str
    display_name: str
    description: str
    block_status_codes: List[int] = []
    retry_status_codes: List[int] = []
    block_keywords: List[str] = []

class ConfigSchema(SettingsConfig):
    """
    完整的配置 Schema（用于 constants.py 中的默认值加载）
    继承自 SettingsConfig，包含所有高级设置字段
    """
    pass
