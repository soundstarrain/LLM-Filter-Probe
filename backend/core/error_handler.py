"""
统一错误处理 (Error Handler)

职责：
- 定义统一的错误类型和错误代码
- 提供统一的错误响应格式
- 消除前后端错误处理不一致的问题

这个模块确保所有错误都遵循统一的格式，
便于前端统一处理各种错误情况。
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorCode(str, Enum):
    """错误代码枚举"""
    
    # 会话相关错误
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_ALREADY_EXISTS = "SESSION_ALREADY_EXISTS"
    SESSION_INITIALIZATION_FAILED = "SESSION_INITIALIZATION_FAILED"
    
    # 扫描相关错误
    SCAN_NOT_RUNNING = "SCAN_NOT_RUNNING"
    SCAN_ALREADY_RUNNING = "SCAN_ALREADY_RUNNING"
    SCAN_CANCELLED = "SCAN_CANCELLED"
    SCAN_TIMEOUT = "SCAN_TIMEOUT"
    
    # 配置相关错误
    CONFIG_INVALID = "CONFIG_INVALID"
    CONFIG_MISSING_FIELD = "CONFIG_MISSING_FIELD"
    CONFIG_LOAD_FAILED = "CONFIG_LOAD_FAILED"
    
    # API 相关错误
    API_ERROR = "API_ERROR"
    API_TIMEOUT = "API_TIMEOUT"
    API_RATE_LIMIT = "API_RATE_LIMIT"
    API_AUTHENTICATION_FAILED = "API_AUTHENTICATION_FAILED"
    
    # WebSocket 相关错误
    WEBSOCKET_CONNECTION_FAILED = "WEBSOCKET_CONNECTION_FAILED"
    WEBSOCKET_MESSAGE_INVALID = "WEBSOCKET_MESSAGE_INVALID"
    
    # 通用错误
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"


class APIError(Exception):
    """
    API 错误基类
    
    所有 API 错误都应该继承此类，以确保统一的错误处理。
    """

    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        创建 API 错误
        
        Args:
            message: 错误消息
            error_code: 错误代码
            status_code: HTTP 状态码
            details: 额外的错误详情
        """
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        self.timestamp = datetime.now().isoformat()
        
        super().__init__(message)

    def to_response(self) -> Dict[str, Any]:
        """转换为响应格式"""
        return {
            "status": "error",
            "message": self.message,
            "error_code": self.error_code.value,
            "timestamp": self.timestamp,
            "details": self.details
        }

    def to_http_exception(self):
        """转换为 FastAPI HTTPException"""
        from fastapi import HTTPException
        return HTTPException(
            status_code=self.status_code,
            detail=self.to_response()
        )


# 具体的错误类

class SessionNotFoundError(APIError):
    """会话未找到错误"""
    def __init__(self, session_id: str):
        super().__init__(
            message=f"会话 '{session_id}' 未找到",
            error_code=ErrorCode.SESSION_NOT_FOUND,
            status_code=404,
            details={"session_id": session_id}
        )


class SessionAlreadyExistsError(APIError):
    """会话已存在错误"""
    def __init__(self, session_id: str):
        super().__init__(
            message=f"会话 '{session_id}' 已存在",
            error_code=ErrorCode.SESSION_ALREADY_EXISTS,
            status_code=409,
            details={"session_id": session_id}
        )


class SessionInitializationError(APIError):
    """会话初始化失败错误"""
    def __init__(self, session_id: str, reason: str):
        super().__init__(
            message=f"会话 '{session_id}' 初始化失败: {reason}",
            error_code=ErrorCode.SESSION_INITIALIZATION_FAILED,
            status_code=500,
            details={"session_id": session_id, "reason": reason}
        )


class ScanNotRunningError(APIError):
    """扫描未运行错误"""
    def __init__(self, session_id: str):
        super().__init__(
            message=f"会话 '{session_id}' 中没有正在运行的扫描",
            error_code=ErrorCode.SCAN_NOT_RUNNING,
            status_code=400,
            details={"session_id": session_id}
        )


class ScanAlreadyRunningError(APIError):
    """扫描已在运行错误"""
    def __init__(self, session_id: str):
        super().__init__(
            message=f"会话 '{session_id}' 中已有扫描在运行",
            error_code=ErrorCode.SCAN_ALREADY_RUNNING,
            status_code=409,
            details={"session_id": session_id}
        )


class ConfigInvalidError(APIError):
    """配置无效错误"""
    def __init__(self, reason: str, field: Optional[str] = None):
        details = {"reason": reason}
        if field:
            details["field"] = field
        
        super().__init__(
            message=f"配置无效: {reason}",
            error_code=ErrorCode.CONFIG_INVALID,
            status_code=400,
            details=details
        )


class ConfigMissingFieldError(APIError):
    """配置缺少字段错误"""
    def __init__(self, field: str):
        super().__init__(
            message=f"配置缺少必需字段: '{field}'",
            error_code=ErrorCode.CONFIG_MISSING_FIELD,
            status_code=400,
            details={"field": field}
        )


class APITimeoutError(APIError):
    """API 超时错误"""
    def __init__(self, timeout_seconds: float):
        super().__init__(
            message=f"API 请求超时 ({timeout_seconds} 秒)",
            error_code=ErrorCode.API_TIMEOUT,
            status_code=504,
            details={"timeout_seconds": timeout_seconds}
        )


class APIRateLimitError(APIError):
    """API 速率限制错误"""
    def __init__(self, retry_after: Optional[int] = None):
        details = {}
        if retry_after:
            details["retry_after"] = retry_after
        
        message = "API 速率限制"
        if retry_after:
            message += f"，请在 {retry_after} 秒后重试"
        
        super().__init__(
            message=message,
            error_code=ErrorCode.API_RATE_LIMIT,
            status_code=429,
            details=details
        )


class APIAuthenticationError(APIError):
    """API 认证失败错误"""
    def __init__(self, reason: str = "无效的 API 密钥"):
        super().__init__(
            message=f"API 认证失败: {reason}",
            error_code=ErrorCode.API_AUTHENTICATION_FAILED,
            status_code=401,
            details={"reason": reason}
        )


class InternalError(APIError):
    """内部错误"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"内部错误: {message}",
            error_code=ErrorCode.INTERNAL_ERROR,
            status_code=500,
            details=details
        )


# 错误处理工具函数

def handle_error(error: Exception, session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    处理异常并返回统一的错误响应
    
    Args:
        error: 异常对象
        session_id: 会话 ID（可选）
        
    Returns:
        错误响应字典
    """
    if isinstance(error, APIError):
        response = error.to_response()
    else:
        response = {
            "status": "error",
            "message": str(error),
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "timestamp": datetime.now().isoformat(),
            "details": {}
        }
    
    if session_id:
        response["session_id"] = session_id
    
    logger.error(f"错误处理: {response}")
    return response











