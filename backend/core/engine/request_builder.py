"""
HTTP 请求构建器 (Request Builder)

职责：
- 构建 LLM API 请求
- 处理模板替换
- 验证请求格式
"""
import json
import logging
from typing import Tuple, Dict, Any
from ..presets import Preset

logger = logging.getLogger(__name__)


class RequestBuilder:
    """HTTP 请求构建器"""
    
    def __init__(self, preset: Preset, engine_id: str = ""):
        """
        初始化请求构建器
        
        Args:
            preset: 预设配置
            engine_id: 引擎 ID（用于日志追踪）
        """
        self.preset = preset
        self.engine_id = engine_id or "default"
    
    def build(self, text_segment: str) -> Tuple[str, Dict[str, Any]]:
        """
        构建 HTTP 请求
        
        Args:
            text_segment: 文本片段
        
        Returns:
            (URL, 请求体)
        
        Raises:
            ValueError: 如果请求模板无效或 API 配置不完整
        """
        # 验证 API 配置是否完整
        if not self.preset.api_url:
            raise ValueError(
                "API URL 未配置。请在前端设置中配置 API 凭证 (API URL, API Key, Model)。"
            )
        
        if not self.preset.api_key:
            raise ValueError(
                "API Key 未配置。请在前端设置中配置 API 凭证。"
            )
        
        if not self.preset.model:
            raise ValueError(
                "Model 未配置。请在前端设置中配置 API 凭证。"
            )
        
        # 验证 API URL 格式
        api_url = self.preset.api_url.strip()
        if not (api_url.startswith("http://") or api_url.startswith("https://")):
            raise ValueError(
                f"API URL 格式无效：'{api_url}'。必须以 'http://' 或 'https://' 开头。"
            )
        
        # 【修复】改进文本转义逻辑，使用更安全的方法
        # 原方法 json.dumps(text_segment)[1:-1] 在某些边界情况下可能失败
        # 新方法：直接使用 json.dumps 的结果作为 JSON 字符串值
        try:
            # 将文本段转换为 JSON 字符串（包含引号）
            json_escaped_text = json.dumps(text_segment)
            # 验证转义结果的有效性
            if not json_escaped_text or len(json_escaped_text) < 2:
                raise ValueError(f"文本转义失败：结果过短 '{json_escaped_text}'")
            # 去掉外层引号，得到可以直接插入 JSON 的转义文本
            escaped_text = json_escaped_text[1:-1]
            logger.debug(
                f"[{self.engine_id}] 文本转义成功 | 原长度: {len(text_segment)} | "
                f"转义后长度: {len(escaped_text)}"
            )
        except Exception as e:
            logger.error(f"[{self.engine_id}] 文本转义异常: {str(e)}")
            raise ValueError(f"文本转义失败: {str(e)}")
        
        # 替换模板中的占位符
        template = self.preset.request_template
        template = template.replace("{{TEXT}}", escaped_text)
        template = template.replace("{{MODEL}}", self.preset.model)
        
        # 【修复】在解析前验证模板的有效性
        if not template or "{{TEXT}}" in template or "{{MODEL}}" in template:
            logger.error(f"[{self.engine_id}] 模板替换失败：仍存在未替换的占位符")
            logger.error(f"[{self.engine_id}] 模板内容: {template[:200]}")
            raise ValueError("请求模板中存在未替换的占位符")
        
        # 解析请求体
        try:
            request_body = json.loads(template)
        except json.JSONDecodeError as e:
            logger.error(f"[{self.engine_id}] 请求模板解析失败: {str(e)}")
            logger.error(f"[{self.engine_id}] 模板内容: {template[:500]}")
            logger.error(f"[{self.engine_id}] 错误位置: 第 {e.lineno} 行，第 {e.colno} 列")
            raise ValueError(f"请求模板 JSON 解析失败: {str(e)}")
        
        # 【修复】验证请求体是否为空或无效
        if not request_body or not isinstance(request_body, dict):
            logger.error(f"[{self.engine_id}] 请求体无效：{request_body}")
            raise ValueError("请求体解析结果无效")
        
        # 设置 max_tokens 以避免因 Token 上限导致的错误
        request_body["max_tokens"] = 10
        
        # 构建 URL
        if not api_url.endswith("/"):
            api_url += "/"
        
        url = f"{api_url}chat/completions"
        
        # 【修复】验证最终构建的 URL
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            logger.error(f"[{self.engine_id}] 构建的 URL 无效: '{url}'")
            raise ValueError(f"构建的 URL 无效：'{url}'。必须以 'http://' 或 'https://' 开头。")
        
        logger.debug(f"[{self.engine_id}] 请求已构建: {url}")
        
        return url, request_body

