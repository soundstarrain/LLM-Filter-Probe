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
    overlap_size: int = Field(
        default=12,
        description="分块间的重叠字符数。建议设为最大敏感词长度的 2 倍以上。注意：此值直接影响切换阈值的最低限制。"
    )
    algorithm_mode: str = "hybrid"
    algorithm_switch_threshold: int = Field(
        default=35,
        description="宏观二分转微观扫描的切换阈值。强烈建议设置为 (overlap_size × 2) + 10（例如重叠12时，设为34；重叠15时，设为40），以获得最佳扫描效率。必须满足 > 2 × overlap_size，否则会导致死循环。"
    )
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
