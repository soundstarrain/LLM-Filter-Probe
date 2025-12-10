"""
会话管理器 (Session Manager) - 重构版

职责：
- 创建和销毁扫描会话 (ScanSession)
- 为每个会话初始化 ScanService
- 管理会话的生命周期
- （新增）维护基于 HTTP 轮询的扫描状态与结果缓存
"""
import uuid
import logging
import asyncio
from typing import Dict, Optional, Any, List
from datetime import datetime

from core.presets import Preset
from core.config_manager import get_config_manager
from core.config_normalizer import ConfigNormalizer
from services.scan_service import ScanService
from handlers.websocket_handler import WebSocketHandler

logger = logging.getLogger(__name__)

class ScanSession:
    """代表一个独立的扫描会话"""

    def __init__(self, session_id: str, preset: Preset):
        self.session_id = session_id
        self.preset = preset
        self.created_at = datetime.now()
        self.scan_service: Optional[ScanService] = None
        self.websocket_handler: Optional[WebSocketHandler] = None

        # ---- 简化版 HTTP 轮询所需的状态缓存 ----
        self.status: str = 'idle'  # idle | scanning | completed | error | canceled
        self.progress: Dict[str, Any] = {
            'current': 0,
            'total': 0,
            'percentage': 0
        }
        self.results: List[Dict[str, Any]] = []  # {text, start_pos, end_pos, reason?}
        self.logs: List[Dict[str, Any]] = []
        self.summary: Dict[str, Any] = {}  # api_calls, duration_seconds 等
        self.scan_task: Optional[asyncio.Task] = None

    async def initialize(self, event_callback=None):
        """
        初始化会话所需的服务
        
        Args:
            event_callback: 可选的事件回调函数，用于推送实时事件
        """
        try:
            logger.info(f"[{self.session_id}] Initializing session with preset '{self.preset.name}'.")
            self.scan_service = ScanService(preset=self.preset, session_id=self.session_id)
            await self.scan_service.initialize(event_callback=event_callback)

            self.websocket_handler = WebSocketHandler(session_id=self.session_id, scan_service=self.scan_service)
            logger.info(f"[{self.session_id}] Session initialized successfully.")
        except Exception as e:
            logger.error(f"[{self.session_id}] Session initialization failed: {e}", exc_info=True)
            await self.close()
            raise

    async def close(self):
        """清理会话资源"""
        if self.scan_service:
            await self.scan_service.cleanup()
        logger.info(f"[{self.session_id}] Session closed.")

    def get_info(self) -> Dict:
        """获取会话的基本信息"""
        return {
            "session_id": self.session_id,
            "preset_name": self.preset.name,
            "created_at": self.created_at.isoformat(),
            "uptime": (datetime.now() - self.created_at).total_seconds(),
        }

    # ---------------- HTTP 轮询扫描支持（新增） ----------------
    async def start_scan(self, text: str):
        """以异步任务方式启动一次扫描，并缓存进度与结果，供 HTTP 轮询查询"""
        if not text:
            raise ValueError("text 不能为空")
        if self.scan_task and not self.scan_task.done():
            raise RuntimeError("已有扫描任务在进行中")

        # 事件回调：由底层扫描流程调用，这里把事件转为内存状态
        async def event_cb(message: Dict[str, Any]):
            try:
                event = message.get('event') or message.get('type')
                data = message.get('data') or {}
                if event == 'scan_start':
                    total_length = data.get('total_length') or data.get('total') or 0
                    self.progress.update({
                        'current': 0,
                        'total': total_length,
                        'percentage': 0
                    })
                    self.status = 'scanning'
                elif event == 'progress':
                    scanned = data.get('scanned') or data.get('current') or 0
                    total = data.get('total') or self.progress.get('total') or 0
                    percentage = int(scanned / total * 100) if total > 0 else 0
                    self.progress.update({
                        'current': scanned,
                        'total': total,
                        'percentage': percentage
                    })
                elif event == 'sensitive_found_batch':
                    findings = data.get('findings') or []
                    # findings: [{keyword, start, end}]
                    for f in findings:
                        self.results.append({
                            'text': f.get('keyword'),
                            'start_pos': f.get('start'),
                            'end_pos': f.get('end'),
                            'reason': 'BLOCKED'
                        })
                elif event == 'scan_complete':
                    # 完成事件
                    self.status = 'completed'
                    stats = self.scan_service.get_statistics() if self.scan_service else {}
                    complete_data = data or {}
                    # 将最终的分组结果转换为列表形式，便于前端直接展示
                    final_grouped = complete_data.get('results') or {}
                    if isinstance(final_grouped, dict):
                        for keyword, positions in final_grouped.items():
                            try:
                                for pos in positions or []:
                                    # 允许 positions 是 [start] 或 ["start-end"] 或 [start, end] 的灵活格式
                                    if isinstance(pos, str) and '-' in pos:
                                        parts = pos.split('-', 1)
                                        start_pos = int(parts[0])
                                        end_pos = int(parts[1])
                                    elif isinstance(pos, (list, tuple)) and len(pos) == 2:
                                        start_pos = int(pos[0]); end_pos = int(pos[1])
                                    else:
                                        # 只有起点时，按照关键词长度推断终点
                                        start_pos = int(pos)
                                        end_pos = start_pos + len(str(keyword))
                                    self.results.append({
                                        'text': str(keyword),
                                        'start_pos': start_pos,
                                        'end_pos': end_pos,
                                        'reason': 'BLOCKED'
                                    })
                            except Exception:
                                # 忽略个别格式异常
                                continue
                    self.summary = {
                        'api_calls': stats.get('api_calls') or complete_data.get('total_requests') or 0,
                        'elapsed_time': complete_data.get('duration_seconds') or complete_data.get('execution_time') or 0,
                        'unknown_status_codes': complete_data.get('unknown_status_codes') or []
                    }
                    # 将进度置为 100%
                    total = self.progress.get('total') or 0
                    self.progress.update({'current': total, 'percentage': 100})
                elif event == 'log':
                    level = message.get('level') or data.get('level') or 'info'
                    msg = message.get('message') or data.get('message') or ''
                    self.logs.append({
                        'timestamp': datetime.now().isoformat(),
                        'level': level,
                        'message': msg,
                    })
                elif event == 'error':
                    self.status = 'error'
                    msg = message.get('message') or data.get('message') or '扫描错误'
                    self.logs.append({
                        'timestamp': datetime.now().isoformat(),
                        'level': 'error',
                        'message': msg,
                    })
            except Exception as e:
                logger.error(f"[{self.session_id}] 处理事件回调失败: {e}", exc_info=True)

        # 确保服务初始化
        if not self.scan_service or not self.scan_service.is_initialized:
            await self.initialize(event_callback=event_cb)

        # 重置缓存
        self.status = 'scanning'
        self.progress = {'current': 0, 'total': len(text), 'percentage': 0}
        self.results = []
        self.logs = []
        self.summary = {}

        # 启动异步扫描任务
        async def run():
            try:
                await self.scan_service.scan_text(text, event_cb)
                # 如果扫描流程未显式发出 completed（极少数异常分支），这里兜底
                if self.status not in ('completed', 'error', 'canceled'):
                    self.status = 'completed'
            except asyncio.CancelledError:
                self.status = 'canceled'
            except Exception as e:
                logger.error(f"[{self.session_id}] 扫描任务内部异常: {e}", exc_info=True)
                self.status = 'error'

        self.scan_task = asyncio.create_task(run())

    def get_scan_status(self) -> Dict[str, Any]:
        return {
            'status': self.status,
            'current': self.progress.get('current', 0),
            'total': self.progress.get('total', 0),
            'percentage': self.progress.get('percentage', 0)
        }

    def get_scan_results(self) -> Dict[str, Any]:
        # 去重（按 start_pos, end_pos, text）
        unique = {}
        for r in self.results:
            key = (int(r.get('start_pos', -1)), int(r.get('end_pos', -1)), str(r.get('text', '')))
            if key not in unique:
                unique[key] = r
        deduped_results = list(unique.values())
        return {
            'results': deduped_results,
            'api_calls': self.summary.get('api_calls', 0),
            'elapsed_time': self.summary.get('elapsed_time', 0),
            'unknown_status_codes': self.summary.get('unknown_status_codes', [])
        }

class SessionManager:
    """管理所有活动的 ScanSession"""

    def __init__(self):
        self.sessions: Dict[str, ScanSession] = {}
        self.config_manager = get_config_manager()

    async def create_session(self, runtime_overrides: Optional[Dict] = None) -> str:
        """
        创建一个新的扫描会话

        Args:
            runtime_overrides: 来自 API 请求的运行时配置覆盖

        Returns:
            新的会话 ID
        """
        session_id = str(uuid.uuid4())
        logger.info(f"[{session_id}] Creating new session...")

        try:
            # 加载配置，应用运行时覆盖
            final_config = await self.config_manager.load(runtime_overrides)
            
            # 规范化配置字段（统一处理别名和类型转换）
            final_config = ConfigNormalizer.normalize(final_config, session_id)
            
            # 验证必需字段
            if not ConfigNormalizer.validate_preset_fields(final_config, session_id):
                raise ValueError("配置缺少必需字段")
            
            logger.debug(f"[{session_id}] 配置规范化完成")
            logger.debug(f"[{session_id}] 配置字段映射信息: {ConfigNormalizer.get_field_mapping_info()}")
            
            preset = Preset(**final_config)

            session = ScanSession(session_id=session_id, preset=preset)
            await session.initialize()

            self.sessions[session_id] = session
            logger.info(f"[{session_id}] Session created successfully. Total sessions: {len(self.sessions)}.")
            return session_id
        except Exception as e:
            logger.error(f"[{session_id}] Failed to create session: {e}", exc_info=True)
            raise

    async def delete_session(self, session_id: str):
        """删除一个会话并清理其资源"""
        session = self.sessions.pop(session_id, None)
        if session:
            await session.close()
            logger.info(f"[{session_id}] Session deleted. Total sessions: {len(self.sessions)}.")
        else:
            logger.warning(f"Attempted to delete non-existent session: {session_id}")

    def get_session(self, session_id: str) -> Optional[ScanSession]:
        """通过 ID 获取一个活动的会话"""
        return self.sessions.get(session_id)

    def list_sessions(self) -> Dict[str, Dict]:
        """列出所有活动会话的信息"""
        return {sid: sess.get_info() for sid, sess in self.sessions.items()}

    async def cleanup(self):
        """清理所有会话"""
        logger.info(f"Cleaning up all {len(self.sessions)} sessions...")
        for session_id in list(self.sessions.keys()):
            await self.delete_session(session_id)
        logger.info("All sessions cleaned up.")

# 全局单例管理器
_session_manager: Optional[SessionManager] = None

def get_session_manager() -> SessionManager:
    """获取全局 SessionManager 单例"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
