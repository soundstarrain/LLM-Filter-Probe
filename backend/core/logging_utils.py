"""
结构化日志工具 - 减少重复的日志格式化代码

提供统一的日志记录接口，避免在多个模块中重复相同的日志格式化逻辑。
这样可以：
1. 确保日志格式一致
2. 减少代码重复
3. 便于后续修改日志格式
"""
import logging
from typing import Any, Optional, Dict


class StructuredLogger:
    """
    结构化日志工具 - 为特定的会话提供统一的日志记录接口
    
    用法:
        logger = StructuredLogger(logging.getLogger(__name__), session_id)
        logger.phase_completed(1, 3, 100, 80)
        logger.keyword_found('敏感词', 5)
    """
    
    def __init__(self, logger: logging.Logger, session_id: str):
        """
        初始化结构化日志工具
        
        Args:
            logger: Python 标准库的 Logger 实例
            session_id: 会话 ID，用于日志前缀
        """
        self.logger = logger
        self.session_id = session_id
    
    def phase_completed(self, phase_num: int, total_phases: int, 
                       input_count: int, output_count: int, 
                       phase_name: str = "Golden Flow", **extra):
        """
        记录检验流程阶段完成日志
        
        Args:
            phase_num: 当前阶段号（1-based）
            total_phases: 总阶段数
            input_count: 输入数量
            output_count: 输出数量
            phase_name: 流程名称（默认为 "Golden Flow"）
            **extra: 额外的信息，会追加到日志末尾
        """
        filter_rate = (1 - output_count / max(1, input_count)) * 100
        
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.info(
            f"[{self.session_id}] [{phase_name}] 阶段 {phase_num}/{total_phases}: "
            f"完成 | 输入: {input_count} → 输出: {output_count} | "
            f"过滤率: {filter_rate:.1f}%{extra_str}"
        )
    
    def keyword_found(self, keyword: str, count: int, 
                     known_keywords_count: int = 0, **extra):
        """
        记录关键词发现日志
        
        Args:
            keyword: 发现的关键词
            count: 该关键词出现的次数
            known_keywords_count: 已知敏感词总数
            **extra: 额外的信息
        """
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        known_str = f" | 已知词数: {known_keywords_count}" if known_keywords_count > 0 else ""
        
        self.logger.info(
            f"[{self.session_id}] [Masking] 新敏感词已锁定 | "
            f"词汇: '{keyword}' | 出现次数: {count}{known_str}{extra_str}"
        )
    
    def validation_started(self, candidate_count: int, **extra):
        """记录验证阶段开始"""
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.info(
            f"[{self.session_id}] [Validation] 开始验证 {candidate_count} 个候选片段（并发模式）...{extra_str}"
        )
    
    def validation_completed(self, candidate_count: int, passed_count: int, **extra):
        """记录验证阶段完成"""
        filter_rate = (1 - passed_count / max(1, candidate_count)) * 100
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.info(
            f"[{self.session_id}] [Validation] 验证完成（并发） | "
            f"候选数: {candidate_count} | 通过数: {passed_count} | "
            f"过滤率: {filter_rate:.1f}%{extra_str}"
        )
    
    def refinement_started(self, segment_count: int, **extra):
        """记录精炼阶段开始"""
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.info(
            f"[{self.session_id}] [Refinement] 开始精炼 {segment_count} 个已验证片段...{extra_str}"
        )
    
    def refinement_completed(self, input_count: int, output_count: int, **extra):
        """记录精炼阶段完成"""
        dedup_rate = (1 - output_count / max(1, input_count)) * 100
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.info(
            f"[{self.session_id}] [Refinement] 精炼完成 | "
            f"输入片段数: {input_count} | 输出关键词数: {output_count} | "
            f"去重率: {dedup_rate:.1f}%{extra_str}"
        )
    
    def enumeration_started(self, keyword_count: int, **extra):
        """记录最终清点阶段开始"""
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.info(
            f"[{self.session_id}] [Enumeration] 开始最终清点，关键词数: {keyword_count}{extra_str}"
        )
    
    def enumeration_completed(self, keyword_count: int, result_count: int, **extra):
        """记录最终清点阶段完成"""
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.info(
            f"[{self.session_id}] [Enumeration] 最终清点完成 | "
            f"核心关键词数: {keyword_count} | 最终结果数: {result_count}{extra_str}"
        )
    
    def golden_flow_completed(self, dirty_count: int, final_count: int, 
                             duration_str: str = "", **extra):
        """记录检验流程完成"""
        filter_rate = (1 - final_count / max(1, dirty_count)) * 100
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        duration_suffix = f" | 耗时: {duration_str}" if duration_str else ""
        
        self.logger.info(
            f"[{self.session_id}] [Golden Flow] 检验流程完成 | "
            f"脏数据: {dirty_count} → 最终结果: {final_count} | "
            f"总过滤率: {filter_rate:.1f}%{duration_suffix}{extra_str}"
        )
    
    def scan_completed(self, sensitive_count: int, request_count: int, 
                      duration_str: str = "", keyword_count: int = 0, **extra):
        """记录扫描完成"""
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        keyword_suffix = f" | 分组关键词: {keyword_count}" if keyword_count > 0 else ""
        
        self.logger.info(
            f"[{self.session_id}] 扫描完成 | "
            f"发现: {sensitive_count} | 总请求: {request_count}{keyword_suffix} | "
            f"总耗时: {duration_str}{extra_str}"
        )
    
    def segment_processed(self, segment_index: int, total_segments: int, 
                         status: str, **extra):
        """记录单个段的处理结果"""
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.debug(
            f"[{self.session_id}] 段 {segment_index + 1}/{total_segments} "
            f"处理完成 | 状态: {status}{extra_str}"
        )
    
    def progress_updated(self, scanned: int, total: int, sensitive_count: int, **extra):
        """记录进度更新"""
        progress_percent = (scanned / max(1, total)) * 100
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.debug(
            f"[{self.session_id}] 进度更新 | "
            f"已扫描: {scanned}/{total} ({progress_percent:.1f}%) | "
            f"敏感词数: {sensitive_count}{extra_str}"
        )
    
    def error_occurred(self, error_type: str, error_msg: str, **extra):
        """记录错误"""
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.error(
            f"[{self.session_id}] [{error_type}] 错误: {error_msg}{extra_str}"
        )
    
    def warning_occurred(self, warning_type: str, warning_msg: str, **extra):
        """记录警告"""
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.warning(
            f"[{self.session_id}] [{warning_type}] 警告: {warning_msg}{extra_str}"
        )
    
    def debug_message(self, message: str, **extra):
        """记录调试信息"""
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.debug(f"[{self.session_id}] {message}{extra_str}")
    
    def info_message(self, message: str, **extra):
        """记录信息"""
        extra_str = ""
        if extra:
            extra_str = " | " + " | ".join(f"{k}: {v}" for k, v in extra.items())
        
        self.logger.info(f"[{self.session_id}] {message}{extra_str}")

