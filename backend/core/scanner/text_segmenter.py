"""
文本分段器 (Text Segmenter)

职责：
- 将长文本分割成固定大小的块
- 处理块之间的重叠部分，以避免漏掉跨边界的敏感词
"""
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

class TextSegmenter:
    """将文本分割成段"""

    def __init__(self, segment_size: int, overlap_size: int):
        """
        初始化文本分段器

        Args:
            segment_size: 每个文本段的目标大小（字符数）
            overlap_size: 段与段之间的重叠大小（字符数）
        """
        if segment_size <= 0:
            raise ValueError("Segment size must be positive.")
        if overlap_size < 0:
            raise ValueError("Overlap size cannot be negative.")
        if overlap_size >= segment_size:
            raise ValueError("Overlap size must be smaller than segment size.")

        self.segment_size = segment_size
        self.overlap_size = overlap_size
        # 【修复】移除此处的初始化日志，避免与 scan_started 中的日志重复
        # logger.info(f"TextSegmenter initialized with segment_size={segment_size}, overlap_size={overlap_size}")

    def split(self, text: str) -> List[Tuple[str, int, int]]:
        """
        将文本分割成带有重叠的段

        关键优化：
        1. 确保重叠大小足够大，防止跨边界的敏感词被漏掉
        2. 边界条件检查，防止死循环
        3. 确保最后一个段也被正确处理

        Args:
            text: 待分割的文本

        Returns:
            一个元组列表，每个元组包含 (文本段, 开始位置, 结束位置)
        """
        if not text:
            return []

        segments = []
        text_len = len(text)
        start = 0

        # 边界检查：确保配置有效
        if self.segment_size <= 0:
            logger.warning(f"[Invalid Config] segment_size must be positive, got {self.segment_size}. Using text length.")
            segments.append((text, 0, text_len))
            return segments
        
        if self.overlap_size < 0:
            logger.warning(f"[Invalid Config] overlap_size cannot be negative, got {self.overlap_size}. Using 0.")
            self.overlap_size = 0
        
        if self.overlap_size >= self.segment_size:
            logger.warning(f"[Invalid Config] overlap_size ({self.overlap_size}) >= segment_size ({self.segment_size}). "
                         f"Reducing overlap_size to {self.segment_size // 2}.")
            self.overlap_size = max(1, self.segment_size // 2)

        while start < text_len:
            end = start + self.segment_size
            # 确保最后一个段不会超出文本末尾
            if end > text_len:
                end = text_len
            
            segment_text = text[start:end]
            segments.append((segment_text, start, end))
            
            # 如果已经到达文本末尾，结束
            if end >= text_len:
                break
            
            # 计算下一个段的起始位置
            # 关键：使用重叠确保不会漏掉跨边界的敏感词
            next_start = end - self.overlap_size
            
            # 边界检查：防止死循环
            # 如果下一个起始点 <= 当前起始点，说明重叠太大或段太小
            if next_start <= start:
                # 如果还有剩余文本，添加最后一个段
                if end < text_len:
                    remaining_text = text[end:]
                    if remaining_text:
                        segments.append((remaining_text, end, text_len))
                break
            
            start = next_start

        logger.debug(f"Text split into {len(segments)} segments with overlap_size={self.overlap_size}.")
        return segments

