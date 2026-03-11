# 注塑成型工艺参数智能推荐系统

## 项目简介

基于贝叶斯优化（Bayesian Optimization）的注塑成型工艺参数智能推荐系统。

## 技术栈

- Python 3.10+
- PyTorch + BoTorch (贝叶斯优化)
- FastAPI + WebSocket (Web 服务)
- pandas + openpyxl (数据处理)

## 项目结构

```
├── src/injection_molding/    # 核心 Python 包
│   ├── core/                 # 算法层（贝叶斯优化、适应度计算）
│   ├── domain/               # 领域层（配置、模型）
│   ├── infrastructure/       # 基础设施（数据持久化）
│   ├── interfaces/           # 接口层
│   │   ├── cli.py            # 命令行接口
│   │   └── web/              # Web API
│   └── agents/               # Agent 层（预留）
├── web/                      # Web 前端
│   ├── index.html
│   ├── css/style.css
│   └── js/app.js
├── configs/parts/            # 件号配置
├── data/                     # 数据文件
│   ├── records/              # 实验记录
│   ├── checkpoints/          # 优化检查点
│   └── templates/            # 模板文件
└── tests/                    # 测试
    ├── unit/
    ├── integration/
    └── e2e/
```

## 安装

```bash
# 激活虚拟环境
source .venv/bin/activate

# 安装包（可编辑模式）
uv pip install -e .
```

## 使用方式

### Web 界面（推荐）

```bash
# 启动 Web 服务器
uvicorn injection_molding.interfaces.web:app --host 0.0.0.0 --port 8000

# 浏览器访问
http://localhost:8000
```

### 命令行

```bash
# 运行优化
python -m injection_molding --config configs/parts/LS39860A-903.json --n-init 10 --n-iter 20
```

## 依赖管理

使用 uv 管理依赖：

```bash
uv pip install -r requirements.txt
uv add package_name
```

## 配置说明

- 件号配置文件存放于 `configs/parts/` 目录
- 历史记录保存于 `data/records/experiment_records.xlsx`

## 开发路线图

1. **核心算法层**：贝叶斯优化、适应度计算
2. **Web 接口**：FastAPI + WebSocket 实时通信
3. **Agent 层**（预留）：工艺推荐 Agent、结果分析 Agent
