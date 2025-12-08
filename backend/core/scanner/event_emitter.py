"""
扫描事件发射器 (Scan Event Emitter)

职责：
- 格式化并发送事件（如进度、日志、结果）
- 通过回调函数与 WebSocket 处理器解耦
- 推送错误和警告事件
- 实现批量发送和节流机制，减少前端卡顿

优化策略：
1. 进度节流：限制每秒最多 5 次进度更新
2. 结果缓冲：攒够 10 个敏感词或 0.5 秒后统一发送
"""
import logging
import asyncio
import time
from typing import Callable, Optional, Dict, Any, List
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
        
        # 【新增】进度节流参数
        self.last_progress_time = 0.0
        self.progress_min_interval = 0.2  # 最小间隔 200ms（每秒最多 5 次）
        
        # 【新增】结果缓冲参数
        self.findings_buffer: List[Dict[str, Any]] = []
        self.last_findings_flush_time = 0.0
        self.findings_flush_interval = 0.5  # 最多 0.5 秒发送一次
        self.findings_batch_size = 10  # 缓冲 10 个敏感词时发送
        
        # 【修复】移除此处的初始化日志，避免信息混乱
        # logger.info(f"ScanEventEmitter initialized. Callback provided: {callback is not None}")

    async def set_callback(self, callback: Callable):
        """
        设置或更新回调函数

        Args:
            callback: 异步回调函数
        """
        self.callback = callback
        # 【修复】移除此处的日志，避免重复
        # logger.info("ScanEventEmitter callback has been set.")

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



    async def scan_started(self, total_length: int, segment_size: int, config: Optional[Dict[str, Any]] = None):
        """发送扫描开始事件，统一输出重要参数"""
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
        
        # 统一输出所有重要参数（分组显示）
        if config:
            # ========== 【文本处理参数】 ==========
            chunk_size = config.get('chunk_size', 'N/A')
            overlap_size = config.get('overlap_size', 'N/A')
            
            await self.log_message(
                "info",
                f"【文本处理】分块大小={chunk_size} | 重叠大小={overlap_size}"
            )
            
            # ========== 【并发与网络参数】 ==========
            concurrency = config.get('concurrency', 'N/A')
            timeout_seconds = config.get('timeout_seconds', 'N/A')
            max_retries = config.get('max_retries', 'N/A')
            
            await self.log_message(
                "info",
                f"【网络参数】并发数={concurrency} | 超时时间={timeout_seconds}秒 | 最大重试={max_retries}次"
            )
            
            # ========== 【算法参数】 ==========
            min_granularity = config.get('min_granularity', 'N/A')
            algorithm_switch_threshold = config.get('algorithm_switch_threshold', 'N/A')
            algorithm_mode = config.get('algorithm_mode', 'N/A')
            
            await self.log_message(
                "info",
                f"【算法参数】模式={algorithm_mode} | 最小粒度={min_granularity} | 切换阈值={algorithm_switch_threshold}"
            )
            
            # ========== 【规则配置】 ==========
            preset = config.get('preset', 'N/A')
            block_codes = config.get('block_status_codes', [])
            retry_codes = config.get('retry_status_codes', [])
            block_keywords = config.get('block_keywords', [])
            
            # 【修复】确保计算的是列表长度，而不是字符串长度
            block_codes_count = len(block_codes) if isinstance(block_codes, list) else 0
            retry_codes_count = len(retry_codes) if isinstance(retry_codes, list) else 0
            
            # 【修复】block_keywords 可能是列表或字符串，需要正确处理
            if isinstance(block_keywords, list):
                block_keywords_count = len(block_keywords)
            elif isinstance(block_keywords, str):
                # 如果是字符串，尝试解析为列表
                try:
                    import json
                    parsed = json.loads(block_keywords)
                    block_keywords_count = len(parsed) if isinstance(parsed, list) else 0
                except:
                    # 如果解析失败，计数为0
                    block_keywords_count = 0
            else:
                block_keywords_count = 0
            
            await self.log_message(
                "info",
                f"【规则配置】预设={preset} | 阻断状态码({block_codes_count}) | 重试状态码({retry_codes_count}) | 阻断关键词({block_keywords_count})"
            )

    async def progress_updated(self, scanned: int, total: int, sensitive_count: int, results: Optional[Dict[str, list]] = None, force: bool = False):
        """
        发送进度更新事件，可选择性携带最新的结果集。
        
        【新增】实现进度节流：限制每秒最多 5 次更新，确保最后一次 (100%) 一定会被发送。
        【修复】对于小文本（<= 100 字），总是发送进度更新，不进行节流。
        
        Args:
            scanned: 已扫描字符数
            total: 总字符数
            sensitive_count: 发现的敏感词数
            results: 最新的结果字典（可选）
            force: 是否强制发送（用于 100% 或最后一次更新）
        """
        current_time = time.time()
        percentage = int(scanned / total * 100) if total > 0 else 0
        
        # 【修复】节流逻辑：
        # 1. force=True 时强制发送
        # 2. 进度达到 100% 时总是发送（确保进度条完成）
        # 3. 小文本（<= 100 字）总是发送，不进行节流
        # 4. 其他情况检查时间间隔
        should_send = (
            force or 
            percentage == 100 or  # 【关键修复】100% 时总是发送
            total <= 100 or  # 小文本总是发送
            (current_time - self.last_progress_time >= self.progress_min_interval)
        )
        
        if not should_send:
            logger.debug(f"[Progress] 节流：跳过此次更新 (距离上次 {current_time - self.last_progress_time:.2f}s)")
            return
        
        self.last_progress_time = current_time
        
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
        # 【修复】只在进度有明显变化时才发送日志，避免日志过多
        if percentage % 10 == 0 or percentage == 100:
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

    async def handle_unknown_status_code(self, status_code: int, response_snippet: str = ""):
        """
        处理未知状态码（与 unknown_status_code_found 功能相同）
        
        这个方法是为了兼容 text_scanner.py 中的调用而添加的。
        
        Args:
            status_code: 未知的状态码
            response_snippet: 响应体片段（可选）
        """
        await self.unknown_status_code_found(status_code, response_snippet)

    async def scan_completed(self, total_sensitive_found: int, total_requests: int, unknown_codes: list, results: Optional[Dict[str, list]] = None, duration_text: str = None, duration_seconds: float = None, unknown_code_counts: Optional[Dict[int, int]] = None, sensitive_word_evidence: Optional[Dict[str, Dict]] = None):
        """发送扫描完成事件"""
        # 【新增】在扫描完成前，确保所有缓冲的敏感词都被发送
        await self.flush_all()
        
        complete_data = {
            "sensitive_count": total_sensitive_found,
            "total_requests": total_requests,
            "unknown_status_codes": unknown_codes,
            "results": results or {},
        }
        # 【新增】添加未知状态码统计和敏感词判断依据
        if unknown_code_counts is not None:
            complete_data["unknown_status_code_counts"] = unknown_code_counts
        if sensitive_word_evidence is not None:
            complete_data["sensitive_word_evidence"] = sensitive_word_evidence
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
                "未知状态码处理建议:"
            )
            
            for code in sorted(unknown_codes):
                if code >= 500:
                    # 5xx 错误通常表示服务器错误或阻断
                    await self.log_message(
                        "info",
                        f"  Code{code}: 服务器错误 → 建议添加到 'block_status_codes' 或 'retry_status_codes'（如果是临时错误）"
                    )
                elif code == 429:
                    # 429 是速率限制
                    await self.log_message(
                        "info",
                        f"  Code{code}: 频率限制 → 建议添加到 'retry_status_codes'（已有默认配置）"
                    )
                elif code == 403:
                    # 403 是禁止访问
                    await self.log_message(
                        "info",
                        f"  Code{code}: 禁止访问 → 建议添加到 'block_status_codes'（表示被阻断）"
                    )
                elif code == 401:
                    # 401 是未授权
                    await self.log_message(
                        "info",
                        f"  Code{code}: 未授权 → 检查 API 密钥或认证配置"
                    )
                elif code == 404:
                    # 404 是未找到
                    await self.log_message(
                        "info",
                        f"  Code{code}: 未找到 → 检查 API 端点配置，可能需要忽略"
                    )
                elif code >= 400 and code < 500:
                    # 其他 4xx 错误
                    await self.log_message(
                        "info",
                        f"  Code{code}: 客户端错误 → 检查请求配置，可能需要添加到 'block_status_codes' 或忽略"
                    )
            
            await self.log_message(
                "info",
                "💡 提示: 根据您的 API 行为，选择合适的处理方式并更新配置文件。"
            )

    async def sensitive_found(self, keyword: str, start_pos: int, end_pos: int):
        """
        【新增】发送敏感词发现事件（使用缓冲和批量发送）
        
        不直接发送，而是加入缓冲区。当缓冲区达到阈值或时间阈值时，
        统一以 sensitive_found_batch 事件发送。
        
        Args:
            keyword: 敏感词
            start_pos: 起始位置
            end_pos: 结束位置
        """
        # 添加到缓冲区
        self.findings_buffer.append({
            "keyword": keyword,
            "start": start_pos,
            "end": end_pos
        })
        
        # 检查是否应该发送
        current_time = time.time()
        should_flush = (
            len(self.findings_buffer) >= self.findings_batch_size or
            (current_time - self.last_findings_flush_time >= self.findings_flush_interval)
        )
        
        if should_flush:
            await self.flush_findings()

    async def flush_findings(self):
        """
        【新增】立即发送缓冲中的所有敏感词
        """
        if not self.findings_buffer:
            return
        
        current_time = time.time()
        batch_size = len(self.findings_buffer)
        
        # 发送批量事件
        await self._emit({
            "event": "sensitive_found_batch",
            "data": {
                "findings": self.findings_buffer.copy()
            }
        })
        
        logger.debug(f"[Batch] 发送 {batch_size} 个敏感词")
        
        # 清空缓冲区
        self.findings_buffer.clear()
        self.last_findings_flush_time = current_time

    async def flush_all(self):
        """
        【新增】扫描结束时，确保所有缓冲的敏感词都被发送
        """
        if self.findings_buffer:
            logger.info(f"[Batch] 扫描结束，发送剩余 {len(self.findings_buffer)} 个敏感词")
            await self.flush_findings()
