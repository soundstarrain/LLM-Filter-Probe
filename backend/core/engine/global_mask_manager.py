"""
全局掩码管理器 (GlobalMaskManager)

实现等长延迟掩码机制 (Iso-Length Lazy Masking)，确保掩码后的文本长度与原文本严格一致。

核心特性：
- **等长替换**: 将敏感词替换为相同长度的填充符（如 '*'），保持文本长度不变
- **延迟绑定**: 在并发扫描过程中，动态获取最新的已知敏感词列表
- **坐标锚定**: 由于长度不变，坐标系始终一致，避免去重错误
- **线程安全**: 使用 threading.RLock 保护共享数据结构
"""

import logging
import threading
from typing import Set, Dict, Optional

logger = logging.getLogger(__name__)


class GlobalMaskManager:
    """
    全局掩码管理器，负责维护已知敏感词列表并提供等长掩码功能。
    
    主要方法：
    - add_keyword(keyword): 添加一个已知敏感词
    - get_all_keywords(): 获取所有已知敏感词的快照（线程安全）
    - apply_masks(text): 对文本应用等长掩码
    - reset(): 清空所有已知敏感词
    """
    
    def __init__(self, mask_char: str = "*"):
        """
        初始化全局掩码管理器
        
        Args:
            mask_char: 用于替换敏感词的填充字符，默认为 '*'
        """
        self.mask_char = mask_char
        self.known_keywords: Set[str] = set()
        self.lock = threading.RLock()
        
        logger.info(f"[GlobalMaskManager] 已初始化 | mask_char='{mask_char}'")
    
    def add_keyword(self, keyword: str) -> bool:
        """
        添加一个已知敏感词
        
        Args:
            keyword: 敏感词
            
        Returns:
            True 表示新添加，False 表示已存在
        """
        if not keyword:
            return False
        
        with self.lock:
            if keyword in self.known_keywords:
                return False
            
            self.known_keywords.add(keyword)
            logger.debug(f"[GlobalMaskManager] 添加敏感词 | keyword='{keyword}' | 总数={len(self.known_keywords)}")
            return True
    
    def get_all_keywords(self) -> Set[str]:
        """
        获取所有已知敏感词的快照（线程安全）
        
        Returns:
            已知敏感词集合的副本
        """
        with self.lock:
            return self.known_keywords.copy()
    
    def apply_masks(self, text: str) -> str:
        """
        对文本应用等长掩码，将所有已知敏感词替换为相同长度的填充符。
        
        关键特性：
        - 等长替换：replacement 的长度 == keyword 的长度
        - 保持坐标系一致：masked_text 的长度 == text 的长度
        - 避免重复替换：使用 replace 方法（不支持正则，但足够安全）
        
        Args:
            text: 原始文本
            
        Returns:
            掩码后的文本（长度与原文本相同）
        """
        if not text:
            return text
        
        # 获取当前所有已知敏感词的快照（线程安全）
        current_keywords = self.get_all_keywords()
        
        if not current_keywords:
            return text
        
        masked_text = text
        
        # 按长度从长到短排序，避免短词替换后影响长词
        # 例如：如果有 "轮奸" 和 "奸"，应先替换 "轮奸"
        sorted_keywords = sorted(current_keywords, key=len, reverse=True)
        
        for keyword in sorted_keywords:
            if keyword in masked_text:
                # 关键：替换为相同长度的填充符
                replacement = self.mask_char * len(keyword)
                masked_text = masked_text.replace(keyword, replacement)
                logger.debug(
                    f"[GlobalMaskManager] 等长替换 | keyword='{keyword}' | "
                    f"len={len(keyword)} | replacement='{replacement}'"
                )
        
        # 验证长度一致性（调试用）
        if len(masked_text) != len(text):
            logger.error(
                f"[GlobalMaskManager] 长度不一致！原文本长度={len(text)}, "
                f"掩码后长度={len(masked_text)}"
            )
        
        return masked_text
    
    def reset(self):
        """清空所有已知敏感词"""
        with self.lock:
            count = len(self.known_keywords)
            self.known_keywords.clear()
            logger.info(f"[GlobalMaskManager] 已重置 | 清除了 {count} 个敏感词")
    
    def get_statistics(self) -> Dict[str, int]:
        """获取掩码管理器的统计信息"""
        with self.lock:
            return {
                "known_keywords_count": len(self.known_keywords),
                "mask_char": self.mask_char
            }

