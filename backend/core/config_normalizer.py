"""
配置规范化器 (Config Normalizer)

职责：
- 统一处理配置字段的别名和类型转换
- 消除配置加载中的重复逻辑
- 确保前后端字段命名一致

这个模块使用 ConfigDefinitions 中的统一规则，避免在多个地方重复定义。
"""
import logging
from typing import Dict, Any, Optional

from .config_definitions import ConfigDefinitions

logger = logging.getLogger(__name__)


class ConfigNormalizer:
    """配置规范化器 - 统一处理字段别名和类型转换"""

    @staticmethod
    def normalize(config: Dict[str, Any], session_id: str = "") -> Dict[str, Any]:
        """
        规范化配置字段
        
        Args:
            config: 原始配置字典
            session_id: 会话 ID（用于日志）
            
        Returns:
            规范化后的配置字典
        """
        normalized = config.copy()
        session_prefix = f"[{session_id}]" if session_id else ""
        
        # 第一步：处理字段别名（使用统一的定义）
        for old_key, new_key in ConfigDefinitions.FIELD_ALIASES.items():
            if old_key in normalized and new_key not in normalized:
                value = normalized.pop(old_key)
                normalized[new_key] = value
                logger.debug(f"{session_prefix} 字段别名映射: {old_key} -> {new_key}")
        
        # 第二步：处理类型转换（使用统一的定义）
        for field_name, target_type in ConfigDefinitions.TYPE_CONVERSIONS.items():
            if field_name in normalized:
                try:
                    current_value = normalized[field_name]
                    if current_value is not None and not isinstance(current_value, target_type):
                        normalized[field_name] = target_type(current_value)
                        logger.debug(
                            f"{session_prefix} 类型转换: {field_name} -> {target_type.__name__}"
                        )
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"{session_prefix} 类型转换失败: {field_name} = {current_value}, 错误: {e}"
                    )
        
        # 第三步：处理列表字段（确保是列表）（使用统一的定义）
        for field_name in ConfigDefinitions.LIST_FIELDS:
            if field_name in normalized:
                value = normalized[field_name]
                if value is None:
                    normalized[field_name] = []
                elif not isinstance(value, list):
                    try:
                        # 尝试将其转换为列表
                        if isinstance(value, str):
                            # 如果是字符串，尝试解析为列表
                            import json
                            normalized[field_name] = json.loads(value)
                        else:
                            normalized[field_name] = list(value)
                        logger.debug(f"{session_prefix} 列表字段转换: {field_name}")
                    except Exception as e:
                        logger.warning(
                            f"{session_prefix} 列表字段转换失败: {field_name} = {value}, 错误: {e}"
                        )
                        normalized[field_name] = []
        
        # 第四步：确保必需字段存在
        if 'name' not in normalized:
            # 如果没有 name，使用 preset 或默认值
            normalized['name'] = normalized.get('preset', 'relay')
            logger.debug(f"{session_prefix} 添加缺失的 name 字段: {normalized['name']}")
        
        return normalized

    @staticmethod
    def validate_preset_fields(config: Dict[str, Any], session_id: str = "") -> bool:
        """
        验证配置是否包含创建 Preset 所需的所有必需字段
        
        Args:
            config: 规范化后的配置字典
            session_id: 会话 ID（用于日志）
            
        Returns:
            是否有效
        """
        session_prefix = f"[{session_id}]" if session_id else ""
        required_fields = ['name']
        
        for field in required_fields:
            if field not in config:
                logger.error(f"{session_prefix} 缺少必需字段: {field}")
                return False
        
        return True

    @staticmethod
    def get_field_mapping_info() -> Dict[str, Any]:
        """获取字段映射信息（用于文档和调试）"""
        return ConfigDefinitions.get_field_mapping_info()











