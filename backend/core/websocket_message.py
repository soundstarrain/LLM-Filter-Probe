"""
WebSocket 消息格式标准化 (WebSocket Message)

职责：
- 定义统一的 WebSocket 消息格式
- 消除前后端消息格式不一致的问题
- 提供消息构建和验证方法

这个模块确保所有 WebSocket 消息都遵循统一的格式，
避免前端处理不同格式消息的复杂逻辑。
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class WebSocketEventType(str, Enum):
    """WebSocket 事件类型枚举"""
    
    # 扫描生命周期事件
    SCAN_START = "scan_start"
    SCAN_PROGRESS = "progress"
    SCAN_COMPLETE = "scan_complete"
    SCAN_CANCELLED = "scan_cancelled"
    SCAN_ERROR = "scan_error"
    
    # 日志事件
    LOG = "log"
    
    # 关键词发现事件
    KEYWORD_FOUND = "keyword_found"
    
    # 状态事件
    CONNECTION_ESTABLISHED = "connection_established"
    CONNECTION_LOST = "connection_lost"
    
    # 错误事件
    UNKNOWN_STATUS_CODE = "unknown_status_code"
    API_ERROR = "api_error"
    RATE_LIMIT = "rate_limit"


class WebSocketMessage:
    """
    统一的 WebSocket 消息格式
    
    所有消息都遵循以下格式：
    {
        "event": "事件类型",
        "data": {
            "字段1": "值1",
            "字段2": "值2",
            ...
        },
        "timestamp": "ISO 8601 时间戳",
        "session_id": "会话 ID（可选）"
    }
    """

    def __init__(
        self,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        timestamp: Optional[str] = None
    ):
        """
        创建 WebSocket 消息
        
        Args:
            event_type: 事件类型（来自 WebSocketEventType）
            data: 消息数据字典
            session_id: 会话 ID（可选）
            timestamp: 时间戳（如果不提供，使用当前时间）
        """
        self.event_type = event_type
        self.data = data or {}
        self.session_id = session_id
        self.timestamp = timestamp or datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        message = {
            "event": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp,
        }
        
        if self.session_id:
            message["session_id"] = self.session_id
        
        return message

    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'WebSocketMessage':
        """从字典创建消息"""
        return WebSocketMessage(
            event_type=data.get("event"),
            data=data.get("data", {}),
            session_id=data.get("session_id"),
            timestamp=data.get("timestamp")
        )


# 消息构建器 - 提供便捷的消息创建方法

class ScanStartMessage(WebSocketMessage):
    """扫描开始消息"""
    def __init__(self, total_length: int, session_id: Optional[str] = None):
        super().__init__(
            event_type=WebSocketEventType.SCAN_START,
            data={"total_length": total_length},
            session_id=session_id
        )


class ScanProgressMessage(WebSocketMessage):
    """扫描进度消息"""
    def __init__(
        self,
        scanned: int,
        total: int,
        sensitive_count: int = 0,
        session_id: Optional[str] = None
    ):
        super().__init__(
            event_type=WebSocketEventType.SCAN_PROGRESS,
            data={
                "scanned": scanned,
                "total": total,
                "sensitive_count": sensitive_count,
                "progress_percent": int((scanned / total * 100) if total > 0 else 0)
            },
            session_id=session_id
        )


class ScanCompleteMessage(WebSocketMessage):
    """扫描完成消息"""
    def __init__(
        self,
        results: Dict[str, Any],
        sensitive_count: int,
        total_requests: int,
        duration: float,
        session_id: Optional[str] = None
    ):
        super().__init__(
            event_type=WebSocketEventType.SCAN_COMPLETE,
            data={
                "results": results,
                "sensitive_count": sensitive_count,
                "total_requests": total_requests,
                "duration": duration
            },
            session_id=session_id
        )


class ScanCancelledMessage(WebSocketMessage):
    """扫描取消消息"""
    def __init__(self, reason: str = "用户主动停止", session_id: Optional[str] = None):
        super().__init__(
            event_type=WebSocketEventType.SCAN_CANCELLED,
            data={"reason": reason},
            session_id=session_id
        )


class ScanErrorMessage(WebSocketMessage):
    """扫描错误消息"""
    def __init__(
        self,
        error_message: str,
        error_code: Optional[str] = None,
        session_id: Optional[str] = None
    ):
        super().__init__(
            event_type=WebSocketEventType.SCAN_ERROR,
            data={
                "error_message": error_message,
                "error_code": error_code
            },
            session_id=session_id
        )


class LogMessage(WebSocketMessage):
    """日志消息"""
    def __init__(
        self,
        message: str,
        level: str = "info",
        session_id: Optional[str] = None
    ):
        super().__init__(
            event_type=WebSocketEventType.LOG,
            data={
                "message": message,
                "level": level
            },
            session_id=session_id
        )


class KeywordFoundMessage(WebSocketMessage):
    """关键词发现消息"""
    def __init__(
        self,
        keyword: str,
        start_pos: int,
        end_pos: int,
        session_id: Optional[str] = None
    ):
        super().__init__(
            event_type=WebSocketEventType.KEYWORD_FOUND,
            data={
                "keyword": keyword,
                "start_pos": start_pos,
                "end_pos": end_pos,
                "length": end_pos - start_pos
            },
            session_id=session_id
        )


class UnknownStatusCodeMessage(WebSocketMessage):
    """未知状态码消息"""
    def __init__(
        self,
        status_code: int,
        response_snippet: str = "",
        session_id: Optional[str] = None
    ):
        super().__init__(
            event_type=WebSocketEventType.UNKNOWN_STATUS_CODE,
            data={
                "status_code": status_code,
                "response_snippet": response_snippet
            },
            session_id=session_id
        )


class RateLimitMessage(WebSocketMessage):
    """速率限制消息"""
    def __init__(
        self,
        retry_after: Optional[int] = None,
        session_id: Optional[str] = None
    ):
        super().__init__(
            event_type=WebSocketEventType.RATE_LIMIT,
            data={
                "retry_after": retry_after,
                "message": f"API 速率限制，请在 {retry_after} 秒后重试" if retry_after else "API 速率限制"
            },
            session_id=session_id
        )












