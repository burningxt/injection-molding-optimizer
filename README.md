# 注塑成型工艺参数智能推荐系统

基于贝叶斯优化（Bayesian Optimization）的注塑成型工艺参数智能推荐系统，支持 Web 界面和命令行两种使用方式。

## 功能特性

- **智能优化**：基于 BoTorch 实现贝叶斯优化，自动推荐最优工艺参数
- **人机协同**：支持 Human-in-the-loop 模式，结合专家经验与算法推荐
- **实时通信**：WebSocket 实现实时日志推送和会话状态同步
- **数据管理**：Excel 导入导出，历史记录编辑与回退
- **多件号支持**：独立的件号配置管理，支持不同产品工艺优化
- **模拟模式**：支持自动模拟计算，便于测试和演示

## 技术栈

- **后端**：Python 3.10+, FastAPI, WebSocket
- **优化引擎**：PyTorch, BoTorch (贝叶斯优化)
- **数据处理**：pandas, openpyxl
- **前端**：原生 JavaScript, AG Grid, ECharts
- **部署**：Uvicorn ASGI 服务器

## 快速开始

### 安装

```bash
# 克隆仓库
git clone <repository-url>
cd InjectionMolding

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -e .
```

### Web 界面（推荐）

```bash
# 启动 Web 服务器
uvicorn injection_molding.interfaces.web:app --host 0.0.0.0 --port 8000

# 浏览器访问
open http://localhost:8000
```

### 命令行

```bash
# 运行优化
python -m injection_molding --config configs/parts/LS39860A-903.json --n-init 10 --n-iter 20
```

## 项目结构

```
├── src/injection_molding/      # 核心 Python 包
│   ├── core/                   # 算法层
│   │   ├── bayesian/           # 贝叶斯优化实现
│   │   ├── fitness.py          # 适应度计算
│   │   ├── simulation.py       # 仿真测试
│   │   └── runner.py           # 实验运行器
│   ├── domain/                 # 领域层
│   │   ├── config.py           # 配置管理
│   │   └── models.py           # 数据模型
│   ├── infrastructure/         # 基础设施
│   │   ├── utils.py            # 工具函数
│   │   └── cuda.py             # CUDA 支持
│   ├── interfaces/             # 接口层
│   │   ├── cli.py              # 命令行接口
│   │   └── web/                # Web API
│   │       ├── main.py         # FastAPI 主应用
│   │       └── services/       # 服务层
│   └── agents/                 # Agent 层（预留）
├── web/                        # Web 前端
│   ├── index.html
│   └── static/
│       ├── css/style.css
│       └── js/app.js
├── configs/parts/              # 件号配置
├── data/                       # 数据文件
│   ├── records/                # 实验记录
│   ├── checkpoints/            # 优化检查点
│   └── templates/              # 模板文件
└── tests/                      # 测试
```

## 配置说明

### 件号配置

件号配置文件存放于 `configs/parts/` 目录，JSON 格式：

```json
{
  "part_number": "LS39860A-903",
  "description": "产品描述",
  "parameters": {
    "melt_temp": {
      "type": "range",
      "bounds": [180, 220],
      "unit": "°C"
    },
    "injection_speed": {
      "type": "range",
      "bounds": [50, 150],
      "unit": "mm/s"
    }
  }
}
```

### 参数类型

- `fixed`: 固定值，不参与优化
- `range`: 连续范围，优化时在此区间内搜索
- `set`: 离散集合，从指定选项中选择

## 使用指南

### Web 界面操作

1. **选择件号**：从下拉框选择或新建件号配置
2. **算法设置**：
   - 初始数据数量：建议 10-20
   - 批次数：建议 10-20
   - 批次大小：建议 2-4
3. **开始寻优**：点击"开始寻优"按钮
4. **输入结果**：在机台试模后输入面型评价指标
5. **保存退出**：可随时保存进度，下次继续

### 历史记录编辑

- **双击单元格**：编辑历史记录
- **删除行**：选择行后点击"删除行"可回退到该状态
- **自动截断**：保存后会自动截断更晚批次并重启优化

## 开发

### 运行测试

```bash
pytest tests/
```

### 代码规范

```bash
# 类型检查
mypy src/

# 代码格式化
black src/ tests/
isort src/ tests/
```

## 路线图

- [x] 核心贝叶斯优化算法
- [x] Web 界面基础功能
- [x] Human-in-the-loop 支持
- [ ] Agent 智能辅助（参数解释、异常诊断）
- [ ] 收敛曲线可视化
- [ ] 多目标优化支持
- [ ] 跨件号知识迁移

## 许可证

MIT License

## 致谢

- [BoTorch](https://botorch.org/) - 贝叶斯优化库
- [FastAPI](https://fastapi.tiangolo.com/) - Web 框架
