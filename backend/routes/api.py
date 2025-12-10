"""
API 路由模块

本模块定义了所有与后端交互的 RESTful API 端点。
这些端点通过 FastAPI 的 APIRouter 进行组织，并被主应用 (`app.py`) 统一注册。

主要功能包括：
- **配置管理**: 获取和保存 API 凭证、扫描规则预设和高级设置。
- **会话管理**: 创建、查询和删除扫描会话。
- **扫描控制**: 发起扫描、查询状态、获取结果、取消扫描。
- **系统工具**: 提供 API 凭证验证和健康检查功能。
"""
from fastapi import APIRouter, HTTPException, Depends
from utils.response import success_response, raise_http_error
from typing import Dict, Any
import logging
from datetime import datetime, timezone

from core.config_manager import get_config_manager, ConfigManager
from services.scan_service import ScanService, get_scan_service
from models.request import ScanRequest, VerifyRequest
from handlers.session_manager import get_session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# --- 配置端点 ---

@router.get("/api_config", summary="获取 API 配置", tags=["Configuration"])
async def get_api_config():
    """获取当前存储的 API 凭证信息。"""
    try:
        config_manager = get_config_manager()
        credentials = await config_manager.load_credentials()
        return success_response(data=credentials, message="API 配置加载成功")
    except Exception as e:
        raise_http_error(message=f"加载 API 配置失败: {e}", status_code=500)

@router.post("/api_config", summary="保存 API 配置", tags=["Configuration"])
async def save_api_config(updates: Dict[str, Any]):
    """保存或更新 API 凭证信息。"""
    try:
        config_manager = get_config_manager()
        result = await config_manager.save_credentials(updates)
        return success_response(data=result, message="API 配置保存成功")
    except ValueError as e:
        raise_http_error(message=str(e), status_code=400)
    except Exception as e:
        raise_http_error(message=f"保存 API 配置失败: {e}", status_code=500)

@router.get("/presets_config", summary="获取预设配置", tags=["Configuration"])
async def get_presets_config():
    """获取所有与扫描规则相关的配置，包括可用预设和自定义规则。"""
    try:
        config_manager = get_config_manager()
        available_presets = await config_manager.load_presets_list()
        custom_rules = await config_manager.load_rules('custom')
        # 注意：此处不再加载 settings 来获取当前预设，因为这会导致死锁
        # 当前激活的预设由 settings_config 接口提供
        data = {"available_presets": available_presets, "custom_rules": custom_rules}
        return success_response(data=data, message="预设配置加载成功")
    except Exception as e:
        raise_http_error(message=f"加载预设配置失败: {e}", status_code=500)

@router.post("/presets_config", summary="保存预设配置", tags=["Configuration"])
async def save_presets_config(updates: Dict[str, Any]):
    """保存或更新自定义扫描规则。"""
    try:
        config_manager = get_config_manager()
        result = await config_manager.save_rules('custom', updates)
        return success_response(data=result, message="预设配置保存成功")
    except Exception as e:
        raise_http_error(message=f"保存预设配置失败: {e}", status_code=500)

@router.get("/settings_config", summary="获取高级设置", tags=["Configuration"])
async def get_settings_config():
    """获取应用的高级设置，如并发数、算法参数等。"""
    try:
        config_manager = get_config_manager()
        settings = await config_manager.load_settings()
        return success_response(data=settings, message="高级设置加载成功")
    except Exception as e:
        raise_http_error(message=f"加载高级设置失败: {e}", status_code=500)

@router.post("/settings_config", summary="保存高级设置", tags=["Configuration"])
async def save_settings_config(updates: Dict[str, Any]):
    """保存或更新应用的高级设置。"""
    try:
        config_manager = get_config_manager()
        result = await config_manager.save_settings(updates)
        return success_response(data=result, message="高级设置保存成功")
    except ValueError as e:
        raise_http_error(message=str(e), status_code=400)
    except Exception as e:
        raise_http_error(message=f"保存高级设置失败: {e}", status_code=500)

# --- 扫描与验证端点 ---

@router.post("/scan/{session_id}/start", summary="开始扫描(HTTP)", tags=["Scan"])
async def start_scan(session_id: str, payload: Dict[str, Any]):
    """以 HTTP 方式发起一次扫描（简化集成，无需 WebSocket）。"""
    text = (payload or {}).get('text')
    if not text or not isinstance(text, str):
        raise_http_error(message="请求体需要提供非空的 text 字段", status_code=400)

    session_manager = get_session_manager()
    session = session_manager.get_session(session_id)
    if not session or not session.scan_service:
        raise_http_error(message="会话未找到或扫描服务未初始化", status_code=404)

    try:
        await session.start_scan(text)
        return success_response(message="扫描已启动")
    except RuntimeError as e:
        raise_http_error(message=str(e), status_code=409)
    except Exception as e:
        logger.error(f"[{session_id}] 启动扫描时出错: {e}", exc_info=True)
        raise_http_error(message=f"启动扫描时出错: {e}", status_code=500)

@router.get("/scan/{session_id}/status", summary="查询扫描状态(HTTP)", tags=["Scan"])
async def get_scan_status(session_id: str):
    session_manager = get_session_manager()
    session = session_manager.get_session(session_id)
    if not session:
        raise_http_error(message="会话未找到", status_code=404)

    try:
        status = session.get_scan_status()
        return success_response(data=status, message="状态获取成功")
    except Exception as e:
        raise_http_error(message=f"获取状态失败: {e}", status_code=500)

@router.get("/scan/{session_id}/results", summary="获取扫描结果(HTTP)", tags=["Scan"])
async def get_scan_results(session_id: str):
    session_manager = get_session_manager()
    session = session_manager.get_session(session_id)
    if not session:
        raise_http_error(message="会话未找到", status_code=404)

    try:
        results = session.get_scan_results()
        return success_response(data=results, message="结果获取成功")
    except Exception as e:
        raise_http_error(message=f"获取结果失败: {e}", status_code=500)

@router.post("/scan/{session_id}/cancel", summary="取消扫描", tags=["Scan"])
async def cancel_scan(session_id: str):
    """请求取消一个正在进行中的扫描任务。这是一个异步操作，发送停止信号后，扫描不会立即中止，而是在下一个检查点安全退出。"""
    session_manager = get_session_manager()
    session = session_manager.get_session(session_id)
    if not session or not session.scan_service:
        raise_http_error(message="会话未找到或扫描服务未初始化", status_code=404)
    
    try:
        await session.scan_service.stop_scan()
        return success_response(message="扫描停止信号已发送")
    except Exception as e:
        logger.error(f"[{session_id}] 停止扫描时出错: {e}", exc_info=True)
        raise_http_error(message=f"停止扫描时出错: {e}", status_code=500)


# --- 会话管理端点 ---

@router.post("/session/create", summary="创建扫描会话", tags=["Session"])
async def create_session(runtime_overrides: Dict[str, Any] = None):
    """
    创建一个新的扫描会话实例。

    会话是执行一次完整扫描的隔离环境，包含了独立的配置和状态。
    成功创建后，返回的 `session_id` 必须用于后续的所有 WebSocket 通信和 API 请求。

    Args:
        runtime_overrides: 可选的运行时配置覆盖，用于本次会话临时替换全局设置。

    Returns:
        包含新创建的 `session_id` 的 JSON 对象。
    """
    try:
        session_manager = get_session_manager()
        session_id = await session_manager.create_session(runtime_overrides=runtime_overrides)
        logger.info(f"[API] 会话创建成功: {session_id}")
        return success_response(data={"session_id": session_id}, message="会话创建成功")
    except Exception as e:
        logger.error(f"[API] 会话创建失败: {e}", exc_info=True)
        raise_http_error(message=f"会话创建失败: {str(e)}", status_code=500)

@router.get("/session/{session_id}", summary="获取会话信息", tags=["Session"])
async def get_session_info(session_id: str):
    """获取指定会话的详细信息，包括其配置和当前状态。"""
    try:
        session_manager = get_session_manager()
        session = session_manager.get_session(session_id)
        if not session:
            raise_http_error(message="会话不存在", status_code=404)
        return success_response(data=session.get_info(), message="会话信息获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] 获取会话信息失败: {e}", exc_info=True)
        raise_http_error(message=str(e), status_code=500)

@router.delete("/session/{session_id}", summary="删除会话", tags=["Session"])
async def delete_session(session_id: str):
    """删除一个指定的会话，并清理其占用的所有资源。"""
    try:
        session_manager = get_session_manager()
        await session_manager.delete_session(session_id)
        logger.info(f"[API] 会话已删除: {session_id}")
        return success_response(message="会话已删除")
    except Exception as e:
        logger.error(f"[API] 删除会话失败: {e}", exc_info=True)
        raise_http_error(message=str(e), status_code=500)

# --- 验证端点 ---

@router.post("/verify", summary="验证 API 凭证", tags=["Verification"])
async def verify_credentials(request: VerifyRequest, scan_service: ScanService = Depends(get_scan_service)):
    """
    验证给定的 API 凭证是否有效。

    此端点用于在保存配置前，测试 API URL、密钥和模型名称是否能成功访问大语言模型服务。
    它会发送一个最小化的测试请求，并返回 API 的响应，以便前端可以展示连接状态。
    """
    try:
        result = await scan_service.verify_credentials(api_url=request.api_url, api_key=request.api_key, model=request.model)
        return success_response(data=result, message="API 凭证验证成功")
    except Exception as e:
        raise_http_error(message=f"API 凭证验证失败: {e}", status_code=500)

@router.get("/health", summary="健康检查", tags=["System"])
async def health_check():
    """提供一个简单的健康检查端点，用于确认后端服务是否正在运行。"""
    health_data = {
        "status": "healthy",
        "version": "1.0.0",  # 以后可以从配置中读取
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    return success_response(data=health_data, message="服务运行正常")
