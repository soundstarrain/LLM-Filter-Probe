"""
核心探针引擎 (Probe Engine)

职责：
- 协调请求构建、响应分析、重试处理
- 管理 HTTP 客户端生命周期
- 提供统一的探测接口
- 管理等长延迟掩码 (Iso-Length Lazy Masking)
"""
import asyncio
import logging
import json
import random
from datetime import datetime
from typing import Dict, Any, Optional, List, Set

# 动态导入 ScanEventEmitter 以避免循环依赖
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..scanner.event_emitter import ScanEventEmitter

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    AsyncRetrying,
    RetryError
)
import httpx

from ..presets import Preset
from utils.http_client import AsyncHttpClient
from .request_builder import RequestBuilder
from .response_analyzer import ResponseAnalyzer, ScanStatus, ProbeResult
from .retry_handler import RetryHandler
from .global_mask_manager import GlobalMaskManager
from ..constants import DEFAULT_ERROR_RECOVERY_MAX_BACKOFF

logger = logging.getLogger(__name__)


class ProbeEngine:
    """
    核心探针引擎，负责与外部 API 进行所有交互。

    核心逻辑：
    - **SAFE**: API 响应成功（例如，HTTP 状态码 200 OK）。
    - **BLOCKED**: API 响应表明请求被拦截。这基于以下任一条件：
        1. 响应的 HTTP 状态码在 `block_status_codes` 列表中。
        2. 响应体内容包含 `block_keywords` 列表中的任何关键字。
    - **RETRY**: API 响应表明这是一个临时性错误，应进行重试（例如，HTTP 状态码 429 或 502）。
    """

    def __init__(self, preset: Preset, engine_id: str = ""):
        """
        初始化探针引擎

        Args:
            preset: 预设配置
            engine_id: 引擎 ID（用于日志追踪）
        """
        self.preset = preset
        self.engine_id = engine_id or "default"

        # 初始化子模块
        self.request_builder = RequestBuilder(preset, engine_id)
        self.response_analyzer = ResponseAnalyzer(preset, engine_id)
        self.retry_handler = RetryHandler(preset, engine_id)

        # HTTP 客户端
        self.http_client: Optional[AsyncHttpClient] = None

        # 统计数据
        self.request_count = 0
        self.blocked_count = 0
        self.safe_count = 0
        self.error_count = 0
        self.unknown_status_codes: Set[int] = set()
        self.unknown_status_code_counts: Dict[int, int] = {}  # 【新增】未知状态码出现次数统计
        self.reported_unknown_codes: Set[int] = set()  # 跟踪已报告的未知状态码，避免重复推送
        self.sensitive_word_evidence: Dict[str, Dict] = {}  # 【新增】敏感词判断依据记录

        # 事件发射器和回调
        self.event_emitter: Optional['ScanEventEmitter'] = None
        self.event_callback = None
        
        # 【新增】等长延迟掩码管理器
        self.mask_manager = GlobalMaskManager(mask_char="*")
        self.mask_patterns: Set[str] = set()  # 保留向后兼容性

        logger.info(
            f"[{self.engine_id}] 探针引擎已初始化 | "
            f"preset={preset.name} | concurrency={preset.concurrency} | timeout={preset.timeout}s"
        )

    async def set_event_emitter(self, emitter: 'ScanEventEmitter'):
        """
        设置事件发射器实例。
        为实现解耦，引擎不直接调用发射器的方法，而是通过一个通用的回调接口。
        """
        self.event_emitter = emitter
        if emitter:
            self.event_callback = emitter._emit
        logger.info(f"[{self.engine_id}] 事件发射器已设置")

    def set_mask_patterns(self, patterns: Set[str]):
        """
        设置用于在探测前屏蔽已知敏感词的模式。
        
        【新增】同时更新 GlobalMaskManager，以支持等长延迟掩码。
        """
        self.mask_patterns = patterns
        
        # 同步到 GlobalMaskManager
        if self.mask_manager:
            # 清空旧的关键词
            self.mask_manager.reset()
            # 添加新的关键词
            for pattern in patterns:
                self.mask_manager.add_keyword(pattern)
            
            logger.debug(
                f"[{self.engine_id}] 已同步掩码模式到 GlobalMaskManager | "
                f"模式数: {len(patterns)}"
            )

    async def initialize(self):
        """初始化 HTTP 客户端"""
        if self.http_client is None:
            self.http_client = AsyncHttpClient(
                timeout=self.preset.timeout,
                max_retries=self.preset.max_retries,
                keep_alive=True,
                max_keepalive_connections=self.preset.concurrency,
                max_connections=self.preset.concurrency,
                use_system_proxy=self.preset.use_system_proxy
            )
            await self.http_client.connect()
            logger.info(f"[{self.engine_id}] HTTP 客户端已初始化")

    async def cleanup(self):
        """清理资源"""
        if self.http_client:
            await self.http_client.close()
            self.http_client = None
            logger.info(f"[{self.engine_id}] HTTP 客户端已关闭")

    def _mask_text(self, text: str) -> str:
        """
        使用等长延迟掩码对文本进行屏蔽。
        
        【关键改进】：
        - 使用 GlobalMaskManager 的 apply_masks 方法进行等长替换
        - 替换为 '*' 而非 '[MASK]'，保持文本长度一致
        - 这样 API 不会因为长度变化而产生坐标偏移
        """
        if not self.mask_manager:
            return text
        
        # 使用 GlobalMaskManager 的等长替换
        masked_text = self.mask_manager.apply_masks(text)
        
        # 验证长度一致性
        if len(masked_text) != len(text):
            logger.warning(
                f"[{self.engine_id}] 掩码后文本长度不一致！"
                f"原长度={len(text)}, 掩码后长度={len(masked_text)}"
            )
        
        return masked_text

    async def _perform_http_request(self, url: str, request_body: Dict, headers: Dict, text_segment: str) -> tuple:
        """
        执行单个 HTTP 请求（内部方法，由 tenacity 装饰）
        
        Returns:
            (status_code, response_json, request_id) 元组
        """
        text_hash = hash(text_segment) & 0xffff
        logger.debug(
            f"[{self.engine_id}] 正在探测 | 长度: {len(text_segment)} | "
            f"Hash: {text_hash:04x}"
        )
        logger.debug(f"[{self.engine_id}] 请求体: {json.dumps(request_body, ensure_ascii=False)[:500]}")

        status_code, response_json, request_id = await self.http_client.post(
            url,
            request_body,
            headers=headers
        )
        return status_code, response_json, request_id

    async def probe(self, text_segment: str, bypass_mask: bool = False) -> ProbeResult:
        """
        探测文本片段

        Args:
            text_segment: 文本片段
            bypass_mask: 是否跳过动态掩码。在验证阶段设置为 True，以确保裸词不被已知掩码干扰。

        Returns:
            ProbeResult 对象
        """
        if not self.http_client:
            await self.initialize()

        # 【延迟掩码机制】在获得信号量后、发送请求前应用掩码
        # 这样可以充分利用前面任务发现的敏感词，减少 API 调用
        # 【验证阶段优化】当 bypass_mask=True 时，跳过掩码，直接发送裸词进行验证
        if bypass_mask:
            masked_segment = text_segment
            logger.debug(
                f"[{self.engine_id}] [Validation] 跳过掩码，直接验证裸词 | "
                f"长度: {len(text_segment)}"
            )
        else:
            masked_segment = self._mask_text(text_segment)

        self.request_count += 1

        try:
            url, request_body = self.request_builder.build(masked_segment)
        except Exception as e:
            logger.error(f"[{self.engine_id}] 构建请求失败: {str(e)}")
            self.error_count += 1
            return ProbeResult(ScanStatus.ERROR, 0, str(e))

        headers = {
            "Authorization": f"Bearer {self.preset.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Connection": "keep-alive",
        }

        # 使用 tenacity 进行强力重试
        retry_config = retry(
            stop=stop_after_attempt(5),  # 增加重试次数到 5 次
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((
                asyncio.TimeoutError,
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.NetworkError,
                ConnectionError,
                OSError
            )),
            reraise=True,  # 关键：重试失败后抛出异常，而不是返回 None/Safe
            before_sleep=before_sleep_log(logger, logging.WARNING)
        )

        try:
            # 应用 tenacity 重试装饰器
            retrying = AsyncRetrying(
                stop=stop_after_attempt(5),
                wait=wait_exponential(multiplier=1, min=1, max=10),
                retry=retry_if_exception_type((
                    asyncio.TimeoutError,
                    httpx.TimeoutException,
                    httpx.ConnectError,
                    httpx.ReadTimeout,
                    httpx.NetworkError,
                    ConnectionError,
                    OSError
                )),
                reraise=True,
                before_sleep=before_sleep_log(logger, logging.WARNING)
            )

            status_code, response_json, request_id = None, None, None
            async for attempt in retrying:
                with attempt:
                    status_code, response_json, request_id = await self._perform_http_request(
                        url, request_body, headers, text_segment
                    )

            response_text = json.dumps(response_json, ensure_ascii=False)
            logger.info(
                f"[{self.engine_id}] 响应接收 | 状态码: {status_code} | "
                f"大小: {len(response_text)} 字节 | 长度: {len(text_segment)} | RequestID: {request_id}"
            )
            logger.debug(f"[{self.engine_id}] 响应体: {response_text[:500]}")

            if status_code in self.preset.retry_status_codes:
                logger.error(f"[{self.engine_id}] 收到重试状态码 {status_code}，已重试多次仍未成功")
                self.error_count += 1
                return ProbeResult(ScanStatus.ERROR, status_code, response_text)

            result = self.response_analyzer.analyze(status_code, response_text)

            if result.status == ScanStatus.BLOCKED:
                logger.error(
                    f"[{self.engine_id}] 触发阻断 | 状态码: {status_code} | "
                    f"原因: {result.block_reason} | 响应体: {response_text[:1000]}"
                )

            if result.is_unknown_error_code:
                self.unknown_status_codes.add(status_code)
                # 【新增】统计未知状态码出现次数
                self.unknown_status_code_counts[status_code] = self.unknown_status_code_counts.get(status_code, 0) + 1
                
                # 【优化】只在首次发现该状态码时输出 WARNING 日志
                if status_code not in self.reported_unknown_codes:
                    self.reported_unknown_codes.add(status_code)
                    logger.warning(
                        f"[{self.engine_id}] 检测到未知的错误状态码: {status_code} | "
                        f"响应体: {response_text[:200]} | "
                        f"建议: 请检查该状态码是否需要配置到 block_status_codes 或 retry_status_codes"
                    )
                    if self.event_emitter:
                        try:
                            await self.event_emitter.unknown_status_code_found(status_code, response_text)
                        except Exception as e:
                            logger.error(f"[{self.engine_id}] 推送未知状态码事件失败: {e}", exc_info=True)
            
            # 【新增】记录敏感词判断依据
            if result.status == ScanStatus.BLOCKED and result.block_evidence:
                evidence = result.block_evidence
                if evidence.get("type") == "keyword":
                    keyword = evidence.get("value")
                    if keyword and keyword not in self.sensitive_word_evidence:
                        self.sensitive_word_evidence[keyword] = {
                            "type": "keyword",
                            "value": keyword,
                            "context": evidence.get("context", ""),
                            "first_found_at": datetime.now().isoformat()
                        }
                        logger.info(f"[{self.engine_id}] 记录敏感词判断依据: {keyword}")
                elif evidence.get("type") == "status_code":
                    status_code_value = evidence.get("value")
                    if status_code_value and f"status_code_{status_code_value}" not in self.sensitive_word_evidence:
                        self.sensitive_word_evidence[f"status_code_{status_code_value}"] = {
                            "type": "status_code",
                            "value": status_code_value,
                            "first_found_at": datetime.now().isoformat()
                        }
                        logger.info(f"[{self.engine_id}] 记录状态码判断依据: {status_code_value}")

            if result.status == ScanStatus.BLOCKED:
                self.blocked_count += 1
            elif result.status == ScanStatus.SAFE:
                self.safe_count += 1
            elif result.status == ScanStatus.ERROR and status_code not in self.unknown_status_codes:
                self.error_count += 1

            return result

        except (asyncio.TimeoutError, httpx.TimeoutException, httpx.ConnectError, 
                httpx.ReadTimeout, httpx.NetworkError, ConnectionError, OSError) as e:
            # 网络错误在重试耗尽后被抛出
            logger.error(f"[{self.engine_id}] 网络错误，重试已耗尽: {type(e).__name__}: {str(e)}")
            self.error_count += 1
            return ProbeResult(ScanStatus.ERROR, 0, f"Network Error: {type(e).__name__}")

        except Exception as e:
            logger.error(f"[{self.engine_id}] 请求异常: {type(e).__name__}: {str(e)}")
            self.error_count += 1
            return ProbeResult(ScanStatus.ERROR, 0, str(e))

    async def probe_batch(self, texts: List[str]) -> List[ProbeResult]:
        """
        批量探测文本片段

        Args:
            texts: 文本片段列表

        Returns:
            ProbeResult 对象列表
        """
        if not texts:
            return []

        logger.info(f"[{self.engine_id}] 开始批量探测 | 文本数: {len(texts)}")
        tasks = [self.probe(text) for text in texts]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"[{self.engine_id}] 批量探测异常: {str(result)}")
                processed_results.append(ProbeResult(ScanStatus.ERROR, 0, str(result)))
            else:
                processed_results.append(result)

        logger.info(
            f"[{self.engine_id}] 批量探测完成 | "
            f"总数: {len(texts)} | "
            f"安全: {sum(1 for r in processed_results if r.status == ScanStatus.SAFE)} | "
            f"阻止: {sum(1 for r in processed_results if r.status == ScanStatus.BLOCKED)} | "
            f"错误: {sum(1 for r in processed_results if r.status == ScanStatus.ERROR)}"
        )

        return processed_results

    def reset_masking(self):
        """
        重置动态掩码，清除所有已知的敏感词模式。
        
        【新增】同时重置 GlobalMaskManager。
        """
        self.mask_patterns = set()
        if self.mask_manager:
            self.mask_manager.reset()
        if self.response_analyzer:
            self.response_analyzer.mask_patterns = self.mask_patterns
        logger.info(f"[{self.engine_id}] 动态掩码已重置.")

    def reset_statistics(self):
        """重置引擎的统计数据，确保每次扫描的计数都是独立的。"""
        self.request_count = 0
        self.blocked_count = 0
        self.safe_count = 0
        self.error_count = 0
        # 【新增】重置未知状态码和敏感词统计
        self.unknown_status_codes.clear()
        self.unknown_status_code_counts.clear()
        self.sensitive_word_evidence.clear()
        self.reported_unknown_codes.clear()
        logger.info(f"[{self.engine_id}] 引擎统计数据已重置.")

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计数据"""
        return {
            "request_count": self.request_count,
            "blocked_count": self.blocked_count,
            "safe_count": self.safe_count,
            "error_count": self.error_count,
            # 【新增】未知状态码统计
            "unknown_status_codes": sorted(list(self.unknown_status_codes)),
            "unknown_status_code_counts": dict(self.unknown_status_code_counts),
            # 【新增】敏感词判断依据
            "sensitive_word_evidence": self.sensitive_word_evidence
        }
