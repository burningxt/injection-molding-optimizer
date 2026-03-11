"""基础设施层

包含数据持久化、检查点管理、工具函数等基础设施。
"""

from .utils import setup_logger, get_resource_path

__all__ = ["setup_logger", "get_resource_path"]
