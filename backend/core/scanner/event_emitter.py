"""
扫描事件发射器 (Scan Event Emitter)

职责：
- 格式化并发送事件（如进度、日志、结果）
- 通过回调函数与 WebSocket 处理器解耦
- 推送错误和警告事件
"""
import logging
from typing import Callable, Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class ScanEventEmitter:
    """负责发送扫描过程中的事件"""

    def __init__(self, callback: Optional[Callable] = None):
        """
        初始化事件发射器

        Args:
            callback: 一个异步函数，用于发送格式化后的消息。
                      例如 `websocket.send_json`
        """
        self.callback = callback
        logger.info(f"ScanEventEmitter initialized. Callback provided: {callback is not None}")

    async def set_callback(self, callback: Callable):
        """
        设置或更新回调函数

        Args:
            callback: 异步回调函数
        """
        self.callback = callback
        logger.info("ScanEventEmitter callback has been set.")

    async def _emit(self, event: Dict[str, Any]):
        """
        通过回调函数发送事件

        Args:
            event: 要发送的事件字典
        """
        if self.callback:
            try:
                await self.callback(event)
            except Exception as e:
                logger.error(f"Error in event emitter callback: {e}", exc_info=True)
        else:
            logger.warning(f"Event emitter callback is not set. Event lost: {event.get('type')}")

    async def handle_unknown_status_code(self, status_code: int, response_snippet: str):
        """
        处理来自 ProbeEngine 的未知状态码事件
        
        Args:
            status_code: 未知的状态码
            response_snippet: 响应体片段
        """
        message = (
            f"⚠️ 检测到未知的响应状态码: {status_code}\n"
            f"响应体片段: {response_snippet[:100]}...\n"
            f"- 如果这是供应商的拦截标志，请将 {status_code} 添加到 block_status_codes\n"
            f"- 如果它表示频率限制或临时错误，请将 {status_code} 添加到 retry_status_codes\n"
            f"- 如果它既不是阻断也不需重试，可忽略此消息"
        )
        await self.log_message("warning", message)

    async def scan_started(self, total_length: int, segment_size: int, config: Optional[Dict[str, Any]] = None):
        """发送扫描开始事件"""
        await self._emit({
            "event": "scan_start",
            "data": {
                "total_length": total_length,
                "segment_size": segment_size,
                "config": config or {},
            }
        })
        # 发送扫描开始日志消息
        await self.log_message("info", f"扫描任务已初始化 | 总字符数: {total_length}")
        
        # 发送配置信息（简洁排版，排除api_key）
        if config:
            config_parts = []
            # 提取并格式化关键配置
            preset = config.get('preset', 'N/A')
            concurrency = config.get('concurrency', 'N/A')
            chunk_size = config.get('chunk_size', 'N/A')
            min_granularity = config.get('min_granularity', 'N/A')
            
            config_parts.append(f"预设: {preset}")
            config_parts.append(f"并发: {concurrency}")
            config_parts.append(f"分块: {chunk_size}")
            config_parts.append(f"粒度: {min_granularity}")

            # 统计规则数量
            block_codes_count = len(config.get('block_status_codes', []))
            retry_codes_count = len(config.get('retry_status_codes', []))
            block_keywords_count = len(config.get('block_keywords', []))
            
            rules_summary = f"规则: 阻断状态码({block_codes_count}), 重试状态码({retry_codes_count}), 阻断关键词({block_keywords_count})"

            await self.log_message("info", f"应用配置 | {' | '.join(config_parts)}")
            await self.log_message("info", f"应用规则 | {rules_summary}")

    async def progress_updated(self, scanned: int, total: int, sensitive_count: int, results: Optional[Dict[str, list]] = None):
        """发送进度更新事件，可选择性携带最新的结果集。"""
        percentage = int(scanned / total * 100) if total > 0 else 0
        
        data = {
            "scanned": scanned,
            "total": total,
            "percentage": percentage,
            "sensitive_count": sensitive_count,
        }
        
        # 如果提供了结果，则将其包含在事件中
        if results is not None:
            data["results"] = results

        await self._emit({
            "event": "progress",
            "data": data
        })

        # 发送进度日志消息
        await self.log_message(
            "info",
            f"🔄 扫描进度: {percentage}% ({scanned}/{total}) | 发现: {sensitive_count} 处"
        )



    async def log_message(self, level: str, message: str):
        """
        发送日志消息事件

        Args:
            level: 日志级别 ('info', 'warning', 'error', 'success')
            message: 日志消息
        """
        await self._emit({
            "event": "log",
            "level": level,
            "message": message,
        })
    
    async def error_occurred(self, error_type: str, message: str, details: Dict = None):
        """
        推送错误事件
        
        Args:
            error_type: 错误类型 ('validation_error', 'api_error', 'timeout', 'scan_error', etc.)
            message: 错误消息
            details: 错误详情字典
        """
        event = {
            'event': 'error',
            'error_type': error_type,
            'message': message,
            'details': details or {},
            'timestamp': datetime.now().isoformat()
        }
        await self._emit(event)
        logger.error(f"错误: {error_type} - {message}")
    
    async def warning_occurred(self, warning_type: str, message: str):
        """
        推送警告事件
        
        Args:
            warning_type: 警告类型
            message: 警告消息
        """
        event = {
            'event': 'warning',
            'warning_type': warning_type,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }
        await self._emit(event)
        logger.warning(f"警告: {warning_type} - {message}")

    async def unknown_status_code_found(self, status_code: int, response_snippet: str = ""):
        """
        发送发现未知状态码的事件
        
        Args:
            status_code: 未知的状态码
            response_snippet: 响应体片段（可选）
        """
        # 发送结构化事件，供前端精细处理
        await self._emit({
            "event": "unknown_status_code",
            "status_code": status_code,
            "response_snippet": response_snippet[:200] if response_snippet else "",
        })
        
        # 同时发送日志消息
        message = (
            f"检测到未知的响应状态码: {status_code}。\n"
            f"- 如果这是供应商的拦截标志, 请将 {status_code} 添加到 block_status_codes。\n"
            f"- 如果它表示频率限制或临时错误 (类似 429), 请将 {status_code} 添加到 retry_status_codes。\n"
            f"- 如果它既不是阻断也不需重试, 可忽略此消息。"
        )
        await self.log_message("warning", message)

    async def scan_completed(self, total_sensitive_found: int, total_requests: int, unknown_codes: list, results: Optional[Dict[str, list]] = None, duration_text: str = None, duration_seconds: float = None):
        """发送扫描完成事件"""
        complete_data = {
            "sensitive_count": total_sensitive_found,
            "total_requests": total_requests,
            "unknown_status_codes": unknown_codes,
            "results": results or {},
        }
        if duration_text is not None:
            complete_data["duration_text"] = duration_text
        if duration_seconds is not None:
            complete_data["duration_seconds"] = round(duration_seconds, 2)

        await self._emit({
            "event": "scan_complete",
            "data": complete_data
        })
        
        # 计算本次扫描的总记录数（所有敏感词的位置总数）
        total_records = 0
        if results:
            for keyword, locations in results.items():
                total_records += len(locations) if isinstance(locations, list) else 0
        
        # 发送扫描完成日志消息
        log_parts = [
            f"共发现 {total_sensitive_found} 处敏感内容",
            f"本次扫描总请求数: {total_requests}"
        ]
        if duration_text:
            log_parts.append(f"总耗时: {duration_text}")
        
        log_message_text = " | ".join(log_parts)
        await self.log_message("success", f"扫描完成 | {log_message_text}")

        if unknown_codes:
            codes_str = ", ".join(map(str, sorted(unknown_codes)))
            await self.log_message(
                "warning",
                f"⚠️ 扫描过程中遇到以下未知状态码: {codes_str}"
            )
            
            # 为每个未知状态码提供建议
            await self.log_message(
                "info",
                "📋 未知状态码处理建议:"
            )
            
            for code in sorted(unknown_codes):
                if code >= 500:
                    # 5xx 错误通常表示服务器错误或阻断
                    await self.log_message(
                        "info",
                        f"  • {code}: 服务器错误 → 建议添加到 'block_status_codes' 或 'retry_status_codes'（如果是临时错误）"
                    )
                elif code == 429:
                    # 429 是速率限制
                    await self.log_message(
                        "info",
                        f"  • {code}: 频率限制 → 建议添加到 'retry_status_codes'（已有默认配置）"
                    )
                elif code == 403:
                    # 403 是禁止访问
                    await self.log_message(
                        "info",
                        f"  • {code}: 禁止访问 → 建议添加到 'block_status_codes'（表示被阻断）"
                    )
                elif code == 401:
                    # 401 是未授权
                    await self.log_message(
                        "info",
                        f"  • {code}: 未授权 → 检查 API 密钥或认证配置"
                    )
                elif code == 404:
                    # 404 是未找到
                    await self.log_message(
                        "info",
                        f"  • {code}: 未找到 → 检查 API 端点配置，可能需要忽略"
                    )
                elif code >= 400 and code < 500:
                    # 其他 4xx 错误
                    await self.log_message(
                        "info",
                        f"  • {code}: 客户端错误 → 检查请求配置，可能需要添加到 'block_status_codes' 或忽略"
                    )
            
            await self.log_message(
                "info",
                "💡 提示: 根据您的 API 行为，选择合适的处理方式并更新配置文件。"
            )

