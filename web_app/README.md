# 注塑成型工艺参数智能推荐系统 - Web 版

基于 FastAPI + WebSocket 的注塑工艺参数优化 Web 应用。

## 项目结构

```
web_app/
├── backend/
│   └── app/
│       ├── api/              # API 路由
│       ├── core/             # 核心配置
│       ├── models/           # Pydantic 模型
│       ├── services/         # 业务逻辑
│       │   ├── session_manager.py   # WebSocket 会话管理
│       │   └── async_runner.py      # 异步优化运行器
│       └── main.py           # FastAPI 主应用
├── frontend/
│   ├── index.html            # 主页面
│   ├── css/
│   │   └── style.css         # 样式
│   └── js/
│       └── app.js            # 前端逻辑
├── checkpoints/              # 检查点存储
├── pyproject.toml            # 项目配置
└── README.md
```

## 安装依赖

```bash
cd web_app

# 使用 uv 安装
uv pip install -e ".[dev]"

# 或使用 pip
pip install -e ".[dev]"
```

## 运行

### 1. 启动后端

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. 访问前端

打开浏览器访问: http://localhost:8000

## 功能特性

### 已实现

- ✅ WebSocket 实时通信
- ✅ 件号选择和配置加载
- ✅ 算法参数设置
- ✅ Human-in-the-loop 交互输入
- ✅ 实时日志显示
- ✅ 实验记录表格 (AG Grid)
- ✅ Checkpoint 自动保存
- ✅ 会话恢复

### 待实现

- 📋 历史记录编辑功能
- 📊 收敛曲线可视化
- 📁 Excel 文件导入/导出
- 🔐 用户认证
- 🐳 Docker 部署

## 与 tkinter 版本对比

| 功能 | tkinter | Web 版 |
|------|---------|--------|
| 启动方式 | `python gui_main.py` | 浏览器访问 |
| 实时日志 | ✅ 即时 | ✅ WebSocket 推送 |
| 表格编辑 | ✅ 双击编辑 | ⚠️ AG Grid |
| Excel 粘贴 | ✅ Ctrl+V | ⚠️ 需实现 |
| 远程访问 | ❌ 不支持 | ✅ 天然支持 |
| 多人协作 | ❌ 不支持 | ✅ 支持 |

## API 文档

启动后访问: http://localhost:8000/docs

### WebSocket 协议

**连接**: `ws://localhost:8000/ws/optimization/{session_id}`

**消息类型**:

| 类型 | 方向 | 说明 |
|------|------|------|
| `start_optimization` | C→S | 开始优化 |
| `stop_optimization` | C→S | 停止优化 |
| `submit_evaluation` | C→S | 提交评价 |
| `optimization_started` | S→C | 优化开始 |
| `params_ready` | S→C | 参数待测 |
| `log_message` | S→C | 日志消息 |
| `state_update` | S→C | 状态更新 |

## 开发计划

### Phase 1: 核心功能 ✅
- [x] FastAPI + WebSocket 基础架构
- [x] 会话管理和 Checkpoint
- [x] 异步优化流程
- [x] 前端基础界面

### Phase 2: 完善体验
- [ ] 历史记录编辑页面
- [ ] 收敛曲线图表
- [ ] 文件上传下载
- [ ] 响应式布局优化

### Phase 3: Agent 化
- [ ] LLM 参数解释
- [ ] 智能推荐建议
- [ ] 异常诊断 Agent

## 技术栈

- **Backend**: FastAPI, WebSocket, Uvicorn
- **Frontend**: Vanilla JS, AG Grid
- **ML**: PyTorch, BoTorch, GPyTorch
- **Data**: pandas, openpyxl

## License

MIT
