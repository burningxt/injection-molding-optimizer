"""FastAPI 主应用"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .services.session_manager import session_manager, OptimizationSession
from .services.async_runner import AsyncExperimentRunner
from .models.schemas import (
    PartConfig,
    AlgoSettings,
    WSMessageType,
    OptimizationState,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时：清理旧 checkpoint
    print("🚀 Starting Injection Molding Web App...")

    # 定期清理不活跃会话
    async def cleanup_task():
        while True:
            await asyncio.sleep(600)  # 每10分钟清理一次
            await session_manager.cleanup_inactive_sessions()

    cleanup_task = asyncio.create_task(cleanup_task())

    yield

    # 关闭时：保存所有会话
    print("🛑 Shutting down...")
    cleanup_task.cancel()
    for session_id in list(session_manager.sessions.keys()):
        await session_manager.remove_session(session_id)


app = FastAPI(
    title="注塑成型工艺参数智能推荐系统",
    description="基于贝叶斯优化的注塑工艺参数优化 Web 应用",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "注塑成型工艺参数智能推荐系统 API",
        "docs": "/docs",
        "websocket": "/ws/optimization/{session_id}",
    }


@app.get("/api/parts")
async def list_parts():
    """获取所有件号列表"""
    configs = []
    if settings.CONFIGS_DIR.exists():
        for f in settings.CONFIGS_DIR.glob("*.json"):
            configs.append(f.stem)
    return {"parts": sorted(configs)}


@app.get("/api/parts/{part_number}")
async def get_part_config(part_number: str):
    """获取件号配置"""
    import json

    config_path = settings.CONFIGS_DIR / f"{part_number}.json"
    if not config_path.exists():
        return {"error": "配置不存在"}

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    return config


@app.websocket("/ws/optimization/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket 优化会话"""
    await websocket.accept()

    # 获取或创建会话
    session = session_manager.get_session(session_id)
    if not session:
        # 尝试加载 checkpoint
        session = await OptimizationSession.load_checkpoint(session_id)
        if session:
            session_manager.sessions[session_id] = session
        else:
            session = session_manager.create_session()
            # 告知客户端新的 session_id
            await websocket.send_json({
                "type": "session_created",
                "data": {"session_id": session.session_id}
            })

    await session.connect(websocket)
    await session.send_log(f"已连接到会话: {session.session_id}")

    try:
        while True:
            # 接收消息
            data = await websocket.receive_json()
            msg_type = data.get("type")
            msg_data = data.get("data", {})

            if msg_type == WSMessageType.START_OPTIMIZATION:
                # 开始优化
                if session.is_running:
                    await session.send_log("优化已在运行中", "warning")
                    continue

                # 解析配置
                part_config = PartConfig(**msg_data.get("part_config", {}))
                algo_settings = AlgoSettings(**msg_data.get("algo_settings", {}))

                # 初始化状态
                session.state = OptimizationState(
                    session_id=session.session_id,
                    part_config=part_config,
                    algo_settings=algo_settings,
                )

                session.is_running = True
                await session.send_message(WSMessageType.OPTIMIZATION_STARTED)

                # 启动优化任务
                runner = AsyncExperimentRunner(
                    session=session,
                    part_config=part_config,
                    algo_settings=algo_settings,
                )

                # 异步运行
                asyncio.create_task(_run_optimization_safe(session, runner))

            elif msg_type == WSMessageType.STOP_OPTIMIZATION:
                # 停止优化
                session.stop()
                await session.send_message(WSMessageType.OPTIMIZATION_STOPPED)

            elif msg_type == WSMessageType.SUBMIT_EVALUATION:
                # 提交评价
                form_error = msg_data.get("form_error", 0)
                is_shrink = msg_data.get("is_shrink", False)
                session.submit_input(form_error, is_shrink)

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        print(f"WebSocket disconnected: {session_id}")
        await session.disconnect()
    except Exception as e:
        print(f"WebSocket error: {e}")
        await session.send_message(WSMessageType.ERROR, {"message": str(e)})
        await session.disconnect()


async def _run_optimization_safe(session: OptimizationSession, runner: AsyncExperimentRunner):
    """安全运行优化（捕获异常）"""
    try:
        await runner.run()
    except asyncio.CancelledError:
        await session.send_log("优化任务已取消")
    except Exception as e:
        await session.send_log(f"优化失败: {str(e)}", "error")
        import traceback
        await session.send_log(traceback.format_exc(), "error")
    finally:
        session.is_running = False
        await session.save_checkpoint()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
