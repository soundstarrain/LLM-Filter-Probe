"""
配置定义和验证规则 - 统一的配置元数据

集中管理所有配置相关的定义：
- 字段分类（凭证、设置、规则）
- 字段别名映射
- 类型转换规则
- 验证规则

这个模块是配置管理层的"单一事实来源"，避免在多个地方重复定义相同的规则。
"""
import logging
from typing import Dict, Any, Callable, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ConfigDefinitions:
    """统一的配置字段定义和验证规则"""
    
    # ========== 字段分类 ==========
    # 凭证相关字段
    CREDENTIAL_KEYS = {
        'api_url',
        'api_key',
        'api_model',
    }
    
    # 设置相关字段
    SETTINGS_KEYS = {
        'chunk_size',
        'timeout',
        'timeout_seconds',
        'concurrency',
        'max_retries',
        'overlap_size',
        'min_granularity',
        'algorithm_mode',
        'algorithm_switch_threshold',
    }
    
    # 规则相关字段
    RULE_KEYS = {
        'block_status_codes',
        'block_keywords',
        'retry_status_codes',
        'preset',
        'name',
    }
    
    # ========== 字段别名映射 ==========
    # 旧字段名 -> 新字段名
    FIELD_ALIASES = {
        'api_model': 'model',
        'timeout_seconds': 'timeout',
        'preset': 'name',
    }
    
    # ========== 类型转换规则 ==========
    TYPE_CONVERSIONS = {
        'timeout': float,
        'timeout_seconds': float,
        'concurrency': int,
        'chunk_size': int,
        'max_retries': int,
        'token_limit': int,
        'min_granularity': int,
        'overlap_size': int,
        'algorithm_switch_threshold': int,
    }
    
    # ========== 列表字段 ==========
    # 确保这些字段始终是列表类型
    LIST_FIELDS = {
        'block_status_codes',
        'block_keywords',
        'retry_status_codes',
    }
    
    # ========== 验证规则 ==========
    # 每个字段的验证规则
    VALIDATION_RULES = {
        'api_url': {
            'required': True,
            'type': str,
            'validator': 'validate_url',
            'error_msg': 'api_url 必须是有效的 URL'
        },
        'api_key': {
            'required': True,
            'type': str,
            'min_length': 1,
            'error_msg': 'api_key 不能为空'
        },
        'api_model': {
            'required': True,
            'type': str,
            'min_length': 1,
            'error_msg': 'api_model 不能为空'
        },
        'concurrency': {
            'required': False,
            'type': int,
            'min': 1,
            'max': 100,
            'default': 20,
            'error_msg': 'concurrency 必须是 1-100 之间的整数'
        },
        'timeout': {
            'required': False,
            'type': float,
            'min': 1,
            'max': 300,
            'default': 30.0,
            'error_msg': 'timeout 必须是 1-300 秒之间的数字'
        },
        'chunk_size': {
            'required': False,
            'type': int,
            'min': 1,
            'default': 50000,
            'error_msg': 'chunk_size 必须大于 0'
        },
        'max_retries': {
            'required': False,
            'type': int,
            'min': 0,
            'default': 3,
            'error_msg': 'max_retries 必须是非负整数'
        },
        'overlap_size': {
            'required': False,
            'type': int,
            'min': 0,
            'default': 10,
            'error_msg': 'overlap_size 不能为负数'
        },
        'min_granularity': {
            'required': False,
            'type': int,
            'min': 1,
            'default': 30,
            'error_msg': 'min_granularity 必须大于 0'
        },
        'algorithm_mode': {
            'required': False,
            'type': str,
            'allowed_values': ['binary', 'precision', 'hybrid'],
            'default': 'hybrid',
            'error_msg': 'algorithm_mode 必须是 binary、precision 或 hybrid'
        },
        'algorithm_switch_threshold': {
            'required': False,
            'type': int,
            'min': 1,
            'default': 50,
            'error_msg': 'algorithm_switch_threshold 必须大于 0'
        },
    }
    
    # ========== 验证函数 ==========
    
    @staticmethod
    def validate_url(url: str) -> Tuple[bool, Optional[str]]:
        """验证 URL 格式"""
        try:
            result = urlparse(url)
            if not all([result.scheme, result.netloc]):
                return False, "URL 格式不正确，必须包含 scheme 和 netloc"
            return True, None
        except Exception as e:
            return False, f"URL 解析失败: {e}"
    
    @staticmethod
    def validate_field(field_name: str, value: Any) -> Tuple[bool, Optional[str]]:
        """
        验证单个字段
        
        Args:
            field_name: 字段名
            value: 字段值
            
        Returns:
            (是否有效, 错误信息)
        """
        rule = ConfigDefinitions.VALIDATION_RULES.get(field_name)
        
        # 如果没有定义验证规则，认为有效
        if not rule:
            return True, None
        
        # 检查必填字段
        if rule.get('required', False) and not value:
            return False, rule.get('error_msg', f'{field_name} 是必填字段')
        
        # 如果值为空且不是必填，则有效
        if not value:
            return True, None
        
        # 检查类型
        expected_type = rule.get('type')
        if expected_type and not isinstance(value, expected_type):
            return False, f'{field_name} 类型应为 {expected_type.__name__}，但收到 {type(value).__name__}'
        
        # 检查最小长度
        if 'min_length' in rule and isinstance(value, str):
            if len(value) < rule['min_length']:
                return False, f'{field_name} 长度不能少于 {rule["min_length"]} 个字符'
        
        # 检查最小值
        if 'min' in rule and isinstance(value, (int, float)):
            if value < rule['min']:
                return False, f'{field_name} 不能小于 {rule["min"]}'
        
        # 检查最大值
        if 'max' in rule and isinstance(value, (int, float)):
            if value > rule['max']:
                return False, f'{field_name} 不能大于 {rule["max"]}'
        
        # 检查允许的值
        if 'allowed_values' in rule:
            if value not in rule['allowed_values']:
                return False, f'{field_name} 必须是以下之一: {", ".join(rule["allowed_values"])}'
        
        # 执行自定义验证函数
        if 'validator' in rule:
            validator_name = rule['validator']
            validator_func = getattr(ConfigDefinitions, validator_name, None)
            if validator_func and callable(validator_func):
                is_valid, error_msg = validator_func(value)
                if not is_valid:
                    return False, error_msg
        
        return True, None
    
    @staticmethod
    def validate_config(config: Dict[str, Any]) -> Tuple[bool, Dict[str, str]]:
        """
        验证整个配置字典
        
        Args:
            config: 配置字典
            
        Returns:
            (是否有效, 错误字典 {字段名: 错误信息})
        """
        errors = {}
        
        for field_name, value in config.items():
            is_valid, error_msg = ConfigDefinitions.validate_field(field_name, value)
            if not is_valid:
                errors[field_name] = error_msg
        
        return len(errors) == 0, errors
    
    @staticmethod
    def get_field_category(field_name: str) -> Optional[str]:
        """获取字段所属的类别"""
        if field_name in ConfigDefinitions.CREDENTIAL_KEYS:
            return 'credential'
        elif field_name in ConfigDefinitions.SETTINGS_KEYS:
            return 'settings'
        elif field_name in ConfigDefinitions.RULE_KEYS:
            return 'rules'
        return None
    
    @staticmethod
    def get_default_value(field_name: str) -> Any:
        """获取字段的默认值"""
        rule = ConfigDefinitions.VALIDATION_RULES.get(field_name)
        if rule and 'default' in rule:
            return rule['default']
        return None
    
    @staticmethod
    def get_field_mapping_info() -> Dict[str, Any]:
        """获取字段映射信息（用于文档和调试）"""
        return {
            'aliases': ConfigDefinitions.FIELD_ALIASES,
            'type_conversions': {k: v.__name__ for k, v in ConfigDefinitions.TYPE_CONVERSIONS.items()},
            'list_fields': list(ConfigDefinitions.LIST_FIELDS),
            'credential_keys': list(ConfigDefinitions.CREDENTIAL_KEYS),
            'settings_keys': list(ConfigDefinitions.SETTINGS_KEYS),
            'rule_keys': list(ConfigDefinitions.RULE_KEYS),
        }

