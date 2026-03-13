"""FastAPI 主应用"""

import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, Form, BackgroundTasks

# 加载 .env 文件
load_dotenv()
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .services.session_manager import session_manager, OptimizationSession
from .services.async_runner import AsyncExperimentRunner
from ...domain.models import (
    PartConfig,
    AlgoSettings,
    WSMessageType,
    OptimizationState,
    ExperimentRecord,
    SensitivityAnalysis,
)

# 设置
from pathlib import Path

class Settings:
    # 基础路径配置
    CHECKPOINT_DIR = Path("data/checkpoints")
    CONFIGS_DIR = Path("configs/parts")
    RECORDS_FILE = Path("data/records/experiment_records.xlsx")
    STATIC_DIR = Path("web")
    OUTPUT_DIR = Path("data/records")

    # 服务器配置
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))

    # LLM 配置（支持 Deepseek 和其他提供商）
    # 优先读取 DEEPSEEK_* 变量，其次读取 LLM_* 变量
    LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("DEEPSEEK_MODEL") or os.getenv("LLM_MODEL", "deepseek-chat")
    LLM_BASE_URL = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))

settings = Settings()


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
    """根路径 - 返回前端页面"""
    from fastapi.responses import FileResponse
    index_path = settings.STATIC_DIR / "index.html"
    if not index_path.exists():
        return {"error": "前端页面不存在", "path": str(index_path)}
    return FileResponse(index_path)


@app.get("/api")
async def api_info():
    """API 信息"""
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


@app.post("/api/parts/create")
async def create_part(request: dict):
    """创建新件号"""
    import json
    import re

    part_number = request.get("part_number", "").strip()
    config = request.get("config", {})

    if not part_number:
        return {"error": "件号名称不能为空"}

    # 验证件号名称格式
    if not re.match(r'^[a-zA-Z0-9_-]+$', part_number):
        return {"error": "件号名称格式无效，只能包含字母、数字、下划线和连字符"}

    config_path = settings.CONFIGS_DIR / f"{part_number}.json"

    # 检查是否已存在
    if config_path.exists():
        return {"error": "该件号已存在"}

    try:
        # 确保配置包含必要字段
        clean_config = {
            "name": part_number,
            "fixed": config.get("fixed", {}),
            "tunable": config.get("tunable", [])
        }

        # 保存配置
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(clean_config, f, ensure_ascii=False, indent=2)

        return {"success": True, "message": f"件号 {part_number} 创建成功"}
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


@app.post("/api/upload-init-data")
async def upload_init_data(file: UploadFile = None, session_id: str = Form("")):
    """上传初始数据文件"""
    import pandas as pd
    import io

    if not file:
        return {"error": "未提供文件"}

    try:
        # 读取上传的文件
        content = await file.read()

        # 根据文件扩展名选择读取方式
        filename = file.filename.lower()
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        elif filename.endswith('.xlsx') or filename.endswith('.xls'):
            df = pd.read_excel(io.BytesIO(content))
        else:
            return {"error": "不支持的文件格式，请上传CSV或Excel文件"}

        # 保存到初始数据文件
        init_data_path = settings.OUTPUT_DIR / f"init_data_{session_id or 'default'}.xlsx"
        df.to_excel(init_data_path, index=False)

        return {
            "success": True,
            "message": f"成功上传文件",
            "record_count": len(df),
            "columns": list(df.columns),
            "file_path": str(init_data_path)
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


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


@app.post("/api/parts/{part_number}/config")
async def save_part_config(part_number: str, request: dict):
    """保存件号配置"""
    import json
    import shutil
    from datetime import datetime

    try:
        config_path = settings.CONFIGS_DIR / f"{part_number}.json"

        # 备份原配置
        if config_path.exists():
            backup_path = settings.CONFIGS_DIR / f"{part_number}.json.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            shutil.copy2(config_path, backup_path)

        # 验证配置格式
        if "tunable" not in request:
            return {"error": "配置格式错误：缺少tunable字段"}

        # 清理配置数据
        clean_config = {
            "name": request.get("name", part_number),
            "fixed": request.get("fixed", {}),
            "tunable": []
        }

        for param in request.get("tunable", []):
            clean_param = {
                "name": param.get("name", ""),
                "type": param.get("type", "range")
            }

            if clean_param["type"] == "fixed":
                clean_param["value"] = float(param.get("value", 0))
            elif clean_param["type"] == "range":
                clean_param["min"] = float(param.get("min", 0))
                clean_param["max"] = float(param.get("max", 100))
                clean_param["step"] = float(param.get("step", 1))
            elif clean_param["type"] == "set":
                clean_param["values"] = [float(v) for v in param.get("values", []) if v is not None]

            # 保留targets字段（如果有）
            if "targets" in param:
                clean_param["targets"] = param["targets"]

            clean_config["tunable"].append(clean_param)

        # 保存新配置
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(clean_config, f, ensure_ascii=False, indent=2)

        return {"success": True, "message": "配置已保存"}
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


@app.post("/api/records/{session_id}/save")
async def save_records(session_id: str, request: dict):
    """保存修改后的实验记录"""
    import pandas as pd

    session = session_manager.get_session(session_id)
    if not session:
        return {"error": "会话不存在"}

    records_data = request.get("records", [])
    if not records_data:
        return {"error": "没有记录需要保存"}

    try:
        # 关键修复：更新 session 的状态
        if session.state:
            # 将前端传来的记录数据转换为 ExperimentRecord 对象
            updated_records = []
            for rec in records_data:
                record = ExperimentRecord(
                    stage=str(rec.get("stage", "")),
                    form_error=rec.get("form_error") if rec.get("form_error") not in [None, ""] else None,
                    is_shrink=rec.get("is_shrink") in [True, "是", "true", "True"],
                    params=rec.get("params", {})
                )
                updated_records.append(record)

            # 更新 session 的记录
            session.state.all_records = updated_records

            # 简化：不重新计算 X_train/y_train，这些在优化启动时会自动重建
            # 只清除它们，让优化器重新计算
            session.state.X_train = []
            session.state.y_train = []

            # 处理回退逻辑
            rollback_to_stage = request.get("rollback_to_stage")
            if rollback_to_stage and session.state:
                # 计算回退后的 iteration
                if rollback_to_stage == "init":
                    new_iteration = 0
                elif rollback_to_stage.startswith("iter_"):
                    try:
                        new_iteration = int(rollback_to_stage.split("_")[1])
                    except (ValueError, IndexError):
                        new_iteration = 0
                else:
                    new_iteration = 0

                old_iteration = session.state.iteration
                session.state.iteration = new_iteration

                # 清除安全边界（因为回退后数据可能不准确）
                session.state.Ph_min_safe = {}

                await session.send_log(f"回退到 {rollback_to_stage}，重置迭代计数: {old_iteration} -> {new_iteration}")

            # 保存 checkpoint
            await session.save_checkpoint()
            await session.send_log(f"已更新 {len(updated_records)} 条记录")
            print(f"[save_records] 成功更新 {len(updated_records)} 条记录到 session {session_id}")

        # 保存到Excel（用于导出）
        df_records = []
        for rec in records_data:
            row = {
                "阶段": str(rec.get("stage", "")),
                "面型评价指标": rec.get("form_error") if rec.get("form_error") not in [None, ""] else "",
                "是否缩水": "是" if rec.get("is_shrink") in [True, "是", "true"] else "否"
            }
            # 添加参数列
            params = rec.get("params", {})
            for key, value in params.items():
                row[key] = value
            df_records.append(row)

        df = pd.DataFrame(df_records)
        output_path = settings.OUTPUT_DIR / "experiment_records.xlsx"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(output_path, index=False)

        return {"success": True, "message": f"已保存 {len(df_records)} 条记录并更新状态"}
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


@app.post("/api/session/{session_id}/clear")
async def clear_session(session_id: str):
    """清除会话（包括服务器端 checkpoint）"""
    import shutil

    # 从 session_manager 移除
    session = session_manager.get_session(session_id)
    if session:
        await session_manager.remove_session(session_id)

    # 删除 checkpoint 文件
    checkpoint_path = settings.CHECKPOINT_DIR / f"{session_id}.json"
    if checkpoint_path.exists():
        checkpoint_path.unlink()

    # 删除初始数据文件
    init_data_path = settings.OUTPUT_DIR / f"init_data_{session_id}.xlsx"
    if init_data_path.exists():
        init_data_path.unlink()

    return {"success": True, "message": "会话已清除"}


@app.post("/api/records/{session_id}/export")
async def export_records(session_id: str, request: dict, background_tasks: BackgroundTasks):
    """导出实验记录为Excel文件"""
    import pandas as pd
    from fastapi.responses import FileResponse
    import tempfile
    import os
    import time

    records_data = request.get("records", [])
    part_name = request.get("part_name", "unknown")

    if not records_data:
        return {"error": "没有记录需要导出"}

    try:
        # 转换记录为DataFrame
        df_records = []
        for rec in records_data:
            row = {
                "阶段": str(rec.get("stage", "")),
                "面型评价指标": rec.get("form_error") if rec.get("form_error") not in [None, ""] else "",
                "是否缩水": "是" if rec.get("is_shrink") in [True, "是", "true", "True"] else "否"
            }
            # 添加参数列
            params = rec.get("params", {})
            for key, value in params.items():
                row[key] = value
            df_records.append(row)

        df = pd.DataFrame(df_records)

        # 创建临时文件
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{part_name}_实验记录_{timestamp}.xlsx"

        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            df.to_excel(tmp.name, index=False, sheet_name='实验记录')
            tmp_path = tmp.name

        # 设置后台删除临时文件
        def cleanup():
            try:
                os.unlink(tmp_path)
            except:
                pass
        background_tasks.add_task(cleanup)

        # 返回文件
        response = FileResponse(
            tmp_path,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            filename=filename
        )
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'

        return response

    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


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
            # 关键修复：重置运行状态，允许继续优化
            session.is_running = False
        else:
            session = session_manager.create_session()
            # 告知客户端新的 session_id
            await websocket.send_json({
                "type": "session_created",
                "data": {"session_id": session.session_id}
            })
    else:
        # 已有会话，重置运行状态
        session.is_running = False

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

                # 关键修复：如果已有状态且有历史记录（从checkpoint加载），复用它；否则创建新状态
                if session.state and session.state.all_records and len(session.state.all_records) > 0:
                    # 从 checkpoint 恢复：更新配置但保留历史记录和进度
                    record_count = len(session.state.all_records)
                    pending_count = sum(1 for r in session.state.all_records if r.form_error is None)
                    await session.send_log(f"检测到 {record_count} 条历史记录（{pending_count} 条待完成），继续优化...")
                    session.state.part_config = part_config
                    session.state.algo_settings = algo_settings
                    # 保留：all_records, X_train, y_train, iteration, stage 等进度信息
                else:
                    # 新会话：创建新状态
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

            elif msg_type == WSMessageType.SAVE_AND_EXIT:
                # 保存并退出 - 温和地停止，不显示"取消"信息
                await session.send_log("正在保存并退出...", "info")
                session.stop(is_save_exit=True)
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
        if session.is_save_exit():
            await session.send_log("进度已保存，可以随时继续")
        else:
            await session.send_log("优化已停止")
    except Exception as e:
        await session.send_log(f"优化失败: {str(e)}", "error")
        import traceback
        await session.send_log(traceback.format_exc(), "error")
    finally:
        session.is_running = False
        await session.save_checkpoint()


@app.post("/api/explain/sensitivity")
async def explain_sensitivity(session_id: str) -> SensitivityAnalysis:
    """获取当前参数敏感性分析

    基于 GP 模型的核函数长度尺度，分析各参数对结果的影响程度。
    长度尺度越小，该参数越敏感（影响越大）。
    """
    import torch
    from botorch.models import SingleTaskGP
    from gpytorch.mlls import ExactMarginalLogLikelihood
    from botorch.fit import fit_gpytorch_mll

    from ...core.explainer import SensitivityAnalyzer

    # 获取会话
    session = session_manager.get_session(session_id)
    if not session:
        return SensitivityAnalysis(
            interpretation="会话不存在，无法进行分析",
            is_fallback=True,
            fallback_reason="session_not_found",
        )

    if not session.state:
        return SensitivityAnalysis(
            interpretation="会话状态不存在，请先开始优化",
            is_fallback=True,
            fallback_reason="no_state",
        )

    # 检查训练数据
    X_train_list = session.state.X_train
    y_train_list = session.state.y_train

    if len(X_train_list) < 5:
        return SensitivityAnalysis(
            interpretation=f"数据量不足（当前 {len(X_train_list)} 条），建议至少进行 5 轮实验后再查看敏感性分析",
            is_fallback=True,
            fallback_reason="insufficient_data",
        )

    try:
        # 转换为 tensor
        X_train = torch.tensor(X_train_list, dtype=torch.double)
        y_train = torch.tensor(y_train_list, dtype=torch.double).unsqueeze(-1)

        # 拟合 GP 模型（如果状态中没有保存）
        if session.state.bo_model_state:
            # TODO: 从状态恢复模型
            # 目前简化处理：重新拟合
            pass

        # 数据标准化（与 StandardBOOptimizer 保持一致）
        y_mean = y_train.mean()
        y_std = y_train.std() + 1e-6
        y_train_std = (y_train - y_mean) / y_std

        # 创建并拟合 GP 模型
        gp = SingleTaskGP(X_train, y_train_std)
        mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
        fit_gpytorch_mll(mll)

        # 获取参数名称
        param_names = session.state.param_names
        if not param_names and session.state.part_config:
            # 从配置中提取参数名称
            param_names = [p.name for p in session.state.part_config.tunable]

        # 创建分析器并分析
        analyzer = SensitivityAnalyzer(gp, param_names)
        result = analyzer.analyze()

        return result

    except Exception as e:
        import traceback
        print(f"[explain_sensitivity] Error: {e}")
        print(traceback.format_exc())
        return SensitivityAnalysis(
            interpretation=f"分析过程中出现错误: {str(e)}",
            is_fallback=True,
            fallback_reason=f"error: {str(e)}",
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
