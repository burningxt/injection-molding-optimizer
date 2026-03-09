"""
工具模块 - 包含日志、表格打印等辅助函数
"""

import logging
import sys
import os
from typing import List, Optional

def get_resource_path(relative_path):
    """ 获取资源的绝对路径，兼容开发环境和 PyInstaller 打包环境 """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 打包后的临时目录 (对于打包进去的资源)
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def get_app_path(relative_path=""):
    """ 获取程序运行目录的绝对路径，用于读写外部配置文件 """
    if hasattr(sys, 'frozen'):
        # exe 所在的目录
        base_path = os.path.dirname(sys.executable)
    else:
        # 脚本所在的目录
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# 全局 logger（在 main 里初始化）
logger = None


def log(msg: str = ""):
    """同时输出到终端和日志文件"""
    global logger
    if logger is None:
        print(msg)
    else:
        logger.info(msg)


def print_table(rows: List[List], headers: List[str], title: Optional[str] = None):
    """
    打印格式化的表格
    
    Args:
        rows: 数据行列表，每行是一个列表
        headers: 表头列表
        title: 表格标题（可选）
    """
    if title:
        log(f"\n{title}")
    if not rows:
        log("(无数据)")
        return

    str_rows = [[str(x) for x in row] for row in rows]
    str_headers = [str(h) for h in headers]

    n_col = len(headers)
    widths = [len(str_headers[j]) for j in range(n_col)]
    for row in str_rows:
        for j in range(n_col):
            widths[j] = max(widths[j], len(row[j]))

    header_line = " | ".join(h.ljust(widths[j]) for j, h in enumerate(str_headers))
    sep_line = "-+-".join("-" * widths[j] for j in range(n_col))
    log(header_line)
    log(sep_line)

    for row in str_rows:
        line = " | ".join(row[j].ljust(widths[j]) for j in range(n_col))
        log(line)


def setup_logger(log_path: str) -> logging.Logger:
    """
    设置日志记录器
    
    Args:
        log_path: 日志文件路径
        
    Returns:
        配置好的 logger 对象
    """
    global logger
    
    logger = logging.getLogger("bo_logger")
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    
    # 文件处理器
    fh = logging.FileHandler(log_path, encoding="utf-8")
    # 控制台处理器
    ch = logging.StreamHandler(sys.stdout)
    
    fmt = logging.Formatter("%(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger
