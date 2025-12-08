"""
响应分析器 (Response Analyzer)

职责：
- 解析 LLM API 响应
- 检测是否被阻止
- 判断是否需要重试
"""
import logging
from typing import Dict, Any, Optional
from enum import Enum
from ..presets import Preset

logger = logging.getLogger(__name__)

class ScanStatus(str, Enum):
    """扫描状态枚举"""
    SAFE = "SAFE"
    BLOCKED = "BLOCKED"
    MASKED = "MASKED"
    ERROR = "ERROR"
    RETRY = "RETRY"
    UNKNOWN = "UNKNOWN"

class ProbeResult:
    """探测结果类"""
    
    def __init__(self, status: ScanStatus, code: int, body: str = "", response: Optional[Dict] = None, block_reason: Optional[str] = None, is_unknown_error_code: bool = False, block_evidence: Optional[Dict] = None):
        self.status = status
        self.code = code
        self.body = body
        self.response = response or {}
        self.block_reason = block_reason
        self.is_unknown_error_code = is_unknown_error_code
        # 【新增】阻断证据：记录是基于哪个状态码或哪个敏感词
        self.block_evidence = block_evidence or {}
    
    def __eq__(self, other):
        if isinstance(other, ScanStatus):
            return self.status == other
        if isinstance(other, ProbeResult):
            return self.status == other.status
        return False
    
    def __str__(self):
        return f"ProbeResult(status={self.status}, code={self.code})"

class ResponseAnalyzer:
    """响应分析器"""
    
    def __init__(self, preset: Preset, engine_id: str = ""):
        self.preset = preset
        self.engine_id = engine_id or "default"

    def _extract_context(self, text: str, keyword: str, window: int = 50) -> str:
        """以关键词为中心，提取上下文片段。"""
        try:
            pos = text.find(keyword)
            if pos == -1:
                return ""
            
            start = max(0, pos - window)
            end = min(len(text), pos + len(keyword) + window)
            
            context = text[start:end].strip().replace('\n', ' ').replace('\r', '')
            
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(text) else ""
            
            return f"{prefix}{context}{suffix}"
        except Exception:
            return text[max(0, pos - 15):min(len(text), pos + len(keyword) + 15)]

    def analyze(self, status_code: int, response_text: str) -> ProbeResult:
        """分析响应"""
        is_known_error_code = (status_code in self.preset.block_status_codes) or (status_code in self.preset.retry_status_codes)
        is_unknown_error_code = (status_code >= 400) and (not is_known_error_code)
        
        if self.preset.block_keywords:
            for keyword in self.preset.block_keywords:
                if keyword in response_text:
                    logger.debug(f"[{self.engine_id}] 响应包含阻止关键词: {keyword}")
                    context = self._extract_context(response_text, keyword)
                    reason = f"关键词: '{keyword}' (上下文: {context})"
                    # 【新增】记录判断依据：基于敏感词
                    evidence = {
                        "type": "keyword",
                        "value": keyword,
                        "context": context
                    }
                    return ProbeResult(ScanStatus.BLOCKED, status_code, response_text, block_reason=reason, is_unknown_error_code=is_unknown_error_code, block_evidence=evidence)

        if status_code in self.preset.block_status_codes:
            logger.debug(f"[{self.engine_id}] 状态码 {status_code} 在阻止列表中")
            # 【新增】记录判断依据：基于状态码
            evidence = {
                "type": "status_code",
                "value": status_code
            }
            return ProbeResult(ScanStatus.BLOCKED, status_code, response_text, block_reason=f"状态码:{status_code}", is_unknown_error_code=is_unknown_error_code, block_evidence=evidence)

        if status_code in self.preset.retry_status_codes:
            logger.debug(f"[{self.engine_id}] 响应被判定为 RETRY (code={status_code})")
            return ProbeResult(ScanStatus.RETRY, status_code, response_text, is_unknown_error_code=is_unknown_error_code)

        if status_code < 400:
            logger.debug(f"[{self.engine_id}] 响应被判定为 SAFE (code={status_code})")
            return ProbeResult(ScanStatus.SAFE, status_code, response_text, is_unknown_error_code=is_unknown_error_code)

        return ProbeResult(ScanStatus.ERROR, status_code, response_text, is_unknown_error_code=is_unknown_error_code)