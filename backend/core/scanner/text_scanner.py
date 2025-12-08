"""
文本扫描器 (TextScanner) - 扫描流程主协调器

本模块定义了 `TextScanner` 类，它是整个扫描流程的核心协调者。
它负责将长文本分割成块，对每个块进行初步探测，并对包含敏感内容的块启动深度扫描。

主要职责:
- **流程编排**: 依次调用 `TextSegmenter` (文本分段) 和 `BinarySearcher` (二分查找/精确定位)。
- **动态配置**: 在每次扫描开始时，从 `ConfigManager` 加载最新的扫描参数。
- **动态全局屏蔽 (Dynamic Global Masking)**: 实现“发现一次，全局屏蔽”策略。一旦一个敏感词被精确定位，
  它会立即在全文中被搜索并记录，同时加入动态屏蔽列表，以避免对同一敏感词的重复 API 请求，
  从而显著提升效率和降低成本。
- **状态与事件管理**: 通过 `ScanEventEmitter` 实时向前端推送扫描进度、日志和结果。
"""
import asyncio
import logging
import re
import time
from typing import List, Optional, Callable, Dict, Any, Set

from ..engine import ProbeEngine, ScanStatus
from ..config_manager import get_config_manager
from ..constants import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MIN_GRANULARITY,
    DEFAULT_OVERLAP_SIZE,
    DEFAULT_ALGORITHM_CONFIG
)
from .text_segmenter import TextSegmenter
from .binary_searcher import BinarySearcher, SensitiveSegment
from .event_emitter import ScanEventEmitter
from ..event_bus import get_event_bus, EventTypes

logger = logging.getLogger(__name__)

class TextScanner:
    """
    封装了完整扫描流程的核心类。

    本类通过组合 `TextSegmenter`、`BinarySearcher` 和 `ProbeEngine`，
    实现了从文本分段、初步探测到深度扫描的完整自动化流程。
    """

    def __init__(self, engine: ProbeEngine, session_id: str):
        """
        初始化文本扫描器

        Args:
            engine: 探针引擎实例
            session_id: 当前会话的 ID，用于日志追踪
        """
        self.engine = engine
        self.session_id = session_id
        self.config_manager = get_config_manager()
        self.emitter = ScanEventEmitter()
        self.event_bus = get_event_bus()

        # 订阅关键词发现事件
        self.event_bus.subscribe(EventTypes.KEYWORD_FOUND, self.handle_new_keyword_event)

        # 将在 scan 方法中根据动态配置进行初始化
        self.segmenter: Optional[TextSegmenter] = None
        self.searcher: Optional[BinarySearcher] = None

        # 统计信息
        self.total_text_length = 0
        self.total_scanned_pos = 0
        self.sensitive_count = 0
        
        self.uncleared_chars = 0
        self.known_sensitive_words: Set[str] = set()
        self.full_text: str = ""
        self.should_stop = False
        
        # 扫描时间记录
        self.scan_start_time: Optional[float] = None
        self.scan_end_time: Optional[float] = None

        logger.info(f"[{self.session_id}] TextScanner initialized.")

    async def set_log_callback(self, callback: Callable):
        """设置用于发送事件的回调函数"""
        async def wrapped_callback(event: Dict[str, Any]):
            if event.get("event") == "unknown_status_code":
                status_code = event.get("status_code")
                response_snippet = event.get("response_snippet", "")
                await self.emitter.handle_unknown_status_code(status_code, response_snippet)
                await callback(event)
            else:
                await callback(event)
        
        await self.emitter.set_callback(wrapped_callback)

    async def handle_new_keyword_event(self, event: Dict[str, Any]):
        """事件处理器：处理新发现的敏感词事件"""
        keyword = event.get('keyword')
        session_id = event.get('session_id')

        # 确保只处理当前会话的事件
        if session_id != self.session_id:
            return

        await self.handle_new_keyword(keyword)

    async def handle_new_keyword(self, keyword: str) -> None:
        """
        处理一个新发现的敏感词，这是“动态全局屏蔽”策略的核心实现。

        当一个敏感词被 `PrecisionScanner` 精确定位后，此方法会立即被调用。
        它执行以下操作：
        1. 将该词加入 `known_sensitive_words` 集合，用于未来的屏蔽。
        2. 在完整的原始文本 (`full_text`) 中搜索该词的所有出现位置。
        3. 将所有找到的位置记录到最终结果中，实现“一次发现，全局收割”。
        4. 更新底层的 `ProbeEngine`，将该词加入其屏蔽列表，后续的 API 请求将自动“欺骗” API，
           从而避免对已知敏感词的重复探测。
        """
        if not keyword or keyword in self.known_sensitive_words:
            logger.debug(f"[{self.session_id}] [Masking] 敏感词已知或为空，跳过: '{keyword}'")
            return
        
        self.known_sensitive_words.add(keyword)
        logger.info(
            f"[{self.session_id}] [Masking] 新敏感词已锁定 | 词汇: '{keyword}' | "
            f"已知词数: {len(self.known_sensitive_words)}"
        )
        
        if not self.full_text:
            logger.warning(f"[{self.session_id}] [Masking] 完整文本未设置，无法执行全局搜索")
            return
        
        try:
            pattern = re.escape(keyword)
            matches = list(re.finditer(pattern, self.full_text))
        except Exception as e:
            logger.error(f"[{self.session_id}] [Masking] 正则搜索失败: {e}")
            return
        
        positions_str = ', '.join([f'{m.start()}-{m.end()}' for m in matches[:10]])
        if len(matches) > 10:
            positions_str += f', ... (共{len(matches)}个)'
        
        logger.info(
            f"[{self.session_id}] [Masking] 全局搜索完成 | 词汇: '{keyword}' | "
            f"出现次数: {len(matches)} | 位置: {positions_str}"
        )
        
        if hasattr(self, 'results_set') and self.results_set is not None:
            for match in matches:
                start_pos = match.start()
                end_pos = match.end()
                result_tuple = (start_pos, end_pos, keyword)
                self.results_set.add(result_tuple)
            
            all_positions = [f'{m.start()}-{m.end()}' for m in matches]
            logger.debug(
                f"[{self.session_id}] [Masking] 所有位置已记录 | 词汇: '{keyword}' | "
                f"位置列表: {all_positions}"
            )
            
            self.sensitive_count = len(self.results_set)

            # --- 实时结果更新 ---
            # 构建当前的分组结果并随进度事件一起发送
            current_grouped_results = self._build_grouped_results()
            await self.emitter.progress_updated(
                scanned=self.total_scanned_pos,
                total=self.total_text_length,
                sensitive_count=self.sensitive_count,
                results=current_grouped_results
            )
            # ---------------------
            
            keyword_total_chars = len(keyword) * len(matches)
            self.uncleared_chars = max(0, self.uncleared_chars - keyword_total_chars)
            logger.info(
                f"[{self.session_id}] [Progress] 未清除字符更新 | "
                f"减少: {keyword_total_chars} | 剩余: {self.uncleared_chars}"
            )
        
        self.engine.set_mask_patterns(self.known_sensitive_words)
        
        await self.emitter.log_message(
            "info",
            f"[Masking] 动态掩码已启用 | 词汇: '{keyword}' | "
            f"全局出现次数: {len(matches)} | 已知敏感词: {len(self.known_sensitive_words)}"
        )

    async def _load_dynamic_config(self):
        """从 ConfigManager 加载并应用最新配置"""
        try:
            settings = await self.config_manager.load()
            chunk_size = settings.get("chunk_size", DEFAULT_CHUNK_SIZE)
            min_granularity = settings.get("min_granularity", DEFAULT_MIN_GRANULARITY)
            overlap_size = settings.get("overlap_size", DEFAULT_OVERLAP_SIZE)
            algorithm_mode = settings.get("algorithm_mode", "hybrid")
            
            algorithm_config = settings.get("algorithm", {})
            if not algorithm_config:
                algorithm_config = DEFAULT_ALGORITHM_CONFIG.copy()
            # 将顶层的 algorithm_switch_threshold 合并到 algorithm 配置，支持前端覆盖
            if "algorithm_switch_threshold" in settings:
                try:
                    th = int(settings.get("algorithm_switch_threshold"))
                    algorithm_config["algorithm_switch_threshold"] = th
                except Exception:
                    pass

            logger.info(
                f"[{self.session_id}] 动态加载扫描配置 | "
                f"chunk_size={chunk_size}, min_granularity={min_granularity}, overlap_size={overlap_size}, "
                f"algorithm_mode={algorithm_mode}"
            )

            try:
                latest_block_status = settings.get("block_status_codes", []) or []
                latest_retry_status = settings.get("retry_status_codes", []) or []
                latest_block_keywords = settings.get("block_keywords", []) or []

                latest_block_status = [int(x) for x in latest_block_status if isinstance(x, (int, str)) and str(x).isdigit()]
                latest_retry_status = [int(x) for x in latest_retry_status if isinstance(x, (int, str)) and str(x).isdigit()]
                latest_block_keywords = [str(x) for x in latest_block_keywords if isinstance(x, (str, int))]

                self.engine.preset.block_status_codes = latest_block_status
                self.engine.preset.retry_status_codes = latest_retry_status
                self.engine.preset.block_keywords = latest_block_keywords

                if hasattr(self.engine, "response_analyzer") and self.engine.response_analyzer:
                    self.engine.response_analyzer.preset.block_status_codes = latest_block_status
                    self.engine.response_analyzer.preset.retry_status_codes = latest_retry_status
                    self.engine.response_analyzer.preset.block_keywords = latest_block_keywords

                logger.info(
                    f"[{self.session_id}] 已同步最新规则到引擎 | "
                    f"block_status_codes={latest_block_status} | retry_status_codes={latest_retry_status}"
                )
            except Exception as sync_err:
                logger.error(f"[{self.session_id}] 同步规则到引擎失败: {sync_err}")

            self.segmenter = TextSegmenter(segment_size=chunk_size, overlap_size=overlap_size)
            self.searcher = BinarySearcher(
                engine=self.engine,
                emitter=self.emitter,
                min_granularity=min_granularity,
                overlap_size=overlap_size,
                algorithm_config=algorithm_config,
                algorithm_mode=algorithm_mode,
                session_id=self.session_id,
                text_scanner_instance=self
            )
            return chunk_size
        except Exception as e:
            logger.error(f"[{self.session_id}] 从 ConfigManager 加载配置失败: {e}", exc_info=True)
            default_algorithm_config = DEFAULT_ALGORITHM_CONFIG.copy()
            self.segmenter = TextSegmenter(segment_size=20000, overlap_size=15)
            self.searcher = BinarySearcher(
                engine=self.engine,
                emitter=self.emitter,
                min_granularity=1,
                overlap_size=15,
                algorithm_config=default_algorithm_config,
                session_id=self.session_id,
                text_scanner_instance=self
            )
            return 20000

    async def scan(self, text: str) -> List[SensitiveSegment]:
        """
        扫描文本并返回敏感片段列表
        """
        if not text:
            return []

        # 记录扫描开始时间
        self.scan_start_time = time.time()

        segment_size = await self._load_dynamic_config()

        self.total_text_length = len(text)
        self.total_scanned_pos = 0
        self.sensitive_count = 0
        self.uncleared_chars = len(text)
        self.full_text = text
        self.known_sensitive_words = set()

        # 【修复】重置引擎的统计数据，确保“总请求数”只计算本次扫描
        if hasattr(self.engine, 'reset_statistics'):
            self.engine.reset_statistics()

        # 【修复】重置动态掩码，防止跨扫描污染
        if hasattr(self.engine, 'reset_masking'):
            self.engine.reset_masking()
        # 【修复】重置动态掩码，防止跨扫描污染
        if hasattr(self.engine, 'reset_masking'):
            self.engine.reset_masking()
        
        try:
            if hasattr(self.engine, "unknown_status_codes"):
                self.engine.unknown_status_codes = set()
            if hasattr(self.engine, "reported_unknown_codes"):
                self.engine.reported_unknown_codes = set()
            logger.info(f"[{self.session_id}] 已重置未知状态码跟踪集合（per-scan）")
        except Exception as reset_err:
            logger.error(f"[{self.session_id}] 重置未知状态码集合失败: {reset_err}")
        
        self.results_set: set = set()
        self.original_text = text
        self.reported_unknown_codes = set()
        self.processed_signatures: set = set()

        try:
            full_config = await self.config_manager.load()
            config_for_log = {}
            exclude_keys = {'api_key', 'api_url', 'api_model'}
            for key, value in full_config.items():
                if key not in exclude_keys and value is not None:
                    if isinstance(value, list):
                        config_for_log[key] = f"{value[:3]}...({len(value)} items)" if len(value) > 5 else value
                    elif isinstance(value, bool):
                        config_for_log[key] = "yes" if value else "no"
                    else:
                        config_for_log[key] = value
        except Exception as e:
            logger.warning(f"[{self.session_id}] 加载完整配置失败: {e}")
            config_for_log = {
                "chunk_size": self.segmenter.segment_size if self.segmenter else segment_size,
                "min_granularity": self.searcher.min_granularity if self.searcher else 30,
                "overlap_size": self.searcher.overlap_size if self.searcher else 10,
            }
        
        await self.emitter.scan_started(self.total_text_length, segment_size, config_for_log)

        # 【修复】强制事件循环切换，确保 'scan_start' 事件能被及时发送到前端
        await asyncio.sleep(0)

        segments = self.segmenter.split(text)
        logger.info(f"[{self.session_id}] 文本已分割成 {len(segments)} 个段进行扫描。")

        for segment_text, start_pos, end_pos in segments:
            if self.should_stop:
                logger.warning(f"[{self.session_id}] 扫描被用户中止")
                await self.emitter.log_message("warning", "扫描已被用户中止")
                break
            
            result = await self.engine.probe(segment_text)

            if result.status == ScanStatus.MASKED:
                await self.emitter.log_message("info", f"段 [pos:{start_pos}-{end_pos}] 已跳过 (包含已知敏感词)")
            elif result.status == ScanStatus.BLOCKED:
                reason = f" (原因: {result.block_reason})" if result.block_reason else ""
                await self.emitter.log_message("info", f"段 [pos:{start_pos}-{end_pos}] 被拦截{reason}，调用二分算法进行查找...")
                found_in_segment = await self.searcher.search(segment_text, start_pos)
                
                for segment in found_in_segment:
                    result_tuple = (segment.start_pos, segment.end_pos, segment.text)
                    self.results_set.add(result_tuple)
                
                self.sensitive_count = len(self.results_set)
            else:
                logger.debug(f"[{self.session_id}] 段 [pos:{start_pos}-{end_pos}] 安全。")
                segment_length = end_pos - start_pos
                self.uncleared_chars = max(0, self.uncleared_chars - segment_length)
                logger.debug(
                    f"[{self.session_id}] [Progress] 干净块处理 | "
                    f"块长: {segment_length} | 未清除字符: {self.uncleared_chars}"
                )

            await self._check_and_report_unknown_codes()

            self.total_scanned_pos = end_pos
            logger.debug(
                f"[{self.session_id}] [Progress] 发送进度更新 | "
                f"已扫描: {end_pos} | 总数: {self.total_text_length} | "
                f"未清除: {self.uncleared_chars} | 敏感词: {self.sensitive_count}"
            )
            # 构建当前的分组结果并随进度事件一起发送，确保前端实时更新
            current_grouped_results = self._build_grouped_results()
            await self.emitter.progress_updated(
                scanned=end_pos,
                total=self.total_text_length,
                sensitive_count=self.sensitive_count,
                results=current_grouped_results
            )

        deduplicated_segments = [
            SensitiveSegment(text=content, start_pos=start, end_pos=end)
            for start, end, content in sorted(self.results_set, key=lambda x: x[0])
        ]
        self.sensitive_count = len(deduplicated_segments)

        grouped_results = self._build_grouped_results()
        logger.info(
            f"[{self.session_id}] 构建最终分组结果 | "
            f"关键词数: {len(grouped_results)} | "
            f"总片段数: {self.sensitive_count}"
        )

        # 记录扫描结束时间并计算总耗时
        self.scan_end_time = time.time()
        scan_duration = self.scan_end_time - self.scan_start_time
        duration_str = self._format_duration(scan_duration)

        stats = self.get_statistics()
        await self.emitter.scan_completed(
            total_sensitive_found=stats['sensitive_count'],
            total_requests=stats['request_count'],
            unknown_codes=list(self.engine.unknown_status_codes),
            results=grouped_results,
            duration_text=duration_str,
            duration_seconds=scan_duration
        )

        logger.info(
            f"[{self.session_id}] 扫描完成 | "
            f"发现: {self.sensitive_count} | 总请求: {self.engine.request_count} | "
            f"分组关键词: {len(grouped_results)} | 总耗时: {duration_str}"
        )

        return deduplicated_segments

    def _format_duration(self, seconds: float) -> str:
        """
        将秒数格式化为可读的时间字符串
        
        Args:
            seconds: 秒数
            
        Returns:
            格式化后的时间字符串，例如 "2m 57s" 或 "3.45s"
        """
        if seconds < 60:
            return f"{seconds:.2f}s"
        else:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}m {secs:.0f}s"

    async def _check_and_report_unknown_codes(self):
        """检查并报告新的未知状态码（仅当首次发现时）"""
        new_codes = self.engine.unknown_status_codes - self.reported_unknown_codes
        if new_codes:
            for code in new_codes:
                await self.emitter.unknown_status_code_found(code)
            self.reported_unknown_codes.update(new_codes)

    def _build_grouped_results(self) -> Dict[str, list]:
        """
        将扫描结果转换为分组的字典对象
        """
        grouped_results = {}
        
        if hasattr(self, 'results_set') and self.results_set:
            for start_pos, end_pos, keyword in sorted(self.results_set, key=lambda x: (x[2], x[0])):
                if keyword not in grouped_results:
                    grouped_results[keyword] = []
                grouped_results[keyword].append({
                    "start": start_pos,
                    "end": end_pos
                })
        
        return grouped_results

    def get_statistics(self) -> Dict[str, Any]:
        """获取本次扫描的统计信息"""
        engine_stats = self.engine.get_statistics()
        return {
            "total_text_length": self.total_text_length,
            "total_scanned": self.total_scanned_pos,
            "sensitive_count": self.sensitive_count,
            "request_count": engine_stats.get("request_count", 0),
            "blocked_count": engine_stats.get("blocked_count", 0),
            "safe_count": engine_stats.get("safe_count", 0),
            "error_count": engine_stats.get("error_count", 0),
        }
