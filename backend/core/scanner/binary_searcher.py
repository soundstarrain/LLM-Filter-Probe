"""
二分查找器 (Binary Searcher)

职责：
- 实现核心的二分查找算法以精确定位敏感片段
- 管理递归深度和熔断机制
- 与 ProbeEngine 交互以探测文本
- 与 ScanEventEmitter 交互以实时报告结果
- 支持混合算法：二分 + 双向挤压
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

from ..engine import ProbeEngine, ScanStatus
from .event_emitter import ScanEventEmitter
from .precision_scanner import PrecisionScanner, SensitiveSegment as PrecisionScannerSegment
from ..constants import MICRO_SCAN_THRESHOLD, DEFAULT_ALGORITHM_SWITCH_THRESHOLD
from ..event_bus import get_event_bus, EventTypes

if TYPE_CHECKING:
    from .text_scanner import TextScanner

logger = logging.getLogger(__name__)

@dataclass
class SensitiveSegment:
    """用于内部表示敏感片段的数据类"""
    text: str
    start_pos: int
    end_pos: int

class BinarySearcher:
    """使用二分查找算法定位敏感词"""

    def __init__(
        self, 
        engine: ProbeEngine, 
        emitter: ScanEventEmitter, 
        min_granularity: int,
        overlap_size: int,
        algorithm_config: Optional[dict] = None,
        algorithm_mode: str = "hybrid",
        session_id: str = "",
        text_scanner_instance: Optional['TextScanner'] = None
    ):
        """
        初始化二分查找器

        Args:
            engine: 探针引擎，用于探测文本
            emitter: 事件发射器，用于发送实时反馈
            min_granularity: 最小查找粒度（字符数）
            overlap_size: 递归切分时的重叠大小
            should_stop_flag: 停止标志的引用（可以是对象的属性）
            algorithm_config: 算法配置字典
            algorithm_mode: 算法模式（hybrid/binary，默认 hybrid）
            session_id: 会话 ID（用于日志）
            text_scanner_instance: TextScanner 实例的引用
        """
        self.engine = engine
        self.emitter = emitter
        self.min_granularity = min_granularity
        self.overlap_size = overlap_size
        self.algorithm_mode = algorithm_mode
        self.session_id = session_id or "default"
        self.text_scanner = text_scanner_instance  # 新增
        self.found_segments: List[SensitiveSegment] = []
        self._current_block_reason: Optional[str] = None
        self.processed_signatures: set = set()  # 去重集合
        self.event_bus = get_event_bus()
        
        # 初始化精确定位扫描器（改进版）
        self.precision_scanner = PrecisionScanner(session_id=self.session_id)
        
        # 加载算法配置
        self.algorithm_config = algorithm_config or {}
        self.enable_triple_probe = self.algorithm_config.get("enable_triple_probe", True)
        self.max_recursion_depth = self.algorithm_config.get("max_recursion_depth", 30)
        self.enable_deduplication = self.algorithm_config.get("enable_deduplication", True)
        self.dedup_overlap_threshold = self.algorithm_config.get("dedup_overlap_threshold", 0.5)
        self.dedup_adjacent_distance = self.algorithm_config.get("dedup_adjacent_distance", 30)
        self.enable_middle_chunk_probe = self.algorithm_config.get("enable_middle_chunk_probe", True)
        self.middle_chunk_overlap_factor = self.algorithm_config.get("middle_chunk_overlap_factor", 1.0)
        
        # 从算法配置中获取切换阈值
        self.algorithm_switch_threshold = self.algorithm_config.get(
            "algorithm_switch_threshold", 
            DEFAULT_ALGORITHM_SWITCH_THRESHOLD
        )
        
        # 计算效率安全因子（加法缓冲区模型）
        # 推荐公式：threshold = (overlap_size × 2) + 10
        recommended_threshold = self.overlap_size * 2 + 10
        if self.algorithm_switch_threshold >= recommended_threshold:
            ratio_status = "✓ 高效"
        elif self.algorithm_switch_threshold > self.overlap_size * 2:
            ratio_status = "⚠️ 低效"
        else:
            ratio_status = "🔴 危险（死循环）"
        
        logger.info(
            f"[{self.session_id}] [BinarySearcher] 已初始化 | "
            f"算法模式={self.algorithm_mode} | "
            f"算法切换阈值={self.algorithm_switch_threshold} | "
            f"重叠大小={self.overlap_size} | "
            f"推荐值={recommended_threshold} | "
            f"状态={ratio_status} | "
            f"min_granularity={self.min_granularity}"
        )

    async def search(self, text: str, base_pos: int = 0) -> List[SensitiveSegment]:
        """
        对给定的文本块执行二分查找

        Args:
            text: 待查找的文本块
            base_pos: 该文本块在原始全文中的起始位置

        Returns:
            一个包含所有已定位敏感片段的列表
        """
        self.found_segments = []
        self.processed_signatures = set()  # 重置去重集合
        await self._recursive_search(text, base_pos, depth=0)
        return self.found_segments

    async def _probe_text(self, text: str) -> tuple[bool, Optional[str]]:
        """
        探测文本是否被拦截
        
        Returns:
            (是否被拦截, 阻断原因)
        """
        result = await self.engine.probe(text)
        block_reason = getattr(result, 'block_reason', None) if result.status == ScanStatus.BLOCKED else None
        return result.status == ScanStatus.BLOCKED, block_reason

    async def _recursive_search(self, text: str, base_pos: int, depth: int) -> None:
        """
        递归地执行二分查找（支持混合算法）
        """
        if self.text_scanner and self.text_scanner.should_stop:
            logger.warning(f"[{self.session_id}] [Recursion] 二分查找被用户中止 (深度: {depth})")
            return
        
        if depth > self.max_recursion_depth:
            logger.error(f"[{self.session_id}] [Panic] 递归深度超限 ({depth} > {self.max_recursion_depth}). 中止此段的搜索.")
            return

        if not text:
            return
        
        if self.min_granularity <= 0:
            logger.warning(f"[{self.session_id}] [Invalid Config] min_granularity must be positive. Using 1.")
            self.min_granularity = 1

        text_len = len(text)
        logger.debug(f"[{self.session_id}] [Recursion] Depth: {depth} | Length: {text_len} | Index: {base_pos} | Probing...")

        is_sensitive, block_reason = await self._probe_text(text)

        if not is_sensitive:
            logger.debug(f"[{self.session_id}] [Recursion] Depth: {depth} | Length: {text_len} | Index: {base_pos} | Status: SAFE (Pruned)")
            # 如果此分支是安全的，更新进度并发送事件
            if self.text_scanner:
                self.text_scanner.uncleared_chars = max(0, self.text_scanner.uncleared_chars - text_len)
                # 使用 TextScanner 的全局进度来发送更新
                await self.emitter.progress_updated(
                    scanned=self.text_scanner.total_scanned_pos, # 使用主扫描器的进度
                    total=self.text_scanner.total_text_length,
                    sensitive_count=self.text_scanner.sensitive_count
                )
            return
        
        self._current_block_reason = block_reason

        if self.algorithm_mode == "hybrid" and text_len <= self.algorithm_switch_threshold:
            # [效率安全因子检查]
            # 物理模型：Threshold = (2 × Overlap) + Buffer
            # 推荐值：Buffer = 10，即 Threshold = (2 × Overlap) + 10
            # 防护：Threshold 必须 > 2 × Overlap（防止死循环）
            # 当前配置：Threshold={self.algorithm_switch_threshold}, Overlap={self.overlap_size}, 推荐={recommended_threshold}
            logger.info(
                f"[{self.session_id}] [Macro→Micro] 触发智能交接 | "
                f"深度:{depth} | 长度:{text_len} | 阈值:{self.algorithm_switch_threshold} | "
                f"重叠:{self.overlap_size} | 比率:{self.algorithm_switch_threshold / self.overlap_size:.2f}x | "
                f"[Precision] 开始精细扫描..."
            )
            
            await self.emitter.log_message(
                "info",
                f"二分查找完成，进入精细扫描阶段 | 当前片段长度: {text_len} 字符 | 使用双向挤压算法定位敏感词"
            )
            
            async def probe_wrapper(text_segment: str) -> tuple:
                result = await self.engine.probe(text_segment)
                is_blocked = result.status == ScanStatus.BLOCKED
                block_reason = getattr(result, 'block_reason', None)
                return is_blocked, block_reason
            
            try:
                precision_results = await self.precision_scanner.scan_precision(
                    text, base_pos, probe_wrapper
                )
                
                for segment in precision_results:
                    self.found_segments.append(SensitiveSegment(
                        text=segment.text,
                        start_pos=segment.start_pos,
                        end_pos=segment.end_pos
                    ))
                    
                    # 发布 KEYWORD_FOUND 事件
                    await self.event_bus.emit(EventTypes.KEYWORD_FOUND, {
                        'keyword': segment.text,
                        'session_id': self.session_id
                    })

                    await self.emitter.log_message(
                        "success",
                        f"[Precision] 敏感词定位完成 | 词汇:'{segment.text}' | "
                        f"长度:{len(segment.text)} | 位置:{segment.start_pos}-{segment.end_pos}"
                    )
                
                logger.info(
                    f"[{self.session_id}] [Precision] 精细扫描完成 | "
                    f"提取敏感词数:{len(precision_results)}"
                )
                return
            except Exception as e:
                logger.error(
                    f"[{self.session_id}] [Precision] 精细扫描异常: {str(e)}",
                    exc_info=True
                )
                segment = SensitiveSegment(text=text, start_pos=base_pos, end_pos=base_pos + text_len)
                self.found_segments.append(segment)
                return

        if text_len <= self.min_granularity:
            segment = SensitiveSegment(text=text, start_pos=base_pos, end_pos=base_pos + text_len)
            self.found_segments.append(segment)
            
            logger.info(f"[{self.session_id}] 敏感片段已锁定 | 长度: {text_len} | 位置: {base_pos}-{base_pos + text_len}")

            # 发布 KEYWORD_FOUND 事件
            await self.event_bus.emit(EventTypes.KEYWORD_FOUND, {
                'keyword': text,
                'session_id': self.session_id
            })

            if depth > 0:
                await self.emitter.log_message(
                    "success",
                    f"[Macro] 敏感词定位完成 | 深度:{depth} | 长度:{text_len} | 位置:{base_pos}-{base_pos + text_len}"
                )
            return

        block_info = f" | 阻断原因:{self._current_block_reason}" if self._current_block_reason else ""
        await self.emitter.log_message(
            "warning",
            f"触发二分查找 | 深度:{depth + 1} | 当前片段长度:{text_len}{block_info} (正在定位...)"
        )

        mid = text_len // 2
        min_required_overlap = min(self.min_granularity, text_len // 4)
        current_overlap = max(self.overlap_size, min_required_overlap)
        max_safe_overlap = (text_len - 1) // 2
        current_overlap = min(current_overlap, max_safe_overlap)
        
        if current_overlap < 1 and text_len > 1:
            current_overlap = 1

        left_start = 0
        left_end = min(mid + current_overlap, text_len)
        right_start = max(0, mid - current_overlap)
        right_end = text_len

        left_half_text = text[left_start:left_end]
        right_half_text = text[right_start:right_end]

        left_len = len(left_half_text)
        right_len = len(right_half_text)
        
        if left_len >= text_len or right_len >= text_len:
            logger.warning(f"[Deadlock Prevention] Invalid split at depth {depth}. Treating as leaf.")
            segment = SensitiveSegment(text=text, start_pos=base_pos, end_pos=base_pos + text_len)
            self.found_segments.append(segment)
            await self.emitter.log_message("error", f"⚠️ 无效切分，强制作为叶子节点处理 | 深度:{depth}")
            return

        if left_len < self.min_granularity // 2 and right_len < self.min_granularity // 2:
            logger.debug(f"[Early Termination] Both halves too small. Treating as leaf.")
            segment = SensitiveSegment(text=text, start_pos=base_pos, end_pos=base_pos + text_len)
            self.found_segments.append(segment)
            return

        (left_is_sensitive, left_reason), (right_is_sensitive, right_reason) = await asyncio.gather(
            self._probe_text(left_half_text),
            self._probe_text(right_half_text)
        )

        if left_is_sensitive:
            self._current_block_reason = left_reason
            await self._recursive_search(left_half_text, base_pos + left_start, depth + 1)

        if right_is_sensitive:
            self._current_block_reason = right_reason
            await self._recursive_search(right_half_text, base_pos + right_start, depth + 1)

        if self.enable_triple_probe and not left_is_sensitive and not right_is_sensitive:
            mid_start = max(0, mid - current_overlap)
            mid_end = min(text_len, mid + current_overlap)
            middle_chunk = text[mid_start:mid_end]
            middle_base_pos = base_pos + mid_start
            
            if len(middle_chunk) < text_len and len(middle_chunk) > 0:
                logger.debug(
                    f"[三路探测] 触发补漏机制 | 深度:{depth} | "
                    f"中间块长度:{len(middle_chunk)} | 位置:{middle_base_pos}-{middle_base_pos + len(middle_chunk)}"
                )
                await self._recursive_search(middle_chunk, middle_base_pos, depth + 1)
            elif len(middle_chunk) > 0:
                    logger.warning(
                        f"[三路探测] 中间块与父块同大小，强制作为叶子节点 | "
                        f"深度:{depth} | 长度:{len(middle_chunk)}"
                    )
                    segment = SensitiveSegment(text=middle_chunk, start_pos=middle_base_pos, 
                                             end_pos=middle_base_pos + len(middle_chunk))
                    self.found_segments.append(segment)
