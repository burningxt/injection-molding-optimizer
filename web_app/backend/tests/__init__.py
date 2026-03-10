"""
注塑成型优化系统 - 测试套件

该包包含完整的自动化测试套件，覆盖以下功能：
- 会话管理
- 优化流程
- 数据提交
- 安全边界
- 回退机制
- 保存退出
- 异常处理
- 集成测试
"""

__version__ = "1.0.0"
__all__ = [
    "OptimizationTestClient",
    "TEST_PART_CONFIG",
    "TEST_ALGO_SETTINGS",
]

from .test_client import OptimizationTestClient, TEST_PART_CONFIG, TEST_ALGO_SETTINGS
