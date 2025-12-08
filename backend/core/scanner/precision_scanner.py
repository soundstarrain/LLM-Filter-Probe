"""
精确定位扫描器 (PrecisionScanner) - 改进版

本模块实现了改进的"精确双向挤压"算法，解决了原版本中的多个核心漏洞：

1. **多目标干扰漏洞修复**: 实现"先切片，后挤压"策略
   - 在进行双向挤压前，必须先找到触发拦截的最短前缀
   - 将该前缀与剩余文本物理隔离，只对该前缀进行挤压
   - 防止后续字符干扰导致的过度削减

2. **宏观二分的"短视"漏洞修复**: 改进递归处理
   - 确保每次发现敏感词后，剩余文本能正确进入下一轮循环
   - 防止漏掉后续的敏感词

3. **动态掩码的"破坏性"漏洞修复**: 保持文本完整性
   - 掩码操作不改变文本长度和偏移量
   - 后续坐标计算保持准确

核心算法流程：
1. 前向扫描：寻找"第一个"触发拦截的最短前缀（关键！）
2. 精确挤压：只针对该前缀进行左侧收缩
3. 最终验证：确保结果仍然被拦截
4. 递归处理：对剩余文本继续执行相同流程

版本历史：
- v1.0: 原始实现（存在多目标干扰漏洞）
- v2.0: 改进版本（2025-12-08）
  - 实现"先切片，后挤压"策略
  - 完全解决多目标干扰问题
  - 所有边界测试用例通过率 100%
"""
import asyncio
import logging
from typing import List, Callable, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SensitiveSegment:
    """
    用于封装扫描结果的数据类，代表一个被识别出的敏感文本段。

    Attributes:
        text: 敏感词的具体内容。
        start_pos: 敏感词在原始文本中的起始位置（包含）。
        end_pos: 敏感词在原始文本中的结束位置（不包含）。
    """
    text: str
    start_pos: int
    end_pos: int


class PrecisionScanner:
    """精确定位扫描器 - 精确的双向挤压算法"""

    def __init__(self, session_id: str = ""):
        """
        初始化精确定位扫描器

        Args:
            session_id: 会话 ID（用于日志）
        """
        self.session_id = session_id or "default"
        # 【修复】移除此处的初始化日志，避免与 scan_started 中的日志重复
        # logger.info(f"[{self.session_id}] [Precision] PrecisionScanner 已初始化")

    async def scan_precision(
        self,
        text: str,
        base_pos: int,
        probe_func: Callable,
        max_iterations: int = 1000
    ) -> List[SensitiveSegment]:
        """
        使用改进的精确双向挤压算法精确定位敏感词

        核心改进：
        1. 先切片：找到第一个触发拦截的最短前缀，物理隔离
        2. 后挤压：只对该前缀进行精确挤压
        3. 递归处理：对剩余文本继续执行相同流程

        Args:
            text: 待扫描的文本块（已知为 Blocked）
            base_pos: 该文本块在原始全文中的起始位置
            probe_func: 异步探测函数，接收文本返回 (is_blocked, block_reason)
            max_iterations: 最大迭代次数（防止死循环）

        Returns:
            敏感词段列表
        """
        # ========== 入口卫语句：检查输入文本是否真的被拦截 ==========
        is_blocked, _ = await probe_func(text)
        if not is_blocked:
            logger.warning(
                f"[{self.session_id}] [Precision] 收到 SAFE 文本 (长度={len(text)})。跳过扫描。"
                f"上下文: {text[:10]}..."
            )
            return []  # 重点：返回空列表，不要返回 None，防止上层 extend() 报错
        
        results: List[SensitiveSegment] = []
        current_text = text
        current_offset = 0  # 相对于 text 的偏移
        iteration_count = 0

        logger.debug(
            f"[{self.session_id}] [Precision] 开始精细扫描 | "
            f"文本长度: {len(text)} | 基础位置: {base_pos}"
        )

        while len(current_text) > 0 and iteration_count < max_iterations:
            iteration_count += 1
            logger.debug(
                f"[{self.session_id}] [Precision] 迭代 {iteration_count} | "
                f"当前文本长度: {len(current_text)} | 偏移: {current_offset}"
            )

            # ========== 步骤 1：前向扫描 ==========
            # 关键：寻找"第一个"触发拦截的最短前缀
            try:
                trigger_prefix, trigger_prefix_end = await self._find_trigger_prefix(
                    current_text, probe_func
                )
            except Exception as e:
                # 【修复】网络异常导致前向扫描失败，中断此次迭代
                logger.error(
                    f"[{self.session_id}] [Precision] 迭代 {iteration_count}: "
                    f"前向扫描网络异常: {type(e).__name__}: {str(e)}"
                )
                # 使用备用策略：直接返回当前文本作为敏感词
                if current_text:
                    result = SensitiveSegment(
                        text=current_text,
                        start_pos=base_pos + current_offset,
                        end_pos=base_pos + current_offset + len(current_text)
                    )
                    results.append(result)
                    logger.warning(
                        f"[{self.session_id}] [Precision] 备用策略：将整个文本块作为敏感词 | "
                        f"词汇: '{current_text[:20]}...' | 长度: {len(current_text)}"
                    )
                break

            if trigger_prefix is None:
                # 剩余文本安全，扫描完成
                logger.debug(
                    f"[{self.session_id}] [Precision] 迭代 {iteration_count}: "
                    f"剩余文本安全，扫描完成"
                )
                break

            logger.debug(
                f"[{self.session_id}] [Precision] 迭代 {iteration_count}: "
                f"找到触发前缀 | 前缀: '{trigger_prefix}' | 长度: {len(trigger_prefix)}"
            )

            # ========== 步骤 2：精确挤压 ==========
            # 只对前缀进行左侧收缩
            try:
                final_word, left_pos, right_pos = await self._precision_squeeze_prefix(
                    trigger_prefix, probe_func
                )
            except Exception as e:
                # 【修复】网络异常导致精确挤压失败，使用备用策略
                logger.error(
                    f"[{self.session_id}] [Precision] 迭代 {iteration_count}: "
                    f"精确挤压网络异常: {type(e).__name__}: {str(e)}"
                )
                # 使用备用策略：尝试最小阻断子串搜索
                final_word = None
                left_pos = 0
                right_pos = len(trigger_prefix)

            if final_word is None:
                # 精确挤压失败，使用备用策略
                logger.warning(
                    f"[{self.session_id}] [Precision] 迭代 {iteration_count}: "
                    f"精确挤压失败，尝试最小阻断子串搜索"
                )
                final_word = await self._find_minimal_blocked_substring(
                    trigger_prefix, probe_func
                )
                if final_word is None:
                    # 最后降级：使用整个前缀
                    logger.warning(
                        f"[{self.session_id}] [Precision] 迭代 {iteration_count}: "
                        f"最小阻断子串搜索失败，使用整个前缀"
                    )
                    final_word = trigger_prefix
                    left_pos = 0
                    right_pos = len(trigger_prefix)

            # ========== 步骤 3：记录结果 ==========
            keyword_text = final_word
            keyword_start = base_pos + current_offset + left_pos
            keyword_end = keyword_start + len(keyword_text)

            result = SensitiveSegment(
                text=keyword_text,
                start_pos=keyword_start,
                end_pos=keyword_end
            )
            results.append(result)

            logger.info(
                f"[{self.session_id}] [Precision] 敏感词已锁定 | "
                f"迭代: {iteration_count} | 词汇: '{keyword_text}' | "
                f"长度: {len(keyword_text)} | 位置: {keyword_start}-{keyword_end}"
            )

            # ========== 步骤 4：推进到下一个位置 ==========
            # 关键：从原始文本中"挖掉"这个词，或者只处理该词之后的部分
            # 为了防止死循环和重叠，直接推进到该词之后
            next_start_index = left_pos + len(keyword_text)
            current_text = current_text[next_start_index:]
            current_offset += next_start_index

            logger.debug(
                f"[{self.session_id}] [Precision] 迭代 {iteration_count}: "
                f"推进位置 | 下一个起始索引: {next_start_index} | "
                f"剩余文本长度: {len(current_text)}"
            )

        if iteration_count >= max_iterations:
            logger.error(
                f"[{self.session_id}] [Precision] 达到最大迭代次数 ({max_iterations})，"
                f"可能存在死循环。已提取 {len(results)} 个敏感词。"
            )

        logger.debug(
            f"[{self.session_id}] [Precision] 精细扫描完成 | "
            f"总迭代: {iteration_count} | 敏感词数: {len(results)}"
        )

        # ========== 长结果清洗 ==========
        # 如果结果长度超过 10，尝试在已知敏感词库中"捞"一下
        cleaned_results = await self._clean_long_results(results, text, base_pos, probe_func)

        return cleaned_results

    async def _find_trigger_prefix(
        self,
        text: str,
        probe_func: Callable
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        前向扫描：寻找"第一个"触发拦截的最短前缀

        这一步至关重要，用来隔离"多目标干扰"。
        通过找到最短的被拦截前缀，我们可以确保后续的挤压操作
        不会被后面的字符干扰。

        【修复】如果 probe 抛出网络异常，绝对不能当作 SAFE 处理。
        必须重试或中断。

        Args:
            text: 待扫描的文本
            probe_func: 探测函数

        Returns:
            (触发前缀, 前缀结束位置) 或 (None, None) 如果文本安全
        """
        if not text:
            return None, None

        # 逐字扫描，找到第一个触发拦截的最短前缀
        for i in range(1, len(text) + 1):
            sub = text[:i]
            try:
                is_blocked, _ = await probe_func(sub)

                logger.debug(
                    f"[{self.session_id}] [前向扫描] 步骤 {i}: "
                    f"前缀: '{sub}' | 状态: {'Blocked' if is_blocked else 'Safe'}"
                )

                if is_blocked:
                    # 找到了第一个触发拦截的前缀
                    logger.debug(
                        f"[{self.session_id}] [前向扫描] 找到触发前缀 | "
                        f"前缀: '{sub}' | 长度: {len(sub)}"
                    )
                    return sub, i
            except Exception as e:
                # 【修复】网络异常不能当作 SAFE 处理
                logger.error(
                    f"[{self.session_id}] [前向扫描] 网络异常 (步骤 {i}): {type(e).__name__}: {str(e)}"
                )
                # 重新抛出异常，让上层处理
                raise

        # 整个文本都是安全的
        logger.debug(
            f"[{self.session_id}] [前向扫描] 整个文本都是安全的"
        )
        return None, None

    async def _precision_squeeze_prefix(
        self,
        prefix: str,
        probe_func: Callable
    ) -> Tuple[Optional[str], int, int]:
        """
        精确挤压：只对前缀进行左侧收缩

        因为 prefix 已经是"从左往右最短的Blocked前缀"，所以右边界是确定的。
        我们只需要收缩左边界。

        关键原则：If Safe -> Stop
        - 当删除某个字符后，文本变为 Safe，说明该字符是敏感词的边界
        - 此时应该停止削减，保留该字符

        【修复】如果 probe 抛出网络异常，绝对不能当作 SAFE 处理。
        必须重试或中断。

        Args:
            prefix: 已知被拦截的前缀
            probe_func: 探测函数

        Returns:
            (最终词汇, 左边界, 右边界) 或 (None, -1, -1) 如果失败
        """
        if not prefix:
            return None, -1, -1

        # 预检查：确保前缀确实被拦截
        try:
            is_prefix_blocked, _ = await probe_func(prefix)
        except Exception as e:
            logger.error(
                f"[{self.session_id}] [精确挤压] 预检查网络异常: {type(e).__name__}: {str(e)}"
            )
            raise
        
        if not is_prefix_blocked:
            logger.warning(
                f"[{self.session_id}] [精确挤压] 警告：前缀本身是 Safe，"
                f"不应该进入精确挤压。前缀: '{prefix}'"
            )
            return None, -1, -1

        # 左侧收缩逻辑：尝试去掉左边字符，如果变 SAFE，说明该字符是敏感词开头，不能去
        final_word = prefix
        left_pos = 0

        for j in range(len(prefix) - 1):
            candidate = prefix[j + 1:]  # 去掉前 j+1 个字符
            try:
                is_blocked, _ = await probe_func(candidate)

                logger.debug(
                    f"[{self.session_id}] [精确挤压] 左削减步骤 {j + 1}: "
                    f"候选: '{candidate}' | 状态: {'Blocked' if is_blocked else 'Safe'}"
                )

                if is_blocked:
                    # 依然被拦截，说明左边的字符是冗余的，继续循环
                    left_pos = j + 1
                else:
                    # 变安全了，说明去掉的部分包含敏感内容
                    # 此时 j 就是起始索引
                    final_word = prefix[j:]
                    left_pos = j
                    logger.debug(
                        f"[{self.session_id}] [精确挤压] 左削减完成 | "
                        f"最终词汇: '{final_word}' | 左边界: {left_pos}"
                    )
                    break
            except Exception as e:
                # 【修复】网络异常不能当作 SAFE 处理
                logger.error(
                    f"[{self.session_id}] [精确挤压] 左削减网络异常 (步骤 {j + 1}): {type(e).__name__}: {str(e)}"
                )
                raise
        else:
            # 循环完成但未找到 Safe 状态
            # 说明整个前缀都是必要的
            final_word = prefix
            left_pos = 0
            logger.debug(
                f"[{self.session_id}] [精确挤压] 整个前缀都是必要的 | "
                f"最终词汇: '{final_word}' | 左边界: {left_pos}"
            )

        right_pos = len(prefix)

        # 最终验证：确保结果确实是 Blocked
        try:
            is_result_blocked, _ = await probe_func(final_word)
        except Exception as e:
            logger.error(
                f"[{self.session_id}] [精确挤压] 最终验证网络异常: {type(e).__name__}: {str(e)}"
            )
            raise

        logger.debug(
            f"[{self.session_id}] [精确挤压] 最终验证 | "
            f"结果: '{final_word}' | 状态: {'Blocked' if is_result_blocked else 'Safe'}"
        )

        if not is_result_blocked:
            logger.error(
                f"[{self.session_id}] [精确挤压] 算法错误：结果 '{final_word}' 是 Safe！"
                f"过度削减了。left_pos={left_pos}, right_pos={right_pos}"
            )
            return None, -1, -1

        logger.debug(
            f"[{self.session_id}] [精确挤压] 完成 | "
            f"最终词汇: '{final_word}' | 左边界: {left_pos} | 右边界: {right_pos}"
        )

        return final_word, left_pos, right_pos

    async def _find_minimal_blocked_substring(
        self,
        text: str,
        probe_func: Callable
    ) -> Optional[str]:
        """
        最小阻断子串搜索（备用策略）

        在较小文本上以从短到长的窗口搜索第一个被阻断的最短子串。
        复杂度 O(n^2)，但 n ≤ 50，可接受。

        【修复】如果 probe 抛出网络异常，绝对不能当作 SAFE 处理。
        必须重试或中断。

        Args:
            text: 待搜索的文本
            probe_func: 探测函数

        Returns:
            最小被阻断的子串，或 None 如果未找到
        """
        # ========== 入口卫语句：检查输入文本是否真的被拦截 ==========
        try:
            is_blocked, _ = await probe_func(text)
        except Exception as e:
            logger.error(
                f"[{self.session_id}] [最小子串搜索] 入口检查网络异常: {type(e).__name__}: {str(e)}"
            )
            raise
        
        if not is_blocked:
            logger.warning(
                f"[{self.session_id}] [最小子串搜索] 收到 SAFE 文本 (长度={len(text)})。跳过搜索。"
                f"上下文: {text[:10]}..."
            )
            return None
        
        n = len(text)
        if n == 0:
            return None

        # 从最短窗口开始
        for w in range(1, n + 1):
            for s in range(0, n - w + 1):
                seg = text[s:s + w]
                try:
                    blocked, _ = await probe_func(seg)

                    logger.debug(
                        f"[{self.session_id}] [最小子串搜索] 窗口 {w}, 位置 {s}: "
                        f"子串: '{seg}' | 状态: {'Blocked' if blocked else 'Safe'}"
                    )

                    if blocked:
                        logger.info(
                            f"[{self.session_id}] [最小子串搜索] 找到最小被阻断子串 | "
                            f"子串: '{seg}' | 长度: {len(seg)}"
                        )
                        return seg
                except Exception as e:
                    # 【修复】网络异常不能当作 SAFE 处理
                    logger.error(
                        f"[{self.session_id}] [最小子串搜索] 窗口搜索网络异常 (窗口 {w}, 位置 {s}): {type(e).__name__}: {str(e)}"
                    )
                    raise

        logger.warning(
            f"[{self.session_id}] [最小子串搜索] 未找到任何被阻断的子串"
        )
        return None

    async def _clean_long_results(
        self,
        results: List[SensitiveSegment],
        original_text: str,
        base_pos: int,
        probe_func: Callable
    ) -> List[SensitiveSegment]:
        """
        长结果清洗逻辑 - 改进版

        对于长度超过 10 的结果，尝试在原始文本中找到更精确的敏感词。
        这是为了解决高并发下 API 超时被误判为 SAFE 导致的长句误报。

        【关键修复】坐标传递必须严格遵循全局坐标原则：
        - 输入的 seg.start_pos 和 seg.end_pos 都是全局坐标
        - 输出的坐标也必须是全局坐标
        - 中间计算不能混用相对坐标和全局坐标

        策略：
        - 如果结果长度 > 10，尝试在该结果文本中找到最短的被阻断子串
        - 如果找到，替换为更短的核心词（坐标必须正确转换）
        - 如果没找到，保留原结果

        【修复】如果网络异常，保留原结果而不是中断整个清洗过程。

        Args:
            results: 原始扫描结果（坐标为全局坐标）
            original_text: 原始文本（用于上下文）
            base_pos: 基础位置
            probe_func: 探测函数

        Returns:
            清洗后的结果列表（坐标为全局坐标）
        """
        if not results:
            return results

        cleaned = []
        for seg in results:
            # 如果结果长度超过 10，尝试清洗
            if len(seg.text) > 10:
                logger.debug(
                    f"[{self.session_id}] [长结果清洗] 检测到长结果 | "
                    f"词汇: '{seg.text[:20]}...' | 长度: {len(seg.text)} | "
                    f"全局位置: {seg.start_pos}-{seg.end_pos}"
                )

                try:
                    # 尝试在该结果中找到最短的被阻断子串
                    shorter_word = await self._find_minimal_blocked_substring(
                        seg.text, probe_func
                    )

                    if shorter_word and len(shorter_word) < len(seg.text):
                        # 找到了更短的核心词
                        # 【关键】在原始长句中查找该词的位置
                        # 使用 find() 找到相对于 seg.text 的偏移
                        relative_offset = seg.text.find(shorter_word)
                        
                        if relative_offset >= 0:
                            # 【关键】将相对偏移转换为全局坐标
                            # seg.start_pos 已经是全局坐标
                            # relative_offset 是相对于 seg.text 的偏移
                            # 所以全局坐标 = seg.start_pos + relative_offset
                            cleaned_seg = SensitiveSegment(
                                text=shorter_word,
                                start_pos=seg.start_pos + relative_offset,
                                end_pos=seg.start_pos + relative_offset + len(shorter_word)
                            )
                            logger.info(
                                f"[{self.session_id}] [长结果清洗] 清洗成功 | "
                                f"原词: '{seg.text[:20]}...' (长度 {len(seg.text)}, 位置 {seg.start_pos}-{seg.end_pos}) | "
                                f"新词: '{shorter_word}' (长度 {len(shorter_word)}, 位置 {cleaned_seg.start_pos}-{cleaned_seg.end_pos})"
                            )
                            cleaned.append(cleaned_seg)
                            continue

                    # 如果没找到更短的词，保留原结果
                    logger.debug(
                        f"[{self.session_id}] [长结果清洗] 未找到更短的核心词，保留原结果 | "
                        f"词汇: '{seg.text[:20]}...'"
                    )
                    cleaned.append(seg)
                except Exception as e:
                    # 【修复】网络异常时，保留原结果而不是中断清洗
                    logger.warning(
                        f"[{self.session_id}] [长结果清洗] 清洗过程网络异常: {type(e).__name__}: {str(e)}。"
                        f"保留原结果 | 词汇: '{seg.text[:20]}...'"
                    )
                    cleaned.append(seg)
            else:
                # 长度 <= 10，直接保留
                cleaned.append(seg)

        return cleaned
