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
        # 直接设置回调，不需要包装
        # unknown_status_code 事件已经由 emitter 正确处理
        await self.emitter.set_callback(callback)

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

        # 【修复】使用 Semaphore 实现真正的并发处理
        concurrency = self.engine.preset.concurrency if hasattr(self.engine, 'preset') else 10
        sem = asyncio.Semaphore(concurrency)
        
        async def process_segment(segment_text: str, start_pos: int, end_pos: int) -> List[tuple]:
            """
            并发处理单个段的 worker 函数 - 实现等长延迟掩码机制。
            
            流程：
            1. [Late Binding] 获取最新的等长掩码文本
            2. [Optimization] 检查是否全被掩码
            3. [Probe] 执行扫描
            4. [Result Restoration] 从原文本中还原真实敏感词
            
            - 【实时反馈】在函数末尾更新并发送实时进度。
            - 【结果隔离】只返回本段的发现结果，不修改全局列表。
            """
            local_findings = []
            status = ScanStatus.SAFE
            error_info = None
            segment_length = end_pos - start_pos

            try:
                async with sem:
                    if self.should_stop:
                        raise asyncio.CancelledError("Scan stopped by user.")

                    # 【Step 1】Late Binding: 获取最新的等长掩码文本
                    # 由于是等长替换，masked_segment 的长度 == segment_text 的长度
                    masked_segment = self.engine.mask_manager.apply_masks(segment_text)
                    
                    # 【Step 2】Optimization: 检查是否全被掩码
                    # 如果替换成了全 '*'，说明全是敏感词
                    if masked_segment.strip() and all(c == '*' or c.isspace() for c in masked_segment):
                        status = ScanStatus.MASKED
                        await self.emitter.log_message(
                            "info", 
                            f"段 [pos:{start_pos}-{end_pos}] 已被完全屏蔽，跳过"
                        )
                    else:
                        # 【Step 3】Probe: 执行扫描
                        # 注意：我们把 masked_segment 传给 probe
                        # 因为已知词被变成了 '*'，API 不会再拦截它们
                        # 如果 API 依然拦截，说明有【新】的敏感词
                        result = await self.engine.probe(masked_segment)
                        status = result.status
                        
                        if status == ScanStatus.BLOCKED:
                            reason = f" (原因: {result.block_reason})" if result.block_reason else ""
                            await self.emitter.log_message(
                                "info", 
                                f"段 [pos:{start_pos}-{end_pos}] 被拦截{reason}，启动深度扫描..."
                            )
                            # 【关键】使用原始文本进行精确扫描，而不是掩码后的文本
                            found_in_segment = await self.searcher.search(segment_text, start_pos)
                            
                            # 【Step 4】Result Restoration: 从原文本中还原真实敏感词
                            # searcher 返回的 findings 中的 text 可能是掩码后的内容
                            # 我们需要用原始 segment_text 还原出真实的敏感词文本
                            for finding in found_in_segment:
                                # 计算相对位置
                                rel_start = finding.start_pos - start_pos
                                rel_end = finding.end_pos - start_pos
                                
                                # 从【原文本】中提取真实内容
                                if 0 <= rel_start < len(segment_text) and 0 <= rel_end <= len(segment_text):
                                    real_word = segment_text[rel_start:rel_end]
                                    # 创建修正后的结果（使用原始坐标和真实文本）
                                    local_findings.append((finding.start_pos, finding.end_pos, real_word))
                                else:
                                    # 如果坐标超出范围，使用 finding 中的文本（降级处理）
                                    local_findings.append((finding.start_pos, finding.end_pos, finding.text))
                        
                        elif status == ScanStatus.SAFE:
                            logger.debug(f"[{self.session_id}] 段 [pos:{start_pos}-{end_pos}] 安全。")
            
            except asyncio.CancelledError as e:
                logger.warning(f"[{self.session_id}] 段 [pos:{start_pos}-{end_pos}] 被取消: {e}")
                error_info = str(e)
            except Exception as e:
                logger.error(f"[{self.session_id}] 段 [pos:{start_pos}-{end_pos}] 处理异常: {e}", exc_info=True)
                error_info = str(e)
                status = ScanStatus.ERROR

            # --- 【关键】实时进度更新 --- 
            self.total_scanned_pos += segment_length
            if status == ScanStatus.SAFE:
                self.uncleared_chars -= segment_length
            
            # 将本段发现的敏感词加入全局结果集
            if local_findings:
                for finding in local_findings:
                    self.results_set.add(finding)
                self.sensitive_count = len(self.results_set)
            
            # 构建分组结果并发送进度事件
            current_grouped_results = self._build_grouped_results()
            await self.emitter.progress_updated(
                scanned=self.total_scanned_pos,
                total=self.total_text_length,
                sensitive_count=self.sensitive_count,
                results=current_grouped_results
            )
            
            return local_findings # 只返回结果

        tasks = [process_segment(s, p_start, p_end) for s, p_start, p_end in segments]
        segment_results = await asyncio.gather(*tasks)

        # --- 检验流程开始 ---
        # 此时 self.results_set 里是并发扫描产生的、混合了高精度短词和低精度长句的脏数据
        
        logger.info(
            f"[{self.session_id}] [Golden Flow] 开始检验流程 | "
            f"脏数据候选数: {len(self.results_set)}"
        )
        
        # 步骤 1: 统计脏数据中的候选片段
        dirty_candidates = list(self.results_set)
        if dirty_candidates:
            logger.debug(
                f"[{self.session_id}] [Golden Flow] 脏数据样本 (前5个): "
                f"{[f'{text[:20]}...' for _, _, text in dirty_candidates[:5]]}"
            )

        # 步骤 2: 【验证】过滤掉所有 API 认为是 SAFE 的幻觉长句
        logger.info(f"[{self.session_id}] [Golden Flow] 阶段 1/3: 验证 - 开始验证 {len(dirty_candidates)} 个候选片段")
        validated_segments = await self._final_validation(dirty_candidates)
        logger.info(
            f"[{self.session_id}] [Golden Flow] 阶段 1/3: 验证 - 完成 | "
            f"候选数: {len(dirty_candidates)} → 验证通过数: {len(validated_segments)} | "
            f"过滤率: {(1 - len(validated_segments)/max(1, len(dirty_candidates)))*100:.1f}%"
        )

        # 步骤 3: 【精炼】处理包含关系，得到最终的核心关键词列表
        logger.info(f"[{self.session_id}] [Golden Flow] 阶段 2/3: 精炼 - 开始精炼 {len(validated_segments)} 个已验证片段")
        core_keywords = self._refine_and_deduplicate(validated_segments)
        logger.info(
            f"[{self.session_id}] [Golden Flow] 阶段 2/3: 精炼 - 完成 | "
            f"已验证片段数: {len(validated_segments)} → 核心关键词数: {len(core_keywords)}"
        )
        if core_keywords:
            logger.info(f"[{self.session_id}] [Golden Flow] 最终确认的核心敏感词: {sorted(core_keywords)}")

        # 步骤 4: 【最终清点】抛弃旧坐标，用核心关键词重新进行全局搜索
        logger.info(f"[{self.session_id}] [Golden Flow] 阶段 3/3: 清点 - 开始最终清点")
        final_results_set = self._final_enumeration(core_keywords, self.original_text)
        logger.info(
            f"[{self.session_id}] [Golden Flow] 阶段 3/3: 清点 - 完成 | "
            f"核心关键词数: {len(core_keywords)} → 最终结果数: {len(final_results_set)}"
        )

        # 步骤 5: 格式化并返回最终结果
        # 用最干净、最准确的结果覆盖 self.results_set
        logger.info(
            f"[{self.session_id}] [Golden Flow] 检验流程完成 | "
            f"脏数据: {len(dirty_candidates)} → 最终结果: {len(final_results_set)} | "
            f"总过滤率: {(1 - len(final_results_set)/max(1, len(dirty_candidates)))*100:.1f}%"
        )
        
        self.results_set = final_results_set
        self.sensitive_count = len(self.results_set)

        # 按绝对坐标排序，确保顺序一致性
        deduplicated_segments = [
            SensitiveSegment(text=content, start_pos=start, end_pos=end)
            for start, end, content in sorted(self.results_set, key=lambda x: (x[0], x[1]))
        ]

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

        # 【修复】在扫描完成时，强制发送 100% 的进度更新
        # 这确保前端的进度条总是能到达 100%，而不会卡在 91% 或其他中间值
        await self.emitter.progress_updated(
            scanned=self.total_text_length,
            total=self.total_text_length,
            sensitive_count=self.sensitive_count,
            results=self._build_grouped_results(),
            force=True  # 强制发送，跳过节流
        )

        stats = self.get_statistics()
        
        # 【修复】获取未知状态码统计和敏感词判断依据
        unknown_code_counts = getattr(self.engine, 'unknown_status_code_counts', {})
        sensitive_word_evidence = getattr(self.engine, 'sensitive_word_evidence', {})
        
        await self.emitter.scan_completed(
            total_sensitive_found=stats['sensitive_count'],
            total_requests=stats['request_count'],
            unknown_codes=list(self.engine.unknown_status_codes),
            results=grouped_results,  # 修正字段名
            duration_text=duration_str,
            duration_seconds=scan_duration,
            unknown_code_counts=unknown_code_counts,
            sensitive_word_evidence=sensitive_word_evidence
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

    async def _final_validation(self, candidate_segments: List[tuple]) -> List[SensitiveSegment]:
        """
        【验证阶段】使用 API 再次验证所有候选片段，过滤掉幻觉长句。
        
        ✅ 已优化：使用并发处理，而非串行 for 循环
        
        流程：
        1. 对每个候选片段调用 probe_func（并发执行）
        2. 只保留 API 认为是 BLOCKED 的片段
        3. 返回已验证的、真实的敏感片段列表
        
        Args:
            candidate_segments: 候选片段列表，每个元素为 (start_pos, end_pos, text)
            
        Returns:
            已验证的 SensitiveSegment 列表
        """
        if not candidate_segments:
            logger.info(f"[{self.session_id}] [Validation] 候选片段为空，跳过验证")
            return []
        
        logger.info(
            f"[{self.session_id}] [Validation] 开始验证 {len(candidate_segments)} 个候选片段（并发模式）..."
        )
        
        # 创建验证任务列表
        async def validate_single_segment(idx: int, start_pos: int, end_pos: int, text: str) -> Optional[SensitiveSegment]:
            """验证单个片段"""
            try:
                # 调用 probe 函数验证该片段是否真的被拦截
                # 【关键修复】传入 bypass_mask=True，跳过动态掩码，确保裸词被正确验证
                # 这样可以避免已发现的敏感词被掩码成 '*' 后被误判为 SAFE
                result = await self.engine.probe(text, bypass_mask=True)
                
                if result.status == ScanStatus.BLOCKED:
                    # 这是一个真实的敏感片段
                    logger.debug(
                        f"[{self.session_id}] [Validation] 片段 {idx+1}/{len(candidate_segments)} "
                        f"验证通过 | 位置: {start_pos}-{end_pos} | 内容: '{text[:30]}...'"
                    )
                    return SensitiveSegment(text=text, start_pos=start_pos, end_pos=end_pos)
                else:
                    # 这是一个幻觉长句，被 API 认为是安全的
                    logger.debug(
                        f"[{self.session_id}] [Validation] 片段 {idx+1}/{len(candidate_segments)} "
                        f"验证失败（幻觉） | 位置: {start_pos}-{end_pos} | 内容: '{text[:30]}...'"
                    )
                    return None
            except Exception as e:
                logger.error(
                    f"[{self.session_id}] [Validation] 片段 {idx+1}/{len(candidate_segments)} "
                    f"验证异常: {e}"
                )
                # 验证异常时，保守起见，保留该片段
                return SensitiveSegment(text=text, start_pos=start_pos, end_pos=end_pos)
        
        # 并发执行所有验证任务
        tasks = [
            validate_single_segment(idx, start_pos, end_pos, text)
            for idx, (start_pos, end_pos, text) in enumerate(candidate_segments)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        # 过滤掉 None 结果（验证失败的片段）
        validated_segments = [seg for seg in results if seg is not None]
        
        logger.info(
            f"[{self.session_id}] [Validation] 验证完成（并发） | "
            f"候选数: {len(candidate_segments)} | 通过数: {len(validated_segments)} | "
            f"过滤率: {(1 - len(validated_segments)/len(candidate_segments))*100:.1f}%"
        )
        
        return validated_segments

    def _refine_and_deduplicate(self, validated_segments: List[SensitiveSegment]) -> Set[str]:
        """
        【精炼阶段】对已通过验证的片段进行精炼，处理包含关系，提取最终的核心关键词列表。
        
        流程：
        1. 从所有片段中提取关键词
        2. 【关键】按长度排序，短的优先
        3. 【关键】检查文本包含关系，优先保留短词，丢弃长词
        4. 返回去重后的核心关键词集合
        
        Args:
            validated_segments: 已验证的 SensitiveSegment 列表
            
        Returns:
            最终的核心关键词集合（已去重，只保留最短的子序列）
        """
        if not validated_segments:
            logger.info(f"[{self.session_id}] [Refinement] 已验证片段为空，返回空关键词集合")
            return set()
        
        logger.info(
            f"[{self.session_id}] [Refinement] 开始精炼 {len(validated_segments)} 个已验证片段..."
        )
        
        # 步骤 1：从所有片段中提取关键词
        all_keywords = {seg.text for seg in validated_segments}
        
        # 步骤 2：【关键修复】按长度排序，短的优先
        # 这让短词有机会"吃掉"包含它的长词
        sorted_keywords = sorted(all_keywords, key=lambda k: (len(k), k))
        
        # 步骤 3：【关键修复】检查文本包含关系，优先保留短词，丢弃长词
        filtered_keywords = []
        
        for current_keyword in sorted_keywords:
            is_contained = False
            
            # 检查是否被已保留的更短关键词包含
            for retained_keyword in filtered_keywords:
                # 如果 current 被 retained 包含，则 current 是冗余的
                if retained_keyword in current_keyword:
                    is_contained = True
                    logger.debug(
                        f"[{self.session_id}] [Refinement] 关键词被包含（丢弃） | "
                        f"被包含: '{current_keyword[:30]}...' | 包含者: '{retained_keyword}'"
                    )
                    break
            
            if not is_contained:
                filtered_keywords.append(current_keyword)
                logger.debug(
                    f"[{self.session_id}] [Refinement] 关键词保留 | "
                    f"词汇: '{current_keyword}' | 长度: {len(current_keyword)}"
                )
        
        core_keywords = set(filtered_keywords)
        
        logger.info(
            f"[{self.session_id}] [Refinement] 精炼完成 | "
            f"输入片段数: {len(validated_segments)} | 输出关键词数: {len(core_keywords)} | "
            f"去重率: {(1 - len(core_keywords)/len(all_keywords))*100:.1f}%"
        )
        
        return core_keywords

    def _final_enumeration(self, core_keywords: Set[str], original_text: str) -> Set[tuple]:
        """
        【最终清点阶段】用已去重的关键词列表，在原始文本上重新进行全局搜索，
        得到最准确的位置和数量。
        
        流程：
        1. 遍历每个核心关键词（已在精炼阶段去重）
        2. 使用 re.finditer 查找所有匹配项
        3. 记录精确的位置和内容
        
        Args:
            core_keywords: 最终确认的核心关键词集合（已去重）
            original_text: 原始文本
            
        Returns:
            最终结果集合，每个元素为 (start_pos, end_pos, keyword)
        """
        if not core_keywords:
            logger.info(f"[{self.session_id}] [Enumeration] 核心关键词为空，返回空结果集")
            return set()
        
        logger.info(
            f"[{self.session_id}] [Enumeration] 开始最终清点，关键词数: {len(core_keywords)}"
        )
        
        final_results_set = set()
        
        for keyword in sorted(core_keywords):  # 按字母顺序排序以确保一致性
            try:
                # 使用 re.finditer 查找所有匹配项
                pattern = re.escape(keyword)
                matches = list(re.finditer(pattern, original_text))
                
                for match in matches:
                    start, end = match.span()
                    final_results_set.add((start, end, keyword))
                
                logger.debug(
                    f"[{self.session_id}] [Enumeration] 关键词清点完成 | "
                    f"词汇: '{keyword}' | 出现次数: {len(matches)}"
                )
            except Exception as e:
                logger.error(
                    f"[{self.session_id}] [Enumeration] 关键词清点异常 | "
                    f"词汇: '{keyword}' | 错误: {e}"
                )
        
        logger.info(
            f"[{self.session_id}] [Enumeration] 最终清点完成 | "
            f"核心关键词数: {len(core_keywords)} | 最终结果数: {len(final_results_set)}"
        )
        
        return final_results_set

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
