import PyInstaller.__main__
import os

# 定义资源文件
# 格式: (源路径, 目标路径)
# 注意: 在 Windows 上使用分号 ; 分隔
datas = [
    ("configs", "configs"),
    ("bo_init_plan.xlsx", "."),
    ("代表值_S1均值+S2均值_T1-T19.xlsx", "."),
    ("初始数据19.xlsx", "."),
]

# 转换为 PyInstaller 格式
data_args = []
for src, dst in datas:
    if os.path.exists(src):
        data_args.extend(["--add-data", f"{src}{os.pathsep}{dst}"])

# 运行 PyInstaller
PyInstaller.__main__.run(
    [
        "gui_main.py",
        "--name",
        "IMOptimizer",
        "--onedir",  # 使用目录模式，更稳定且启动快
        "--windowed",  # GUI 程序，不显示控制台
        "--noconfirm",  # 覆盖现有 build/dist
        "--clean",  # 清理缓存
        *data_args,
        # 本地模块 (必须显式包含)
        "--hidden-import",
        "config",
        "--hidden-import",
        "utils",
        "--hidden-import",
        "main",
        "--hidden-import",
        "optimizer_standard",
        "--hidden-import",
        "runner",
        "--hidden-import",
        "fitness_calculate",
        "--hidden-import",
        "fitness_gui",
        # tkinter 必须显式包含
        "--hidden-import",
        "tkinter",
        "--hidden-import",
        "tkinter.ttk",
        "--hidden-import",
        "_tkinter",
        "--hidden-import",
        "tkinter.messagebox",
        "--hidden-import",
        "tkinter.filedialog",
        "--hidden-import",
        "tkinter.scrolledtext",
        "--hidden-import",
        "tkinter.simpledialog",
        # 核心依赖包
        "--hidden-import",
        "botorch",
        "--hidden-import",
        "gpytorch",
        "--hidden-import",
        "sklearn.utils._typedefs",
        "--hidden-import",
        "sklearn.utils._cython_blas",
        "--hidden-import",
        "sklearn.neighbors._partition_nodes",
        "--hidden-import",
        "pandas._libs.tslibs.np_datetime",
        "--hidden-import",
        "pandas._libs.tslibs.nattype",
        "--hidden-import",
        "numpy.core._dtype_ctypes",
        "--hidden-import",
        "numpy.random.common",
        "--hidden-import",
        "numpy.random.bounded_integers",
        "--hidden-import",
        "numpy.random.entropy",
        # unittest (torch 需要)
        "--hidden-import",
        "unittest",
        "--hidden-import",
        "unittest.mock",
        "--hidden-import",
        "unittest.suite",
        "--hidden-import",
        "unittest.case",
        # 排除测试模块
        "--exclude-module",
        "pytest",
        "--exclude-module",
        "doctest",
        "--exclude-module",
        "tkinter.test",
        "--exclude-module",
        "matplotlib.tests",
        # collect-all 配置
        "--collect-all",
        "tkinter",
        "--collect-all",
        "unittest",
        "--collect-all",
        "botorch",
        "--collect-all",
        "gpytorch",
        "--collect-all",
        "torch",
        # tkinter 主题数据文件（修复 GUI 显示问题）
        "--collect-data",
        "tkinter",
        # (tkinter 是标准库，无需 copy-metadata)
    ]
)
