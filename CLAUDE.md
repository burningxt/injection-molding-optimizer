# 注塑成型工艺参数智能推荐系统

## 项目简介

基于贝叶斯优化（Bayesian Optimization）的注塑成型工艺参数智能推荐系统。

## 技术栈

- Python 3.12
- PyTorch + BoTorch (贝叶斯优化)
- tkinter (GUI)
- pandas + openpyxl (数据处理)

## 项目结构

```
├── main.py              # 主程序入口
├── gui_main.py          # GUI 界面
├── config.py            # 配置管理
├── runner.py            # 优化运行器
├── optimizer_*.py       # 优化器实现
├── fitness_*.py         # 适应度计算
├── utils.py             # 工具函数
├── configs/             # 件号配置文件
├── output/              # 输出目录
└── requirements.txt     # 依赖列表
```

## 常用命令

```bash
# 激活虚拟环境
source .venv/bin/activate

# 运行 GUI
uv python gui_main.py

# 运行命令行版本
uv python main.py --help
```

## 依赖管理

使用 uv 管理依赖：

```bash
uv pip install -r requirements.txt
uv add package_name
```

## 配置说明

- 件号配置文件存放于 `configs/` 目录
- 历史记录保存于 `output/experiment_records.xlsx`
