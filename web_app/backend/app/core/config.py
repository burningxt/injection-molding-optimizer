"""应用配置管理"""

import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""

    # 项目路径
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    CHECKPOINT_DIR: Path = BASE_DIR / "checkpoints"
    STATIC_DIR: Path = BASE_DIR.parent / "static"  # web_app/static
    CONFIGS_DIR: Path = Path("/home/xt/Code/InjectionMolding/configs")
    OUTPUT_DIR: Path = Path("/home/xt/Code/InjectionMolding/output")

    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # WebSocket 配置
    WS_HEARTBEAT_INTERVAL: int = 30  # 秒
    WS_TIMEOUT: int = 300  # 5分钟无消息自动断开

    # 优化默认配置
    DEFAULT_N_INIT: int = 20
    DEFAULT_N_ITER: int = 10
    DEFAULT_BATCH_SIZE: int = 4
    DEFAULT_SHRINK_THRESHOLD: float = 30.0

    class Config:
        env_file = ".env"


settings = Settings()

# 确保目录存在
settings.CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
