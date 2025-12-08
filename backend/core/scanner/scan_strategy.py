"""
扫描策略基类和实现 (Scan Strategy)

职责：
- 定义统一的扫描策略接口
- 实现二分查找策略
- 实现微观精确定位策略
- 实现混合策略（自动选择）
- 消除重复的扫描逻辑

这个模块通过策略模式统一了 BinarySearcher 和 PrecisionScanner 的接口，
避免了在 TextScanner 中的重复逻辑。
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Callable

from ..engine import ProbeEngine, ScanStatus
from ..constants import MICRO_SCAN_THRESHOLD, DEFAULT_ALGORITHM_SWITCH_THRESHOLD
from .event_emitter import ScanEventEmitter
from ..event_bus import get_event_bus, EventTypes

logger = logging.getLogger(__name__)


@dataclass
class SensitiveSegment:
    """敏感片段数据类"""
    text: str
    start_pos: int
    end_pos: int


class ScanStrategy(ABC):
    """扫描策略基类"""

    @abstractmethod
    async def scan(self, text: str, base_pos: int = 0) -> List[SensitiveSegment]:
        """
        执行扫描
        
        Args:
            text: 待扫描的文本
            base_pos: 文本在原始全文中的起始位置
            
        Returns:
            敏感片段列表
        """
        pass


class MacroBinarySearchStrategy(ScanStrategy):
    """
    二分查找策略
    
    用于较长的文本，通过二分查找快速定位敏感内容的大致范围。
    """

    def __init__(
        self,
        engine: ProbeEngine,
        emitter: ScanEventEmitter,
        min_granularity: int = 1,
        overlap_size: int = 50,
        should_stop_flag: Optional[object] = None,
        algorithm_config: Optional[dict] = None,
        session_id: str = ""
    ):
        self.engine = engine
        self.emitter = emitter
        self.min_granularity = min_granularity
        self.overlap_size = overlap_size
        self.should_stop_flag = should_stop_flag
        self.session_id = session_id or "default"
        self.algorithm_config = algorithm_config or {}
        self.event_bus = get_event_bus()
        
        # 从配置加载参数
        self.enable_triple_probe = self.algorithm_config.get("enable_triple_probe", True)
        self.max_recursion_depth = self.algorithm_config.get("max_recursion_depth", 30)
        self.enable_deduplication = self.algorithm_config.get("enable_deduplication", True)
        self.dedup_overlap_threshold = self.algorithm_config.get("dedup_overlap_threshold", 0.5)
        self.dedup_adjacent_distance = self.algorithm_config.get("dedup_adjacent_distance", 30)
        
        self.found_segments: List[SensitiveSegment] = []
        self._current_block_reason: Optional[str] = None

    async def scan(self, text: str, base_pos: int = 0) -> List[SensitiveSegment]:
        """执行二分查找"""
        self.found_segments = []
        await self._recursive_search(text, base_pos, depth=0)
        return self.found_segments

    async def _probe_text(self, text: str) -> tuple[bool, Optional[str]]:
        """探测文本是否被拦截"""
        result = await self.engine.probe(text)
        block_reason = getattr(result, 'block_reason', None) if result.status == ScanStatus.BLOCKED else None
        return result.status == ScanStatus.BLOCKED, block_reason

    async def _recursive_search(self, text: str, base_pos: int, depth: int) -> None:
        """递归执行二分查找"""
        # 检查停止标志
        if self.should_stop_flag and getattr(self.should_stop_flag, 'should_stop', False):
            logger.warning(f"[{self.session_id}] 二分查找被用户中止 (深度: {depth})")
            return
        
        # 检查递归深度
        if depth > self.max_recursion_depth:
            logger.error(f"[{self.session_id}] 递归深度超限 ({depth} > {self.max_recursion_depth})")
            return

        if not text:
            return

        text_len = len(text)
        logger.debug(f"[{self.session_id}] 二分查找 - 深度: {depth}, 长度: {text_len}, 位置: {base_pos}")

        # 探测当前文本
        is_sensitive, block_reason = await self._probe_text(text)
        if not is_sensitive:
            logger.debug(f"[{self.session_id}] 文本安全，剪枝")
            return

        self._current_block_reason = block_reason

        # 如果文本已经很短，作为叶子节点
        if text_len <= self.min_granularity:
            segment = SensitiveSegment(text=text, start_pos=base_pos, end_pos=base_pos + text_len)
            self.found_segments.append(segment)
            
            await self.event_bus.emit(EventTypes.KEYWORD_FOUND, {
                'keyword': text,
                'session_id': self.session_id
            })
            
            logger.info(f"[{self.session_id}] 敏感词定位完成 | 长度: {text_len} | 位置: {base_pos}-{base_pos + text_len}")
            return

        # 执行二分查找
        await self.emitter.log_message(
            "warning",
            f"触发二分查找 | 深度:{depth + 1} | 当前片段长度:{text_len}"
        )

        mid = text_len // 2
        min_required_overlap = min(self.min_granularity, text_len // 4)
        current_overlap = max(self.overlap_size, min_required_overlap)
        max_safe_overlap = (text_len - 1) // 2
        current_overlap = min(current_overlap, max_safe_overlap)
        
        if current_overlap < 1 and text_len > 1:
            current_overlap = 1

        # 计算左右半部分
        left_start = 0
        left_end = min(mid + current_overlap, text_len)
        right_start = max(0, mid - current_overlap)
        right_end = text_len

        left_half_text = text[left_start:left_end]
        right_half_text = text[right_start:right_end]

        left_len = len(left_half_text)
        right_len = len(right_half_text)
        
        # 检查无效切分
        if left_len >= text_len or right_len >= text_len:
            logger.warning(f"[{self.session_id}] 无效切分，强制作为叶子节点")
            segment = SensitiveSegment(text=text, start_pos=base_pos, end_pos=base_pos + text_len)
            self.found_segments.append(segment)
            return

        # 并行探测两个半部分
        (left_is_sensitive, left_reason), (right_is_sensitive, right_reason) = await asyncio.gather(
            self._probe_text(left_half_text),
            self._probe_text(right_half_text)
        )

        # 递归处理敏感的半部分
        if left_is_sensitive:
            self._current_block_reason = left_reason
            await self._recursive_search(left_half_text, base_pos + left_start, depth + 1)

        if right_is_sensitive:
            self._current_block_reason = right_reason
            await self._recursive_search(right_half_text, base_pos + right_start, depth + 1)

        # 三路探测补漏机制
        if self.enable_triple_probe and not left_is_sensitive and not right_is_sensitive:
            mid_start = max(0, mid - current_overlap)
            mid_end = min(text_len, mid + current_overlap)
            middle_chunk = text[mid_start:mid_end]
            
            if len(middle_chunk) < text_len and len(middle_chunk) > 0:
                logger.debug(f"[{self.session_id}] 触发三路探测补漏机制")
                await self._recursive_search(middle_chunk, base_pos + mid_start, depth + 1)


class MicroPrecisionStrategy(ScanStrategy):
    """
    微观精确定位策略
    
    用于较短的文本，通过精确的双向挤压算法定位敏感词的精确边界。
    """

    def __init__(
        self,
        engine: ProbeEngine,
        emitter: ScanEventEmitter,
        session_id: str = ""
    ):
        self.engine = engine
        self.emitter = emitter
        self.session_id = session_id or "default"
        self.event_bus = get_event_bus()

    async def scan(self, text: str, base_pos: int = 0) -> List[SensitiveSegment]:
        """执行精确定位扫描"""
        results: List[SensitiveSegment] = []
        current_pos = 0
        iteration_count = 0
        max_iterations = 1000

        logger.debug(f"[{self.session_id}] 开始精细扫描 | 文本长度: {len(text)} | 基础位置: {base_pos}")

        while current_pos < len(text) and iteration_count < max_iterations:
            iteration_count += 1
            remaining_text = text[current_pos:]

            # 探测剩余文本
            result = await self.engine.probe(remaining_text)
            is_blocked = result.status == ScanStatus.BLOCKED

            if not is_blocked:
                logger.debug(f"[{self.session_id}] 剩余文本安全，扫描完成")
                break

            # 从左侧挤压
            left_boundary = await self._squeeze_left(remaining_text)
            
            # 从右侧挤压
            right_boundary = await self._squeeze_right(remaining_text)

            # 提取敏感词
            if left_boundary < right_boundary:
                sensitive_text = remaining_text[left_boundary:right_boundary]
                segment = SensitiveSegment(
                    text=sensitive_text,
                    start_pos=base_pos + current_pos + left_boundary,
                    end_pos=base_pos + current_pos + right_boundary
                )
                results.append(segment)

                await self.event_bus.emit(EventTypes.KEYWORD_FOUND, {
                    'keyword': sensitive_text,
                    'session_id': self.session_id
                })

                await self.emitter.log_message(
                    "success",
                    f"敏感词定位完成 | 词汇:'{sensitive_text}' | 位置:{segment.start_pos}-{segment.end_pos}"
                )

                # 继续扫描右侧的文本
                current_pos += right_boundary
            else:
                # 无法找到有效的边界，跳过
                current_pos += 1

        logger.info(f"[{self.session_id}] 精细扫描完成 | 提取敏感词数:{len(results)}")
        return results

    async def _squeeze_left(self, text: str) -> int:
        """从左侧挤压，找到左边界"""
        for i in range(len(text)):
            remaining = text[i:]
            result = await self.engine.probe(remaining)
            if result.status != ScanStatus.BLOCKED:
                return i
        return 0

    async def _squeeze_right(self, text: str) -> int:
        """从右侧挤压，找到右边界"""
        for i in range(len(text), 0, -1):
            remaining = text[:i]
            result = await self.engine.probe(remaining)
            if result.status != ScanStatus.BLOCKED:
                return i
        return len(text)


class HybridScanStrategy(ScanStrategy):
    """
    混合扫描策略
    
    根据文本长度自动选择二分查找或微观精确定位策略。
    """

    def __init__(
        self,
        engine: ProbeEngine,
        emitter: ScanEventEmitter,
        min_granularity: int = 1,
        overlap_size: int = 50,
        should_stop_flag: Optional[object] = None,
        algorithm_config: Optional[dict] = None,
        threshold: int = None,
        session_id: str = ""
    ):
        self.engine = engine
        self.emitter = emitter
        # 如果没有提供阈值，从算法配置中获取，否则使用默认值
        if threshold is None:
            if algorithm_config:
                threshold = algorithm_config.get("algorithm_switch_threshold", DEFAULT_ALGORITHM_SWITCH_THRESHOLD)
            else:
                threshold = DEFAULT_ALGORITHM_SWITCH_THRESHOLD
        self.threshold = threshold
        self.session_id = session_id or "default"
        
        # 创建两个策略实例
        self.macro_strategy = MacroBinarySearchStrategy(
            engine=engine,
            emitter=emitter,
            min_granularity=min_granularity,
            overlap_size=overlap_size,
            should_stop_flag=should_stop_flag,
            algorithm_config=algorithm_config,
            session_id=session_id
        )
        
        self.micro_strategy = MicroPrecisionStrategy(
            engine=engine,
            emitter=emitter,
            session_id=session_id
        )

    async def scan(self, text: str, base_pos: int = 0) -> List[SensitiveSegment]:
        """根据文本长度选择合适的策略"""
        if len(text) <= self.threshold:
            logger.info(f"[{self.session_id}] 使用双向挤压定位策略 (长度: {len(text)} <= {self.threshold})")
            return await self.micro_strategy.scan(text, base_pos)
        else:
            logger.info(f"[{self.session_id}] 使用二分法查找策略 (长度: {len(text)} > {self.threshold})")
            return await self.macro_strategy.scan(text, base_pos)











