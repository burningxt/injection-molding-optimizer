"""优化会话管理器"""

import asyncio
import json
import pickle
import uuid
from typing import Dict, Optional, List, Any
from datetime import datetime
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

from ..core.config import settings
from ..models.schemas import (
    OptimizationState,
    WSMessage,
    WSMessageType,
    LogMessageData,
)


class OptimizationSession:
    """单个优化会话"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state: Optional[OptimizationState] = None
        self.websocket: Optional[WebSocket] = None
        self.is_running = False
        self._stop_event = asyncio.Event()
        self._log_queue: asyncio.Queue[str] = asyncio.Queue()
        self._input_future: Optional[asyncio.Future] = None

    async def connect(self, websocket: WebSocket):
        """连接 WebSocket"""
        self.websocket = websocket
        await self.send_message(WSMessageType.STATE_UPDATE, self._state_to_dict())

    async def disconnect(self):
        """断开连接"""
        if self.websocket:
            await self.websocket.close()
        self.websocket = None

    async def send_message(self, msg_type: WSMessageType, data: Optional[Dict] = None):
        """发送消息到客户端"""
        if self.websocket:
            message = WSMessage(type=msg_type, data=data)
            await self.websocket.send_json(message.model_dump(mode="json"))

    async def send_log(self, message: str, level: str = "info"):
        """发送日志消息"""
        await self.send_message(
            WSMessageType.LOG_MESSAGE,
            LogMessageData(level=level, message=message).model_dump()
        )

    def request_input(self, prompt: str, current_sample: Dict[str, Any]) -> asyncio.Future:
        """请求用户输入，返回 Future"""
        self._input_future = asyncio.get_event_loop().create_future()

        # 发送请求到前端
        asyncio.create_task(self.send_message(
            WSMessageType.PARAMS_READY,
            {"prompt": prompt, "current_sample": current_sample}
        ))

        return self._input_future

    def submit_input(self, form_error: float, is_shrink: bool):
        """提交用户输入"""
        if self._input_future and not self._input_future.done():
            self._input_future.set_result({
                "form_error": form_error,
                "is_shrink": is_shrink
            })

    def stop(self):
        """停止优化"""
        self.is_running = False
        self._stop_event.set()
        if self._input_future and not self._input_future.done():
            self._input_future.cancel()

    def _state_to_dict(self) -> Dict[str, Any]:
        """转换状态为字典"""
        if self.state:
            return self.state.model_dump(mode="json")
        return {}

    async def save_checkpoint(self):
        """保存检查点"""
        if not self.state:
            return

        checkpoint_path = settings.CHECKPOINT_DIR / f"{self.session_id}.pkl"
        self.state.updated_at = datetime.now()

        with open(checkpoint_path, "wb") as f:
            pickle.dump(self.state, f)

        await self.send_log(f"Checkpoint saved: {checkpoint_path.name}")

    @classmethod
    async def load_checkpoint(cls, session_id: str) -> Optional["OptimizationSession"]:
        """加载检查点"""
        checkpoint_path = settings.CHECKPOINT_DIR / f"{session_id}.pkl"

        if not checkpoint_path.exists():
            return None

        session = cls(session_id)
        with open(checkpoint_path, "rb") as f:
            session.state = pickle.load(f)

        return session


class SessionManager:
    """会话管理器（单例）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.sessions: Dict[str, OptimizationSession] = {}
        return cls._instance

    def create_session(self) -> OptimizationSession:
        """创建新会话"""
        session_id = str(uuid.uuid4())[:8]
        session = OptimizationSession(session_id)
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[OptimizationSession]:
        """获取会话"""
        return self.sessions.get(session_id)

    async def remove_session(self, session_id: str):
        """移除会话"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            await session.save_checkpoint()
            await session.disconnect()
            del self.sessions[session_id]

    async def cleanup_inactive_sessions(self, max_inactive_minutes: int = 30):
        """清理不活跃会话"""
        now = datetime.now()
        to_remove = []

        for session_id, session in self.sessions.items():
            if not session.websocket:
                # 检查最后更新时间
                if session.state:
                    inactive_time = (now - session.state.updated_at).total_seconds() / 60
                    if inactive_time > max_inactive_minutes:
                        to_remove.append(session_id)

        for session_id in to_remove:
            await self.remove_session(session_id)


# 全局会话管理器实例
session_manager = SessionManager()
