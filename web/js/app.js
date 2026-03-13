/**
 * 注塑成型工艺参数智能推荐系统 - 前端主应用
 */

// 参数中文名称映射（与 config.py 保持一致）
const PARAM_DISPLAY_NAMES = {
    "T": "模具温度",
    "Tc": "冷却时间",
    "F": "锁模力",
    "p_vp": "VP切换压力",
    "p_sw": "保压压力",
    "delay": "延时时间",
    "delay_time": "延时时间",
    "v1": "射速1",
    "v2": "射速2",
    "v3": "射速3",
    "v4": "射速4",
    "v5": "射速5",
    "t1": "保压时间1",
    "t2": "保压时间2",
    "t3": "保压时间3",
    "t4": "保压时间4",
    "Vg": "剪口速度",
    "G": "保压梯度",
    "t_pack": "保压时间",
};

class OptimizationApp {
    constructor() {
        this.ws = null;
        this.sessionId = localStorage.getItem('session_id') || null;
        this.partConfig = null;
        this.isRunning = false;
        this.recordsGrid = null;
        this.logEntries = [];

        // 缓存数据（用于标签页切换时不重复请求）
        this._sensitivityData = null;
        this._heatmapData = null;
        this._currentTab = 'convergence'; // 当前激活的标签页

        console.log(`[OptimizationApp] Loaded session_id from localStorage: ${this.sessionId}`);

        this.init();
    }

    /**
     * 智能格式化数值显示
     * - 整数显示为整数（如 100）
     * - 小数保留适当精度并去除末尾的0
     */
    formatNumber(value) {
        if (typeof value !== 'number') return value;
        // 如果是整数，显示整数
        if (Number.isInteger(value)) return value.toString();
        // 如果是小数，保留4位小数并去除末尾的0
        return parseFloat(value.toFixed(4)).toString();
    }

    init() {
        this.initUI();
        this.initWebSocket();
        this.initAGGrid();
        this.initResizableLayout();

        // 确保页面完全加载后再加载件号列表
        if (document.readyState === 'complete') {
            // 页面已完全加载，直接执行
            this.loadPartList();
        } else {
            // 等待页面完全加载（包括所有资源）
            window.addEventListener('load', () => {
                console.log('[init] Page fully loaded, loading part list...');
                this.loadPartList();
            });
        }

        // 心跳检测
        setInterval(() => this.checkConnection(), 30000);
    }

    /**
     * 重置输入区域状态
     * 在 WebSocket 连接成功或页面初始化时调用
     */
    resetInputSection() {
        // 重置为等待状态，隐藏表格、进度和表单
        document.getElementById('waitingPrompt').style.display = 'block';
        document.getElementById('batchParamsTable').style.display = 'none';
        document.getElementById('inputProgress').style.display = 'none';
        document.getElementById('inputForm').style.display = 'none';

        // 重置进度显示为默认值
        document.getElementById('currentGroupNum').textContent = '1';
        document.getElementById('totalGroups').textContent = '4';
    }

    initUI() {
        // 件号选择
        document.getElementById('partSelect').addEventListener('change', (e) => {
            this.loadPartConfig(e.target.value);
        });

        document.getElementById('refreshPartsBtn').addEventListener('click', () => {
            this.loadPartList();
        });

        document.getElementById('newPartBtn').addEventListener('click', () => {
            this.createNewPart();
        });

        // 控制按钮
        document.getElementById('startBtn').addEventListener('click', () => {
            this.startOptimization();
        });

        document.getElementById('saveExitBtn').addEventListener('click', () => {
            this.saveAndExit();
        });

        document.getElementById('resetBtn').addEventListener('click', () => {
            this.resetSession();
        });

        document.getElementById('clearLogBtn').addEventListener('click', () => {
            this.clearLog();
        });

        // 洞察面板标签页
        this.initInsightsTabs();

        // 导出记录
        document.getElementById('exportRecordsBtn')?.addEventListener('click', () => {
            this.exportRecords();
        });

        // 算法设置改变时保存状态
        ['nInit', 'nIter', 'batchSize', 'modeSelect'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('change', () => this.onStateChange());
        });

        // 初始数据模式切换
        const initSourceSelect = document.getElementById('initSource');
        if (initSourceSelect) {
            initSourceSelect.addEventListener('change', (e) => {
                const fileGroup = document.getElementById('initFileGroup');
                if (fileGroup) {
                    fileGroup.style.display = e.target.value === 'file' ? 'block' : 'none';
                }
                this.onStateChange();
            });
        }

        // 提交评价
        document.getElementById('submitBtn').addEventListener('click', () => {
            this.submitEvaluation();
        });

        // 回车提交
        document.getElementById('formErrorInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.submitEvaluation();
        });

        // 更新会话信息显示
        if (this.sessionId) {
            document.getElementById('sessionInfo').textContent = `Session: ${this.sessionId}`;
        }

        // 初始化记录表格编辑工具栏
        this.initRecordsToolbar();

        // 参数配置编辑开关
        this.initParamConfigEditor();

        // 初始化收敛曲线图表
        this.initConvergenceChart();

        // 加载保存的UI状态
        this.loadUIState();
    }

    initConvergenceChart() {
        // 初始化ECharts实例
        const chartDom = document.getElementById('convergenceChart');
        if (!chartDom || typeof echarts === 'undefined') return;

        this.convergenceChart = echarts.init(chartDom);

        // 绑定切换按钮
        document.getElementById('toggleChartBtn').addEventListener('click', () => {
            const chartSection = document.getElementById('chartSection');
            const btn = document.getElementById('toggleChartBtn');
            const isExpanded = chartSection.dataset.expanded !== 'false';

            if (isExpanded) {
                chartSection.querySelector('#convergenceChart').style.height = '0px';
                btn.textContent = '展开';
                chartSection.dataset.expanded = 'false';
            } else {
                chartSection.querySelector('#convergenceChart').style.height = '250px';
                btn.textContent = '收起';
                chartSection.dataset.expanded = 'true';
                this.convergenceChart.resize();
            }
        });

        // 窗口大小变化时重绘图表
        window.addEventListener('resize', () => {
            if (this.convergenceChart) {
                this.convergenceChart.resize();
            }
        });
    }

    initParamConfigEditor() {
        const editToggle = document.getElementById('editConfigToggle');
        const actionsPanel = document.getElementById('paramPanelActions');

        if (!editToggle) return;

        editToggle.addEventListener('change', (e) => {
            this.isEditingConfig = e.target.checked;
            actionsPanel.style.display = this.isEditingConfig ? 'flex' : 'none';
            this.renderParamList();
        });

        document.getElementById('saveConfigBtn').addEventListener('click', () => {
            this.savePartConfig();
        });

        document.getElementById('addParamBtn').addEventListener('click', () => {
            this.addNewParam();
        });

        // 参数绑定功能
        document.getElementById('linkParamsBtn').addEventListener('click', () => {
            this.showLinkParamsPanel();
        });
        document.getElementById('cancelLinkBtn').addEventListener('click', () => {
            this.hideLinkParamsPanel();
        });
        document.getElementById('confirmSyncLinkBtn').addEventListener('click', () => {
            this.confirmLinkParams('sync');
        });
        document.getElementById('confirmModeLinkBtn').addEventListener('click', () => {
            this.confirmLinkParams('mode');
        });

        // 参数类型切换时更新字段
        const typeSelect = document.getElementById('editParamType');
        if (typeSelect) {
            typeSelect.addEventListener('change', () => this.updateEditParamFields());
        }

        // 点击模态框外部关闭
        const modal = document.getElementById('paramEditModal');
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) this.closeParamModal();
            });
        }
    }

    showLinkParamsPanel() {
        const panel = document.getElementById('linkParamsPanel');
        const list = document.getElementById('linkParamsList');

        list.innerHTML = '';

        if (!this.partConfig || !this.partConfig.tunable) {
            alert('没有可绑定的参数');
            return;
        }

        this.partConfig.tunable.forEach((param, index) => {
            const div = document.createElement('div');
            div.className = 'link-param-item';
            div.innerHTML = `
                <input type="checkbox" id="link-param-${index}" value="${index}">
                <label for="link-param-${index}">${param.name} (${param.type})</label>
            `;
            list.appendChild(div);
        });

        panel.style.display = 'block';
    }

    hideLinkParamsPanel() {
        document.getElementById('linkParamsPanel').style.display = 'none';
    }

    confirmLinkParams(linkType) {
        const selectedIndices = [];
        const checkboxes = document.querySelectorAll('#linkParamsList input[type="checkbox"]:checked');

        checkboxes.forEach(cb => {
            selectedIndices.push(parseInt(cb.value));
        });

        if (selectedIndices.length < 2) {
            alert('请至少选择2个参数进行绑定');
            return;
        }

        const selectedParams = selectedIndices.map(i => this.partConfig.tunable[i]);
        const paramNames = selectedParams.map(p => p.name);

        if (linkType === 'sync') {
            // 同步数值绑定：创建一个绑定参数，targets指向多个参数
            const firstParam = selectedParams[0];
            const linkedParam = {
                name: `${paramNames.join('_')}_同步`,
                type: firstParam.type,
                targets: paramNames,
                ...this.extractParamValues(firstParam)
            };

            // 删除原有的参数
            selectedIndices.sort((a, b) => b - a).forEach(index => {
                this.partConfig.tunable.splice(index, 1);
            });

            this.partConfig.tunable.push(linkedParam);
            this.addLogEntry('info', `已创建同步绑定: ${linkedParam.name}`);
        } else {
            // 模式选择绑定
            const linkedParam = {
                name: `${paramNames.join('_')}_模式`,
                type: 'choice',
                targets: paramNames,
                options: []
            };

            selectedIndices.sort((a, b) => b - a).forEach(index => {
                this.partConfig.tunable.splice(index, 1);
            });

            this.partConfig.tunable.push(linkedParam);
            this.addLogEntry('info', `已创建模式绑定: ${linkedParam.name}`);
        }

        this.hideLinkParamsPanel();
        this.renderParamList();
    }

    extractParamValues(param) {
        if (param.type === 'fixed') {
            return { value: param.value };
        } else if (param.type === 'range') {
            return { min: param.min, max: param.max, step: param.step };
        } else if (param.type === 'set') {
            return { values: param.values };
        }
        return {};
    }

    initRecordsToolbar() {
        // 创建表格工具栏（在recordsGrid之前插入）
        const recordsSection = document.querySelector('.records-section');
        const toolbar = document.createElement('div');
        toolbar.className = 'records-toolbar';
        toolbar.innerHTML = `
            <span class="toolbar-title">实验记录</span>
            <div class="toolbar-actions">
                <button id="saveRecordsBtn" class="btn btn-small btn-primary" disabled>💾 保存修改</button>
                <button id="undoEditBtn" class="btn btn-small" disabled>↩️ 撤销</button>
                <span class="toolbar-separator">|</span>
                <button id="addRowBtn" class="btn btn-small">➕ 添加行</button>
                <button id="insertRowAboveBtn" class="btn btn-small">⬆️ 上方插入</button>
                <button id="insertRowBelowBtn" class="btn btn-small">⬇️ 下方插入</button>
                <button id="deleteRowBtn" class="btn btn-small">🗑️ 删除行</button>
                <span class="toolbar-separator">|</span>
                <button id="pasteExcelBtn" class="btn btn-small" title="从Excel复制后点击此处粘贴">📋 粘贴Excel</button>
                <button id="exportRecordsBtn" class="btn btn-small">📥 导出Excel</button>
            </div>
            <span id="editStatus" class="edit-status"></span>
        `;
        recordsSection.insertBefore(toolbar, recordsSection.firstChild);

        // 绑定事件
        document.getElementById('saveRecordsBtn').addEventListener('click', () => this.saveRecords());
        document.getElementById('undoEditBtn').addEventListener('click', () => this.undoEdit());
        document.getElementById('addRowBtn').addEventListener('click', () => this.addRecordRow());
        document.getElementById('insertRowAboveBtn').addEventListener('click', () => this.insertRow('above'));
        document.getElementById('insertRowBelowBtn').addEventListener('click', () => this.insertRow('below'));
        document.getElementById('deleteRowBtn').addEventListener('click', () => this.deleteRecordRow());
        document.getElementById('pasteExcelBtn').addEventListener('click', () => this.pasteFromExcel());
        document.getElementById('exportRecordsBtn').addEventListener('click', () => this.exportRecords());

        // 添加Ctrl+V全局粘贴监听
        document.addEventListener('paste', (e) => this.handlePaste(e));

        // 初始化编辑状态
        this.pendingEdits = [];
        this.originalRecords = [];
        this.clipboardData = null;
    }

    initWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/optimization/${this.sessionId || 'new'}`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.updateConnectionStatus(true);

            // 重置输入区域状态，避免显示残留的上一次运行状态
            this.resetInputSection();

            // WebSocket连接成功后，确保件号列表已加载
            const partSelect = document.getElementById('partSelect');
            if (partSelect && partSelect.options.length <= 1) {
                console.log('[WebSocket] Part list empty, reloading...');
                this.loadPartList();
            }

            // 发送心跳
            this.heartbeatInterval = setInterval(() => {
                if (this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({ type: 'ping' }));
                }
            }, 30000);

            // WebSocket 连接成功后，如果当前在敏感分析或预测质量标签页，自动刷新数据
            if (this._currentTab === 'sensitivity') {
                console.log('[WebSocket] Reconnected, refreshing sensitivity analysis...');
                this.loadSensitivityAnalysis(true);
            } else if (this._currentTab === 'prediction') {
                console.log('[WebSocket] Reconnected, refreshing prediction heatmap...');
                this.loadPredictionHeatmap(true);
            }
        };

        this.ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            this.handleMessage(message);
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.updateConnectionStatus(false);
            clearInterval(this.heartbeatInterval);

            // 3秒后重连
            setTimeout(() => this.initWebSocket(), 3000);
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.updateConnectionStatus(false);
        };
    }

    handleMessage(message) {
        const { type, data } = message;

        switch (type) {
            case 'session_created':
                const oldSessionId = this.sessionId;
                this.sessionId = data.session_id;
                localStorage.setItem('session_id', this.sessionId);
                document.getElementById('sessionInfo').textContent = `Session: ${this.sessionId}`;
                console.log(`[handleMessage] Session created/changed: ${oldSessionId} -> ${this.sessionId}`);
                break;

            case 'log_message':
                this.addLogEntry(data.level, data.message);
                break;

            case 'optimization_started':
                this.isRunning = true;
                this.updateControlButtons();
                break;

            case 'optimization_stopped':
            case 'optimization_completed':
                this.isRunning = false;
                this.updateControlButtons();
                // 不再隐藏输入区，显示完成状态
                this.showCompletedState();
                break;

            case 'params_ready':
                console.log('[DEBUG] Received params_ready:', JSON.parse(JSON.stringify(data)));
                try {
                    this.updateInputSection(data);
                    console.log('[DEBUG] updateInputSection completed successfully');
                } catch (e) {
                    console.error('[DEBUG] Error in updateInputSection:', e);
                }
                break;

            case 'state_update':
                this.updateState(data);
                break;

            case 'error':
                this.addLogEntry('error', data.message);
                break;

            case 'pong':
                // 心跳响应
                break;

            case 'history_records':
                console.log('[WebSocket] 收到 history_records:', data.records?.length || 0, '条记录');
                this.loadHistoryRecords(data.records);
                this.updateStartButtonState(data.records);
                break;

            case 'new_record':
                console.log('[WebSocket] 收到 new_record 消息:', data);
                this.addNewRecord(data.record);
                // 自动刷新敏感度分析（非强制，允许缓存）
                this.loadSensitivityAnalysis(false);
                break;
        }
    }

    sendMessage(type, data = null) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type, data }));
        }
    }

    // ========== 业务逻辑 ==========

    async loadPartList() {
        try {
            const select = document.getElementById('partSelect');
            if (!select) {
                console.error('[loadPartList] partSelect element not found');
                return;
            }

            const response = await fetch('/api/parts');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();

            // 保留当前选中的值
            const currentValue = select.value;

            // 清空并重建选项
            select.innerHTML = '<option value="">选择件号...</option>';

            data.parts.forEach(part => {
                const option = document.createElement('option');
                option.value = part;
                option.textContent = part;
                select.appendChild(option);
            });

            // 恢复之前选中的值（如果仍然存在）
            if (currentValue && data.parts.includes(currentValue)) {
                select.value = currentValue;
            }

            this.addLogEntry('info', `已加载 ${data.parts.length} 个件号配置`);
            console.log('[loadPartList] Loaded', data.parts.length, 'parts:', data.parts);
        } catch (error) {
            console.error('[loadPartList] Error:', error);
            this.addLogEntry('error', `加载件号列表失败: ${error.message}`);
        }
    }

    async createNewPart() {
        const partName = prompt('请输入新件号名称：\n（只能包含字母、数字、下划线和连字符）');

        if (!partName || !partName.trim()) {
            return;
        }

        // 验证件号名称格式
        const validNameRegex = /^[a-zA-Z0-9_-]+$/;
        if (!validNameRegex.test(partName)) {
            alert('件号名称格式无效，只能包含字母、数字、下划线和连字符');
            return;
        }

        // 检查是否已存在
        const select = document.getElementById('partSelect');
        for (let i = 0; i < select.options.length; i++) {
            if (select.options[i].value === partName) {
                alert('该件号已存在！');
                return;
            }
        }

        // 创建新件号配置
        const defaultConfig = this.createDefaultConfig(partName);

        try {
            const response = await fetch('/api/parts/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    part_number: partName,
                    config: defaultConfig
                })
            });

            const result = await response.json();
            if (result.success) {
                this.addLogEntry('success', `已创建新件号: ${partName}`);
                // 刷新列表并选中新件号
                await this.loadPartList();
                select.value = partName;
                this.loadPartConfig(partName);
            } else {
                alert(`创建失败: ${result.error || '未知错误'}`);
            }
        } catch (error) {
            this.addLogEntry('error', `创建件号失败: ${error.message}`);
        }
    }

    createDefaultConfig(partName) {
        // 创建默认件号配置
        return {
            name: partName,
            fixed: {
                Tc: 16.0,
                F: 8.0,
                t_pack: [2.0, 1.0, 0.5, 0.5]
            },
            tunable: [
                { name: 'T', type: 'range', min: 136, max: 143, step: 1 },
                { name: 'p_vp', type: 'range', min: 700, max: 1200, step: 20 },
                { name: 'p_sw', type: 'range', min: 250, max: 600, step: 20 },
                { name: 'delay_time', type: 'range', min: 0.0, max: 2.0, step: 0.5 },
                { name: 'v1', type: 'range', min: 5, max: 40, step: 5 },
                { name: 'v2', type: 'range', min: 5, max: 40, step: 5 },
                { name: 'v3', type: 'range', min: 5, max: 40, step: 5 },
                { name: 'v4', type: 'range', min: 5, max: 40, step: 5 },
                { name: 'v5', type: 'range', min: 5, max: 40, step: 5 }
            ]
        };
    }

    async loadPartConfig(partNumber) {
        if (!partNumber) {
            document.getElementById('configPanel').style.display = 'none';
            document.getElementById('paramPanel').style.display = 'none';
            document.getElementById('startBtn').disabled = true;
            return;
        }

        try {
            const response = await fetch(`/api/parts/${partNumber}`);
            const config = await response.json();

            if (config.error) {
                this.addLogEntry('error', config.error);
                return;
            }

            this.partConfig = {
                name: partNumber,
                fixed: config.fixed || {},
                tunable: config.tunable || [],
                ui_order: config.ui_order || []
            };

            // 显示配置面板
            document.getElementById('configPanel').style.display = 'block';
            document.getElementById('paramPanel').style.display = 'block';
            document.getElementById('startBtn').disabled = false;

            // 渲染参数列表
            this.renderParamList();

            // 更新热力图参数选择器
            this._updateHeatmapOptions();

            // 保存状态
            this.onStateChange();

            this.addLogEntry('info', `已加载件号配置: ${partNumber}`);
        } catch (error) {
            this.addLogEntry('error', `加载配置失败: ${error.message}`);
        }
    }

    renderParamList() {
        const container = document.getElementById('paramList');
        container.innerHTML = '';

        if (!this.partConfig) return;

        // 类型映射
        const typeMap = {
            'fixed': '固定值',
            'range': '范围',
            'set': '离散集合',
            'choice': '模式选择',
            'mixed': '混合模式'
        };

        // 合并固定参数和可调参数为一个统一的数组
        // 注意：可调参数(tunable)在前，与试模表格顺序一致
        const allParams = [];

        // 先添加可调参数（与试模表格顺序一致）
        if (this.partConfig.tunable) {
            this.partConfig.tunable.forEach(param => {
                allParams.push({
                    ...param,
                    source: 'tunable'
                });
            });
        }

        // 再添加固定参数（转换为统一格式）
        if (this.partConfig.fixed) {
            for (const [name, value] of Object.entries(this.partConfig.fixed)) {
                allParams.push({
                    name: name,
                    type: 'fixed',
                    value: value,
                    source: 'fixed' // 标记来源
                });
            }
        }

        if (allParams.length === 0) {
            container.innerHTML = '<div class="param-empty">暂无参数配置</div>';
            return;
        }

        // 按 ui_order 排序（如果存在）
        // 确保 tunable 参数在前，fixed 参数在后，各自组内按 ui_order 排序
        if (this.partConfig.ui_order && this.partConfig.ui_order.length > 0) {
            allParams.sort((a, b) => {
                // 首先按 source 分组：tunable 在前，fixed 在后
                if (a.source !== b.source) {
                    return a.source === 'tunable' ? -1 : 1;
                }
                // 同组内按 ui_order 排序
                const idxA = this.partConfig.ui_order.indexOf(a.name);
                const idxB = this.partConfig.ui_order.indexOf(b.name);
                if (idxA === -1 && idxB === -1) return 0;
                if (idxA === -1) return 1;
                if (idxB === -1) return -1;
                return idxA - idxB;
            });
        }

        // 创建统一表格
        const table = document.createElement('table');
        table.className = 'param-table';
        table.id = 'paramTable';

        // 表头 - 新增范围和颗粒度列
        const thead = document.createElement('thead');
        thead.innerHTML = `
            <tr>
                <th style="width: 25%">参数名</th>
                <th style="width: 15%">类型</th>
                <th style="width: 30%">范围</th>
                <th style="width: 15%">粒度</th>
                ${this.isEditingConfig ? '<th style="width: 15%">操作</th>' : ''}
            </tr>
        `;
        table.appendChild(thead);

        // 表体
        const tbody = document.createElement('tbody');
        allParams.forEach((param, index) => {
            const tr = document.createElement('tr');
            tr.dataset.index = index;
            tr.dataset.source = param.source;

            // 显示绑定参数的特殊标识
            let bindIndicator = '';
            if (param.targets && param.targets.length > 1) {
                bindIndicator = ` <span title="绑定: ${param.targets.join(', ')}" style="color: #667eea;">🔗</span>`;
            }

            // 获取中文名称
            const displayName = PARAM_DISPLAY_NAMES[param.name] || param.name;
            const nameDisplay = displayName !== param.name
                ? `<span title="${param.name}">${displayName}</span>`
                : param.name;

            // 范围和颗粒度显示
            let rangeDisplay = '';
            let granularityDisplay = '';

            if (param.type === 'fixed') {
                rangeDisplay = `${param.value}`;
                granularityDisplay = '-'; // 固定值无颗粒度
            } else if (param.type === 'range') {
                rangeDisplay = `${param.min} ~ ${param.max}`;
                granularityDisplay = param.step || 1;
            } else if (param.type === 'set') {
                rangeDisplay = `{${(param.values || []).join(', ')}}`;
                granularityDisplay = '离散值';
            } else if (param.type === 'choice') {
                rangeDisplay = `模式: ${param.choiceName || param.name}`;
                granularityDisplay = '-';
            }

            tr.innerHTML = `
                <td class="param-name-cell">${nameDisplay}${bindIndicator}</td>
                <td class="param-type-cell">${typeMap[param.type] || param.type}</td>
                <td class="param-value-cell">${rangeDisplay}</td>
                <td class="param-value-cell">${granularityDisplay}</td>
            `;

            // 编辑模式添加操作按钮
            if (this.isEditingConfig) {
                const actionsTd = document.createElement('td');
                actionsTd.className = 'param-actions-cell';
                actionsTd.innerHTML = `
                    <button class="btn-icon btn-drag" title="拖拽排序" data-index="${index}">⋮⋮</button>
                    <button class="btn-icon btn-edit" title="编辑" onclick="app.editParam(${index})">✏️</button>
                    <button class="btn-icon btn-delete" title="删除" onclick="app.deleteParam(${index})">🗑️</button>
                `;
                tr.appendChild(actionsTd);
            }

            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        container.appendChild(table);

        // 启用拖拽排序
        if (this.isEditingConfig) {
            this.initParamDragSort();
        }
    }

    initParamDragSort() {
        // Enable drag sort for the unified param table
        const paramTable = document.getElementById('paramTable');
        if (!paramTable) return;
        const tbody = paramTable.querySelector('tbody');
        if (!tbody) return;

        let draggedRow = null;
        let draggedSource = null;

        tbody.querySelectorAll('tr').forEach(row => {
            const dragHandle = row.querySelector('.btn-drag');
            if (dragHandle) {
                dragHandle.draggable = true;

                dragHandle.addEventListener('dragstart', (e) => {
                    draggedRow = row;
                    draggedSource = row.dataset.source;
                    // Only allow dragging tunable params
                    if (draggedSource === 'fixed') {
                        e.preventDefault();
                        return;
                    }
                    row.style.opacity = '0.5';
                    e.dataTransfer.effectAllowed = 'move';
                });

                dragHandle.addEventListener('dragend', () => {
                    row.style.opacity = '';
                    draggedRow = null;
                    draggedSource = null;

                    // Update tunable array order based on new DOM order
                    this.updateTunableOrderFromDOM(tbody);
                });
            }

            row.addEventListener('dragover', (e) => {
                if (draggedRow && row !== draggedRow && draggedSource === 'tunable') {
                    // Only allow dropping on other tunable rows
                    if (row.dataset.source !== 'tunable') return;

                    e.preventDefault();
                    const rows = Array.from(tbody.querySelectorAll('tr'));
                    const draggedIdx = rows.indexOf(draggedRow);
                    const targetIdx = rows.indexOf(row);

                    if (draggedIdx < targetIdx) {
                        row.parentNode.insertBefore(draggedRow, row.nextSibling);
                    } else {
                        row.parentNode.insertBefore(draggedRow, row);
                    }
                }
            });
        });
    }

    // Update tunable array order based on DOM order
    updateTunableOrderFromDOM(tbody) {
        if (!this.partConfig.tunable) return;

        const rows = Array.from(tbody.querySelectorAll('tr'));
        const newTunable = [];

        rows.forEach(row => {
            if (row.dataset.source === 'tunable') {
                const paramName = row.querySelector('.param-name-cell')?.textContent?.replace('🔗', '').trim();
                const param = this.partConfig.tunable.find(p => p.name === paramName || PARAM_DISPLAY_NAMES[p.name] === paramName);
                if (param) {
                    newTunable.push(param);
                }
            }
        });

        this.partConfig.tunable = newTunable;
    }

    // 获取统一格式的所有参数数组
    getAllParams() {
        const allParams = [];
        if (this.partConfig.fixed) {
            for (const [name, value] of Object.entries(this.partConfig.fixed)) {
                allParams.push({ name, type: 'fixed', value, source: 'fixed' });
            }
        }
        if (this.partConfig.tunable) {
            this.partConfig.tunable.forEach(param => {
                allParams.push({ ...param, source: 'tunable' });
            });
        }
        return allParams;
    }

    // 从统一参数数组更新原始配置
    updateParamFromAllParams(index, updatedParam) {
        // 重新计算当前索引对应的是 fixed 还是 tunable
        const allParams = this.getAllParams();
        const targetParam = allParams[index];

        if (!targetParam) return false;

        if (targetParam.source === 'fixed') {
            // 原来是 fixed，可能变成 tunable
            if (updatedParam.type === 'fixed') {
                // 还是 fixed，更新值
                this.partConfig.fixed[targetParam.name] = updatedParam.value;
            } else {
                // 变成 tunable，从 fixed 删除，添加到 tunable
                delete this.partConfig.fixed[targetParam.name];
                if (!this.partConfig.tunable) this.partConfig.tunable = [];
                const { source, ...rest } = updatedParam;
                this.partConfig.tunable.push(rest);
            }
        } else {
            // 原来是 tunable，找到在 tunable 中的实际索引
            const tunableIndex = this.partConfig.tunable.findIndex(p => p.name === targetParam.name);
            if (tunableIndex >= 0) {
                if (updatedParam.type === 'fixed') {
                    // 变成 fixed，从 tunable 删除，添加到 fixed
                    this.partConfig.tunable.splice(tunableIndex, 1);
                    if (!this.partConfig.fixed) this.partConfig.fixed = {};
                    this.partConfig.fixed[updatedParam.name] = updatedParam.value;
                } else {
                    // 还是 tunable，更新值
                    const { source, ...rest } = updatedParam;
                    this.partConfig.tunable[tunableIndex] = rest;
                }
            }
        }
        return true;
    }

    // 从统一参数数组删除参数
    deleteParamFromAllParams(index) {
        const allParams = this.getAllParams();
        const targetParam = allParams[index];

        if (!targetParam) return false;

        if (targetParam.source === 'fixed') {
            delete this.partConfig.fixed[targetParam.name];
        } else {
            const tunableIndex = this.partConfig.tunable.findIndex(p => p.name === targetParam.name);
            if (tunableIndex >= 0) {
                this.partConfig.tunable.splice(tunableIndex, 1);
            }
        }
        return true;
    }

    editParam(index) {
        this.editingParamIndex = index;
        const allParams = this.getAllParams();
        const param = allParams[index];

        // 填充模态框
        document.getElementById('editParamName').value = param.name;
        document.getElementById('editParamType').value = param.type;

        // 更新字段显示
        this.updateEditParamFields();

        // 填充当前值
        const fieldsContainer = document.getElementById('editParamFields');
        if (param.type === 'fixed') {
            fieldsContainer.querySelector('#editParamValue').value = param.value || 0;
        } else if (param.type === 'range') {
            fieldsContainer.querySelector('#editParamMin').value = param.min || 0;
            fieldsContainer.querySelector('#editParamMax').value = param.max || 100;
            fieldsContainer.querySelector('#editParamStep').value = param.step || 1;
        } else if (param.type === 'set') {
            fieldsContainer.querySelector('#editParamValues').value = (param.values || []).join(', ');
        }

        // 显示模态框
        document.getElementById('paramEditModal').style.display = 'flex';
    }

    updateEditParamFields() {
        const type = document.getElementById('editParamType').value;
        const container = document.getElementById('editParamFields');

        let html = '';
        if (type === 'fixed') {
            html = `
                <div class="form-group">
                    <label>固定值</label>
                    <input type="number" id="editParamValue" class="form-control" step="any">
                </div>
            `;
        } else if (type === 'range') {
            html = `
                <div class="param-edit-row">
                    <div class="form-group">
                        <label>最小值</label>
                        <input type="number" id="editParamMin" class="form-control" step="any">
                    </div>
                    <div class="form-group">
                        <label>最大值</label>
                        <input type="number" id="editParamMax" class="form-control" step="any">
                    </div>
                </div>
                <div class="form-group">
                    <label>步长</label>
                    <input type="number" id="editParamStep" class="form-control" step="any">
                </div>
            `;
        } else if (type === 'set') {
            html = `
                <div class="form-group">
                    <label>可选值（逗号分隔）</label>
                    <input type="text" id="editParamValues" class="form-control" placeholder="例如: 10, 20, 30">
                </div>
            `;
        }

        container.innerHTML = html;
    }

    closeParamModal() {
        document.getElementById('paramEditModal').style.display = 'none';
        this.editingParamIndex = null;
    }

    saveParamEdit() {
        if (this.editingParamIndex === null) return;

        const allParams = this.getAllParams();
        const originalParam = allParams[this.editingParamIndex];
        if (!originalParam) return;

        // 创建更新后的参数对象
        const updatedParam = { ...originalParam };

        // 更新名称
        updatedParam.name = document.getElementById('editParamName').value.trim();
        if (!updatedParam.name) {
            alert('参数名称不能为空');
            return;
        }

        // 更新类型
        updatedParam.type = document.getElementById('editParamType').value;

        // 更新值
        const type = updatedParam.type;
        if (type === 'fixed') {
            updatedParam.value = parseFloat(document.getElementById('editParamValue').value) || 0;
            delete updatedParam.min; delete updatedParam.max; delete updatedParam.step; delete updatedParam.values;
        } else if (type === 'range') {
            updatedParam.min = parseFloat(document.getElementById('editParamMin').value) || 0;
            updatedParam.max = parseFloat(document.getElementById('editParamMax').value) || 100;
            updatedParam.step = parseFloat(document.getElementById('editParamStep').value) || 1;
            delete updatedParam.value; delete updatedParam.values;
        } else if (type === 'set') {
            const valuesStr = document.getElementById('editParamValues').value;
            updatedParam.values = valuesStr.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
            delete updatedParam.value; delete updatedParam.min; delete updatedParam.max; delete updatedParam.step;
        }

        // 更新到配置
        this.updateParamFromAllParams(this.editingParamIndex, updatedParam);

        this.closeParamModal();
        this.renderParamList();
        this.addLogEntry('info', `已更新参数: ${updatedParam.name}`);
    }

    deleteParam(index) {
        if (confirm('确定删除此参数吗？')) {
            const allParams = this.getAllParams();
            const targetParam = allParams[index];
            if (targetParam) {
                this.deleteParamFromAllParams(index);
                this.renderParamList();
                this.addLogEntry('info', `已删除参数: ${targetParam.name}`);
            }
        }
    }

    addNewParam() {
        // 新参数默认添加到 tunable
        if (!this.partConfig.tunable) this.partConfig.tunable = [];
        const newParam = {
            name: `新参数${this.partConfig.tunable.length + 1}`,
            type: 'range',
            min: 0,
            max: 100,
            step: 1
        };
        this.partConfig.tunable.push(newParam);
        this.renderParamList();
        // 自动打开编辑 - 新参数在 tunable 末尾
        const fixedCount = this.partConfig.fixed ? Object.keys(this.partConfig.fixed).length : 0;
        this.editParam(fixedCount + this.partConfig.tunable.length - 1);
    }

    async savePartConfig() {
        // 数据已在编辑时通过 editParam/saveParamEdit 更新到 this.partConfig.tunable
        // 只需发送到后端保存
        try {
            const response = await fetch(`/api/parts/${this.partConfig.name}/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.partConfig)
            });

            const result = await response.json();
            if (result.success) {
                this.addLogEntry('success', '配置保存成功');
                // 退出编辑模式
                document.getElementById('editConfigToggle').checked = false;
                this.isEditingConfig = false;
                document.getElementById('paramPanelActions').style.display = 'none';
                this.renderParamList();
            } else {
                throw new Error(result.error || '保存失败');
            }
        } catch (error) {
            this.addLogEntry('error', `保存配置失败: ${error.message}`);
        }
    }

    async startOptimization() {
        if (!this.partConfig) {
            alert('请先选择件号');
            return;
        }

        // 获取初始数据模式
        const initSourceSelect = document.getElementById('initSource');
        const initMode = initSourceSelect ? initSourceSelect.value : 'auto';

        const algoSettings = {
            n_init: parseInt(document.getElementById('nInit').value),
            n_iter: parseInt(document.getElementById('nIter').value),
            batch_size: parseInt(document.getElementById('batchSize').value),
            mode: document.getElementById('modeSelect').value,
            init_mode: initMode,
            shrink_threshold: 30.0,
            init_excel_path: null
        };

        // 如果从文件导入模式，检查并上传文件
        if (initMode === 'file') {
            const fileInput = document.getElementById('initExcelFile');
            if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
                alert('请选择初始数据文件');
                return;
            }
            try {
                this.addLogEntry('info', '正在上传初始数据文件...');
                const uploadResult = await this.uploadInitData(fileInput.files[0]);
                algoSettings.init_excel_path = uploadResult.file_path;
                fileInput.value = ''; // 清空文件选择
            } catch (error) {
                this.addLogEntry('error', `上传初始数据失败: ${error.message}`);
                return;
            }
        } else {
            this.addLogEntry('info', '使用自动生成模式创建初始采样点...');
        }

        const hasHistory = document.getElementById('startBtn').dataset.hasHistory === 'true';
        this.sendMessage('start_optimization', {
            part_config: this.partConfig,
            algo_settings: algoSettings,
            resume: hasHistory
        });

        this.addLogEntry('info', '>>> 启动优化流程...');
    }

    async uploadInitData(file) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('session_id', this.sessionId);

        const response = await fetch('/api/upload-init-data', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error('上传失败');
        }

        const result = await response.json();
        if (result.success) {
            this.addLogEntry('success', `成功上传 ${result.record_count} 条初始数据`);
            return { file_path: result.file_path };
        } else {
            throw new Error(result.error || '上传失败');
        }
    }

    saveAndExit() {
        if (!this.isRunning) return;

        // 保存并退出 - 发送 save_and_exit 消息，优雅地停止
        this.sendMessage('save_and_exit');
        this.addLogEntry('info', '进度已保存，您可以稍后点击"继续寻优"恢复');

        // 立即更新按钮状态为"继续寻优"（无需刷新页面）
        const records = this.getCurrentRecords();
        this.updateStartButtonState(records);

        alert('💾 进度已保存！\n\n您可以安全关闭页面，稍后刷新页面并点击"继续寻优"即可恢复进度。');
    }

    async resetSession() {
        if (confirm('确定要清除历史并重新开始吗？')) {
            // 通知服务器清除会话
            if (this.sessionId) {
                try {
                    await fetch(`/api/session/${this.sessionId}/clear`, { method: 'POST' });
                } catch (e) {
                    console.log('清除服务器会话失败:', e);
                }
            }
            localStorage.removeItem('session_id');
            this.sessionId = null;
            location.reload();
        }
    }

    updateInputSection(data) {
        // 隐藏等待提示，显示表格、进度和表单
        document.getElementById('waitingPrompt').style.display = 'none';
        document.getElementById('batchParamsTable').style.display = 'table';
        document.getElementById('inputProgress').style.display = 'block';
        document.getElementById('inputForm').style.display = 'flex';

        // 使用表格形式显示批次参数
        this.renderBatchParamsTable(data.batch_info);

        // 更新进度显示
        const currentGroup = data.batch_info.group_num;
        const totalGroups = data.batch_info.total_groups;
        document.getElementById('currentGroupNum').textContent = currentGroup;
        document.getElementById('totalGroups').textContent = totalGroups;

        // 更新标签文本
        const batchNum = data.batch_info.batch_num;
        const batchLabel = batchNum === 0 ? '初始' : `第${batchNum}`;
        document.getElementById('formErrorLabel').textContent =
            `面型评价指标（${batchLabel}批次第${currentGroup}组）:`;

        // 不再显示/隐藏整个区域，避免闪烁
        // 不再自动滚动，避免干扰用户
        // 不清空输入和聚焦，这些在提交后处理

        this.addLogEntry('info', data.prompt);
    }

    /**
     * 显示优化完成状态
     */
    showCompletedState() {
        // 显示完成提示，隐藏其他元素
        document.getElementById('waitingPrompt').textContent = '优化已完成';
        document.getElementById('waitingPrompt').style.display = 'block';
        document.getElementById('batchParamsTable').style.display = 'none';
        document.getElementById('inputProgress').style.display = 'none';
        document.getElementById('inputForm').style.display = 'none';
    }

    /**
     * 渲染批次参数表格
     * @param {Object} batchInfo - 批次信息
     * @param {number} batchInfo.batch_num - 批次号
     * @param {number} batchInfo.group_num - 当前组号
     * @param {number} batchInfo.total_groups - 总组数
     * @param {Array} batchInfo.batch_params - 批次参数列表
     */
    renderBatchParamsTable(batchInfo) {
        console.log('[DEBUG] renderBatchParamsTable called with:', JSON.parse(JSON.stringify(batchInfo)));
        const table = document.getElementById('batchParamsTable');
        const { group_num, batch_params } = batchInfo;

        if (!batch_params || batch_params.length === 0) {
            console.error('[DEBUG] batch_params is empty!');
            return;
        }

        // 获取所有参数名（从第一组参数提取）
        const paramKeys = Object.keys(batch_params[0]);
        console.log('[DEBUG] paramKeys:', paramKeys);

        // 构建表头
        let theadHTML = '<thead><tr><th>组号</th>';
        paramKeys.forEach(key => {
            // 使用 PARAM_DISPLAY_NAMES 映射中文名
            const displayName = PARAM_DISPLAY_NAMES[key] || key;
            theadHTML += `<th>${displayName}</th>`;
        });
        theadHTML += '</tr></thead>';

        // 构建表体
        let tbodyHTML = '<tbody>';
        batch_params.forEach((params, index) => {
            const groupNum = index + 1;
            const isCurrentGroup = groupNum === group_num;
            const rowClass = isCurrentGroup ? 'current-group' : '';

            let rowHTML = `<tr class="${rowClass}"><td>${groupNum}</td>`;
            paramKeys.forEach(key => {
                const value = params[key];
                // 智能格式化数值显示
                const displayValue = this.formatNumber(value);
                rowHTML += `<td>${displayValue}</td>`;
            });
            rowHTML += '</tr>';
            tbodyHTML += rowHTML;
        });
        tbodyHTML += '</tbody>';

        // 设置表格内容
        table.innerHTML = theadHTML + tbodyHTML;
        console.log('[DEBUG] Table rendered successfully');
    }

    submitEvaluation() {
        const formError = parseFloat(document.getElementById('formErrorInput').value);
        const isShrink = document.getElementById('isShrinkInput').checked;

        if (isNaN(formError)) {
            alert('请输入有效的面型评价指标');
            return;
        }

        this.sendMessage('submit_evaluation', {
            form_error: formError,
            is_shrink: isShrink
        });

        // 清除分析数据缓存，以便下次加载时获取最新数据
        this._sensitivityData = null;
        this._heatmapData = null;

        // 不再隐藏整个输入区，只清空输入准备下一组
        document.getElementById('formErrorInput').value = '';
        document.getElementById('isShrinkInput').checked = false;
        document.getElementById('formErrorInput').focus();

        this.addLogEntry('info', `已提交: form_error=${formError}, is_shrink=${isShrink}`);
    }

    updateState(data) {
        // 更新记录表格
        if (data.all_records) {
            this.updateRecordsGrid(data.all_records);
            // 更新收敛曲线图表
            this.updateConvergenceChartFromRecords(data.all_records);
        }
    }

    // 加载历史记录（WebSocket连接时接收）
    loadHistoryRecords(records) {
        if (records && records.length > 0) {
            this.updateRecordsGrid(records);
            this.addLogEntry('info', `已加载 ${records.length} 条历史记录`);
        }
    }

    // 更新开始按钮状态（根据是否有历史记录）
    updateStartButtonState(records) {
        const startBtn = document.getElementById('startBtn');
        if (records && records.length > 0) {
            startBtn.textContent = '▶ 继续寻优';
            startBtn.dataset.hasHistory = 'true';
        } else {
            startBtn.textContent = '▶ 开始寻优';
            startBtn.dataset.hasHistory = 'false';
        }
    }

    // 添加新记录（实时更新）
    addNewRecord(record) {
        console.log('[addNewRecord] 开始处理记录:', record);

        try {
            if (!this.recordsGrid) {
                console.error('[addNewRecord] recordsGrid 未初始化');
                return;
            }

            if (!this.recordsGrid.gridOptions) {
                console.error('[addNewRecord] gridOptions 未初始化');
                return;
            }

            const gridApi = this.recordsGrid.gridOptions.api;
            if (!gridApi) {
                console.error('[addNewRecord] gridApi 未初始化');
                return;
            }

            // 获取当前列定义
            const currentColumnDefs = gridApi.getColumnDefs();
            console.log('[addNewRecord] 当前列定义数量:', currentColumnDefs ? currentColumnDefs.length : 0);

            // 检查是否需要更新列定义（第一条记录到达时）
            if (record.params && currentColumnDefs && currentColumnDefs.length <= 3) {
                console.log('[addNewRecord] 需要更新列定义，参数:', Object.keys(record.params));

                const paramKeys = Object.keys(record.params);
                const newColumnDefs = [
                    { field: 'stage', headerName: '阶段', width: 100, editable: false },
                    ...paramKeys.map(key => ({
                        field: `params.${key}`,
                        headerName: key,
                        valueGetter: params => params.data.params?.[key],
                        valueSetter: params => {
                            if (!params.data.params) params.data.params = {};
                            params.data.params[key] = params.newValue;
                            return true;
                        },
                        width: 100,
                        editable: true
                    })),
                    {
                        field: 'form_error',
                        headerName: '面型评价指标',
                        width: 130,
                        editable: true,
                        cellEditor: 'agNumberCellEditor',
                        cellEditorParams: { precision: 4 },
                        valueFormatter: (params) => {
                            if (params.value === null || params.value === undefined) return '';
                            const num = parseFloat(params.value);
                            if (isNaN(num)) return params.value;
                            // 智能格式化：整数显示整数，小数去除末尾0
                            if (Number.isInteger(num)) return num.toString();
                            return parseFloat(num.toFixed(4)).toString();
                        }
                    },
                    {
                        field: 'is_shrink',
                        headerName: '是否缩水',
                        width: 100,
                        editable: true,
                        cellEditor: 'agSelectCellEditor',
                        cellEditorParams: { values: ['是', '否', ''] },
                        valueFormatter: (params) => {
                            const val = params.value;
                            if (val === true || val === '是' || val === 'true') return '是';
                            if (val === false || val === '否' || val === 'false') return '否';
                            return '';
                        },
                        valueParser: (params) => {
                            const val = params.newValue;
                            if (val === '是') return true;
                            if (val === '否') return false;
                            return val;
                        }
                    },
                ];

                console.log('[addNewRecord] 设置新列定义:', newColumnDefs);
                gridApi.setColumnDefs(newColumnDefs);
            }

            // 添加新行到表格开头
            console.log('[addNewRecord] 调用 applyTransaction');
            const result = gridApi.applyTransaction({ add: [record], addIndex: 0 });
            console.log('[addNewRecord] applyTransaction 结果:', result);

            this.addLogEntry('info', `新记录已添加: 阶段=${record.stage}`);
        } catch (error) {
            console.error('[addNewRecord] 错误:', error);
            this.addLogEntry('error', `添加记录失败: ${error.message}`);
        }
    }

    // 更新收敛曲线（从记录数据）
    updateConvergenceChartFromRecords(records) {
        if (!records || records.length === 0) return;

        const yTrain = records
            .filter(r => r.form_error !== null && r.form_error !== undefined)
            .map(r => r.form_error);

        if (yTrain.length === 0) return;

        const bestSoFar = [];
        let currentBest = Infinity;
        for (const y of yTrain) {
            currentBest = Math.min(currentBest, y);
            bestSoFar.push(currentBest);
        }

        this.renderConvergenceChart(yTrain, bestSoFar);
    }

    // 更新收敛曲线（从后端推送的数据）
    updateConvergenceChart(data) {
        if (!data || !data.y_train || data.y_train.length === 0) return;
        this.renderConvergenceChart(data.y_train, data.best_so_far);
    }

    // 渲染收敛曲线
    renderConvergenceChart(yTrain, bestSoFar) {
        const chartDom = document.getElementById('convergenceChart');
        if (!chartDom) return;

        // 显示图表区域
        document.getElementById('chartSection').style.display = 'block';

        // 获取或初始化图表实例
        let chart = echarts.getInstanceByDom(chartDom);
        if (!chart) {
            chart = echarts.init(chartDom);
            this.convergenceChart = chart;
        }

        const xData = yTrain.map((_, i) => i + 1);

        const option = {
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'cross' }
            },
            legend: {
                data: ['当前值', '最优值'],
                top: 0
            },
            grid: {
                left: '3%',
                right: '4%',
                bottom: '3%',
                top: '15%',
                containLabel: true
            },
            xAxis: {
                type: 'category',
                name: '实验次数',
                data: xData
            },
            yAxis: {
                type: 'value',
                name: '面型误差',
                scale: true
            },
            series: [
                {
                    name: '当前值',
                    type: 'scatter',
                    data: yTrain,
                    symbolSize: 8,
                    itemStyle: { color: '#667eea' }
                },
                {
                    name: '最优值',
                    type: 'line',
                    data: bestSoFar,
                    smooth: true,
                    lineStyle: { color: '#51cf66', width: 2 },
                    itemStyle: { color: '#51cf66' }
                }
            ]
        };

        chart.setOption(option, true);
    }

    // ========== UI 辅助 ==========

    initAGGrid() {
        const gridDiv = document.getElementById('recordsGrid');

        const columnDefs = [
            { field: 'stage', headerName: '阶段', width: 100 },
            { field: 'form_error', headerName: '面型评价指标', width: 130 },
            { field: 'is_shrink', headerName: '是否缩水', width: 100 },
        ];

        const gridOptions = {
            columnDefs: columnDefs,
            defaultColDef: {
                resizable: true,
                sortable: true,
            },
            rowData: [],
            pagination: true,
            paginationPageSize: 10,
            // 行选择配置
            rowSelection: 'single',
            onCellValueChanged: (event) => this.onCellValueChanged(event),
            // 阻止编辑时自动排序
            suppressSortingOnEdit: true,
        };

        this.recordsGrid = new agGrid.Grid(gridDiv, gridOptions);
    }

    onCellValueChanged(event) {
        // 防止重复触发（撤销操作时会再次触发）
        if (event.oldValue === event.newValue) return;

        // 记录编辑历史
        this.pendingEdits.push({
            rowIndex: event.rowIndex,
            field: event.colDef.field,
            oldValue: event.oldValue,
            newValue: event.newValue,
            data: event.data
        });

        // 更新UI状态
        this.updateEditStatus();

        // 注意：不立即发送到后端，点击保存时才批量提交
        this.addLogEntry('info', `记录已修改: ${event.colDef.headerName} = ${event.newValue}`);
    }

    updateEditStatus() {
        const saveBtn = document.getElementById('saveRecordsBtn');
        const undoBtn = document.getElementById('undoEditBtn');
        const statusLabel = document.getElementById('editStatus');

        if (this.pendingEdits.length > 0) {
            saveBtn.disabled = false;
            undoBtn.disabled = false;
            statusLabel.textContent = `有 ${this.pendingEdits.length} 处未保存修改`;
            statusLabel.className = 'edit-status dirty';
        } else {
            saveBtn.disabled = true;
            undoBtn.disabled = true;
            statusLabel.textContent = '已同步';
            statusLabel.className = 'edit-status';
        }
    }

    async saveRecords() {
        // 保存修改到后端，并触发自动回退和重启
        try {
            // 1. 应用自动回退逻辑
            const { rollbackToStage, trimmedCount } = this._applyAutoRollback();

            if (trimmedCount > 0) {
                this.addLogEntry('warning', `自动回退：已截断 ${trimmedCount} 条更晚批次记录`);
            }

            // 2. 停止当前优化（如果有）
            if (this.isRunning) {
                this.addLogEntry('info', '停止当前优化以应用修改...');
                this.sendMessage('stop_optimization');
                // 等待一小段时间确保停止
                await new Promise(r => setTimeout(r, 500));
            }

            // 3. 保存记录到后端
            const records = this.getCurrentRecords();
            const response = await fetch(`/api/records/${this.sessionId}/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    records: records,
                    rollback_to_stage: rollbackToStage
                })
            });

            // 检查响应状态
            const result = await response.json();

            if (!response.ok || result.error) {
                console.error('[saveRecords] 服务器返回错误:', result);
                const errorDetail = result.detail || result.error || '未知错误';
                throw new Error(`保存失败: ${errorDetail}`);
            }

            this.pendingEdits = [];
            this.updateEditStatus();
            this.addLogEntry('success', `记录保存成功，共 ${records.length} 条`);

            // 4. 自动重启优化
            if (records.length > 0) {
                this.addLogEntry('info', '自动重启优化...');
                await this._restartOptimization();
            }

        } catch (error) {
            console.error('[saveRecords] 错误:', error);
            this.addLogEntry('error', `保存记录失败: ${error.message}`);
            alert(`保存失败:\n${error.message}`);
        }
    }

    // 应用自动回退逻辑（参照 tkinter 版本）
    _applyAutoRollback() {
        const records = this.getCurrentRecords();
        if (!records || records.length === 0) {
            return { rollbackToStage: null, trimmedCount: 0 };
        }

        // 找到最早被修改的"已完成"记录的 stage
        let earliestModifiedRank = null;
        let earliestStage = null;

        for (const edit of this.pendingEdits) {
            const record = edit.data;
            if (!record) continue;

            // 只考虑已完成的记录（form_error 不为空）
            if (record.form_error === null || record.form_error === undefined) {
                continue;
            }

            const stage = record.stage;
            const rank = this._stageRank(stage);

            if (earliestModifiedRank === null || rank < earliestModifiedRank) {
                earliestModifiedRank = rank;
                earliestStage = stage;
            }
        }

        if (earliestModifiedRank === null) {
            return { rollbackToStage: null, trimmedCount: 0 };
        }

        // 截断更晚批次的记录
        const beforeCount = records.length;
        const keptRecords = records.filter(r => this._stageRank(r.stage) <= earliestModifiedRank);
        const trimmedCount = beforeCount - keptRecords.length;

        // 更新表格显示（使用截断后的记录）
        if (trimmedCount > 0) {
            this.updateRecordsGrid(keptRecords);
        }

        return { rollbackToStage: earliestStage, trimmedCount };
    }

    // 计算 stage 的排序值（用于回退判断）
    _stageRank(stage) {
        if (!stage) return 999999;
        const s = String(stage).toLowerCase().trim();
        if (s === 'init') return 0;
        if (s.startsWith('iter_')) {
            try {
                return parseInt(s.split('_')[1]);
            } catch (e) {
                return 999999;
            }
        }
        return 999999;
    }

    // 重启优化
    async _restartOptimization() {
        // 等待一小段时间确保后端状态已更新
        await new Promise(r => setTimeout(r, 500));

        // 触发开始优化
        this.startOptimization();
    }

    async exportRecords() {
        // 导出记录到Excel
        try {
            const records = this.getCurrentRecords();
            if (!records || records.length === 0) {
                alert('没有可导出的记录');
                return;
            }

            this.addLogEntry('info', '正在导出记录...');

            const response = await fetch(`/api/records/${this.sessionId}/export`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    records: records,
                    part_name: this.partConfig?.name || 'unknown'
                })
            });

            if (!response.ok) {
                throw new Error('导出失败');
            }

            // 获取文件名
            const contentDisposition = response.headers.get('content-disposition');
            let filename = 'experiment_records.xlsx';
            if (contentDisposition) {
                const match = contentDisposition.match(/filename="?([^"]+)"?/);
                if (match) filename = match[1];
            }

            // 下载文件
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);

            this.addLogEntry('success', `已导出 ${records.length} 条记录`);
        } catch (error) {
            this.addLogEntry('error', `导出失败: ${error.message}`);
        }
    }

    undoEdit() {
        if (this.pendingEdits.length === 0) return;

        const lastEdit = this.pendingEdits.pop();
        const api = this.recordsGrid.gridOptions.api;

        // 恢复旧值
        const rowNode = api.getDisplayedRowAtIndex(lastEdit.rowIndex);
        if (rowNode) {
            rowNode.setDataValue(lastEdit.field, lastEdit.oldValue);
        }

        this.updateEditStatus();
        this.addLogEntry('info', '已撤销上次修改');
    }

    addRecordRow() {
        const api = this.recordsGrid.gridOptions.api;
        const newRow = {
            stage: 'manual',
            form_error: null,
            is_shrink: false,
            params: {}
        };

        // 如果有参数配置，填充空参数
        if (this.partConfig && this.partConfig.tunable) {
            this.partConfig.tunable.forEach(param => {
                newRow.params[param.name] = '';
            });
        }

        api.applyTransaction({ add: [newRow] });
        this.pendingEdits.push({ type: 'add', data: newRow });
        this.updateEditStatus();
        this.addLogEntry('info', '已添加新行');
    }

    deleteRecordRow() {
        const api = this.recordsGrid.gridOptions.api;
        const selectedRows = api.getSelectedRows();

        if (selectedRows.length === 0) {
            alert('请先选中一行');
            return;
        }

        if (confirm('确定删除选中的行吗？')) {
            api.applyTransaction({ remove: selectedRows });
            this.pendingEdits.push({ type: 'delete', data: selectedRows[0] });
            this.updateEditStatus();
            this.addLogEntry('info', '已删除选中行');
        }
    }

    insertRow(position) {
        const api = this.recordsGrid.gridOptions.api;
        const selectedNodes = api.getSelectedNodes();

        if (selectedNodes.length === 0) {
            alert('请先选中一行作为参照');
            return;
        }

        const selectedNode = selectedNodes[0];
        const selectedIndex = selectedNode.rowIndex;
        const referenceData = selectedNode.data;

        // 创建新行，复制参照行的阶段
        const newRow = {
            stage: referenceData.stage || 'manual',
            form_error: null,
            is_shrink: false,
            params: {}
        };

        // 如果有参数配置，填充空参数
        if (this.partConfig && this.partConfig.tunable) {
            this.partConfig.tunable.forEach(param => {
                newRow.params[param.name] = '';
            });
        }

        // 确定插入位置
        const addIndex = position === 'above' ? selectedIndex : selectedIndex + 1;

        api.applyTransaction({
            add: [newRow],
            addIndex: addIndex
        });

        this.pendingEdits.push({ type: 'insert', position, data: newRow });
        this.updateEditStatus();
        this.addLogEntry('info', `已在${position === 'above' ? '上方' : '下方'}插入新行`);
    }

    handlePaste(e) {
        // 只有在表格区域聚焦时才处理粘贴
        const activeElement = document.activeElement;
        const gridDiv = document.getElementById('recordsGrid');

        // 检查是否聚焦于表格内或工具栏的粘贴按钮
        const isInGrid = gridDiv && (gridDiv.contains(activeElement) || activeElement === gridDiv);
        const isPasteBtn = activeElement && activeElement.id === 'pasteExcelBtn';

        if (!isInGrid && !isPasteBtn) return;

        // 阻止默认粘贴行为
        e.preventDefault();

        // 获取剪贴板数据
        const clipboardData = e.clipboardData || window.clipboardData;
        const pastedData = clipboardData.getData('Text');

        if (!pastedData) {
            this.addLogEntry('warning', '剪贴板为空');
            return;
        }

        this.processExcelData(pastedData);
    }

    pasteFromExcel() {
        // 提示用户粘贴
        const pastedData = prompt('请从Excel复制数据后，粘贴到下方：\n\n（支持多行多列，格式：阶段 面型评价指标 是否缩水 参数1 参数2...）');
        if (pastedData && pastedData.trim()) {
            this.processExcelData(pastedData);
        }
    }

    processExcelData(tsvData) {
        // 解析TSV数据（Excel默认复制格式：Tab分隔列，换行分隔行）
        const lines = tsvData.trim().split(/\r?\n/);
        if (lines.length === 0) {
            this.addLogEntry('warning', '粘贴的数据为空');
            return;
        }

        // 解析列名（第一行）
        const headers = lines[0].split('\t').map(h => h.trim());

        // 检查是否包含必要的列
        const hasStage = headers.includes('阶段');
        const hasFormError = headers.includes('面型评价指标');
        const hasShrink = headers.includes('是否缩水');

        if (!hasStage && !hasFormError && lines.length > 0) {
            // 可能没有标题行，假设第一列是阶段，第二列是form_error
            this.addLogEntry('info', '未检测到标题行，按默认格式解析...');
        }

        // 解析数据行
        const newRows = [];
        const dataStartIndex = (hasStage || hasFormError) ? 1 : 0;

        for (let i = dataStartIndex; i < lines.length; i++) {
            const line = lines[i].trim();
            if (!line) continue;

            const values = line.split('\t');
            const row = {
                stage: 'manual',
                form_error: null,
                is_shrink: false,
                params: {}
            };

            // 根据列名或位置填充数据
            for (let j = 0; j < headers.length && j < values.length; j++) {
                const header = headers[j];
                const value = values[j].trim();

                if (!value) continue;

                if (header === '阶段' || (j === 0 && !hasStage && !hasFormError)) {
                    row.stage = value;
                } else if (header === '面型评价指标' || (j === 1 && !hasStage)) {
                    const num = parseFloat(value);
                    row.form_error = isNaN(num) ? null : num;
                } else if (header === '是否缩水' || (j === 2 && !hasShrink)) {
                    row.is_shrink = (value === '是' || value === 'true' || value === '1');
                } else {
                    // 参数列
                    row.params[header] = value;
                }
            }

            // 确保params包含所有配置的参数
            if (this.partConfig && this.partConfig.tunable) {
                this.partConfig.tunable.forEach(param => {
                    if (!(param.name in row.params)) {
                        row.params[param.name] = '';
                    }
                });
            }

            newRows.push(row);
        }

        if (newRows.length === 0) {
            this.addLogEntry('warning', '未解析到有效数据');
            return;
        }

        // 添加到表格
        const api = this.recordsGrid.gridOptions.api;

        // 获取当前选中的行作为插入位置参考
        const selectedNodes = api.getSelectedNodes();
        const addIndex = selectedNodes.length > 0 ? selectedNodes[0].rowIndex + 1 : null;

        api.applyTransaction({
            add: newRows,
            addIndex: addIndex !== null ? addIndex : undefined
        });

        this.pendingEdits.push({ type: 'paste', count: newRows.length, data: newRows });
        this.updateEditStatus();
        this.addLogEntry('success', `已成功粘贴 ${newRows.length} 行数据`);
    }

    getCurrentRecords() {
        const api = this.recordsGrid.gridOptions.api;
        const records = [];
        api.forEachNode((node) => {
            records.push(node.data);
        });
        return records;
    }

    exportRecords() {
        const records = this.getCurrentRecords();
        if (records.length === 0) {
            alert('没有记录可导出');
            return;
        }

        // 构建CSV内容
        const headers = ['阶段', '面型评价指标', '是否缩水'];

        // 获取所有参数列
        const paramKeys = new Set();
        records.forEach(r => {
            if (r.params) {
                Object.keys(r.params).forEach(k => paramKeys.add(k));
            }
        });
        const sortedParamKeys = Array.from(paramKeys).sort();
        headers.push(...sortedParamKeys);

        // 构建CSV行
        const rows = records.map(r => {
            const row = [
                r.stage || '',
                r.form_error !== null && r.form_error !== undefined ? r.form_error : '',
                r.is_shrink ? '是' : '否'
            ];
            sortedParamKeys.forEach(key => {
                row.push(r.params?.[key] ?? '');
            });
            return row.map(cell => {
                // 处理包含逗号或换行符的单元格
                const cellStr = String(cell);
                if (cellStr.includes(',') || cellStr.includes('\n') || cellStr.includes('"')) {
                    return `"${cellStr.replace(/"/g, '""')}"`;
                }
                return cellStr;
            }).join(',');
        });

        const csvContent = '\ufeff' + headers.join(',') + '\n' + rows.join('\n');

        // 下载文件
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-');
        link.href = URL.createObjectURL(blob);
        link.download = `实验记录_${this.partConfig?.name || 'export'}_${timestamp}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        this.addLogEntry('success', `已导出 ${records.length} 条记录`);
    }

    updateRecordsGrid(records) {
        if (!this.recordsGrid) return;

        // 保存原始记录用于编辑比较
        this.originalRecords = JSON.parse(JSON.stringify(records));

        // 动态生成列定义（支持行内编辑）
        if (records.length > 0 && records[0].params) {
            const paramKeys = Object.keys(records[0].params);
            const columnDefs = [
                { field: 'stage', headerName: '阶段', width: 100, editable: false },
                ...paramKeys.map(key => ({
                    field: `params.${key}`,
                    headerName: PARAM_DISPLAY_NAMES[key] || key,
                    valueGetter: params => params.data.params?.[key],
                    valueSetter: params => {
                        if (!params.data.params) params.data.params = {};
                        params.data.params[key] = params.newValue;
                        return true;
                    },
                    width: 100,
                    editable: true
                })),
                {
                    field: 'form_error',
                    headerName: '面型评价指标',
                    width: 130,
                    editable: true,
                    cellEditor: 'agNumberCellEditor',
                    cellEditorParams: {
                        precision: 4
                    },
                    valueFormatter: (params) => {
                        if (params.value === null || params.value === undefined || params.value === '-') return '';
                        const num = parseFloat(params.value);
                        if (isNaN(num)) return params.value;
                        // 智能格式化：整数显示整数，小数去除末尾0
                        if (Number.isInteger(num)) return num.toString();
                        return parseFloat(num.toFixed(4)).toString();
                    }
                },
                {
                    field: 'is_shrink',
                    headerName: '是否缩水',
                    width: 100,
                    editable: true,
                    cellEditor: 'agSelectCellEditor',
                    cellEditorParams: {
                        values: ['是', '否', '']
                    },
                    valueFormatter: (params) => {
                        const val = params.value;
                        if (val === true || val === '是' || val === 'true') return '是';
                        if (val === false || val === '否' || val === 'false') return '否';
                        return '';
                    },
                    valueParser: (params) => {
                        const val = params.newValue;
                        if (val === '是') return true;
                        if (val === '否') return false;
                        return val;
                    }
                },
            ];
            this.recordsGrid.gridOptions.api.setColumnDefs(columnDefs);
        }

        const rowData = records.map(r => ({
            ...r,
            form_error: r.form_error !== null ? parseFloat(r.form_error) : null,
            is_shrink: r.is_shrink === true || r.is_shrink === '是'
        }));

        this.recordsGrid.gridOptions.api.setRowData(rowData);
    }

    addLogEntry(level, message) {
        const container = document.getElementById('logContainer');
        const entry = document.createElement('div');
        entry.className = `log-entry ${level}`;

        const timestamp = new Date().toLocaleTimeString();
        entry.textContent = `[${timestamp}] ${message}`;

        container.appendChild(entry);
        container.scrollTop = container.scrollHeight;

        // 限制日志条目数
        this.logEntries.push(entry);
        if (this.logEntries.length > 500) {
            container.removeChild(this.logEntries.shift());
        }
    }

    clearLog() {
        document.getElementById('logContainer').innerHTML = '';
        this.logEntries = [];
    }

    updateConnectionStatus(connected) {
        const dot = document.querySelector('.status-dot');
        const text = document.querySelector('.status-text');

        if (connected) {
            dot.classList.add('connected');
            text.textContent = '已连接';
        } else {
            dot.classList.remove('connected');
            text.textContent = '连接中...';
        }
    }

    updateControlButtons() {
        document.getElementById('startBtn').disabled = this.isRunning;
        document.getElementById('saveExitBtn').disabled = !this.isRunning;
    }

    checkConnection() {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.updateConnectionStatus(false);
        }
    }

    // ========== 洞察面板（标签页）==========

    initInsightsTabs() {
        // 初始化敏感度分析区域为"待评估"状态
        const sensitivityTable = document.getElementById('sensitivityTable');
        if (sensitivityTable) {
            sensitivityTable.innerHTML = `
                <div class="sensitivity-fallback">
                    <div class="icon">⏳</div>
                    <div class="message">待评估</div>
                    <div style="font-size: 0.8rem; color: #868e96; margin-top: 0.5rem;">
                        开始优化后将自动分析参数敏感性
                    </div>
                </div>
            `;
            console.log('[initInsightsTabs] 已设置初始状态为待评估');
        } else {
            console.warn('[initInsightsTabs] 未找到 sensitivityTable 元素');
        }

        // 初始化预测质量热力图参数选择器
        this._initHeatmapSelectors();

        // 标签切换
        const tabs = document.querySelectorAll('.insights-tab');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const tabName = tab.dataset.tab;

                // 切换标签激活状态
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                // 切换内容面板
                document.querySelectorAll('.insights-pane').forEach(pane => {
                    pane.classList.remove('active');
                });
                document.getElementById(tabName + 'Pane').classList.add('active');

                // 加载对应内容
                this._currentTab = tabName;
                if (tabName === 'sensitivity') {
                    this.loadSensitivityAnalysis();
                } else if (tabName === 'prediction') {
                    this.loadPredictionHeatmap();
                }
            });
        });

        // 刷新敏感性分析按钮
        const refreshBtn = document.getElementById('refreshSensitivityBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                this.loadSensitivityAnalysis(true);
            });
        }

        // 刷新预测热力图按钮
        const refreshHeatmapBtn = document.getElementById('refreshHeatmapBtn');
        if (refreshHeatmapBtn) {
            refreshHeatmapBtn.addEventListener('click', () => {
                this.loadPredictionHeatmap(true);
            });
        }
    }

    /**
     * 初始化热力图参数选择器
     * @private
     */
    _initHeatmapSelectors() {
        const xSelect = document.getElementById('heatmapXParam');
        const ySelect = document.getElementById('heatmapYParam');
        if (!xSelect || !ySelect) return;

        // 保存引用以便后续使用
        this.heatmapXSelect = xSelect;
        this.heatmapYSelect = ySelect;

        // 当参数配置加载后填充选项
        this._updateHeatmapOptions();

        // 监听参数变化
        xSelect.addEventListener('change', () => {
            // 确保X和Y不选择同一个参数
            if (xSelect.value === ySelect.value) {
                const yOptions = Array.from(ySelect.options);
                const nextOption = yOptions.find(o => o.value !== xSelect.value);
                if (nextOption) {
                    ySelect.value = nextOption.value;
                }
            }
            this.loadPredictionHeatmap(true);
        });

        ySelect.addEventListener('change', () => {
            // 确保X和Y不选择同一个参数
            if (ySelect.value === xSelect.value) {
                const xOptions = Array.from(xSelect.options);
                const nextOption = xOptions.find(o => o.value !== ySelect.value);
                if (nextOption) {
                    xSelect.value = nextOption.value;
                }
            }
            this.loadPredictionHeatmap(true);
        });
    }

    /**
     * 更新热力图参数选项
     * @private
     */
    _updateHeatmapOptions() {
        const xSelect = document.getElementById('heatmapXParam');
        const ySelect = document.getElementById('heatmapYParam');
        if (!xSelect || !ySelect || !this.partConfig?.tunable) return;

        // 清空现有选项
        xSelect.innerHTML = '';
        ySelect.innerHTML = '';

        // 添加参数选项（从 tunable 数组中提取参数名称）
        const params = this.partConfig.tunable.map(p => p.name);
        params.forEach((param, idx) => {
            const name = PARAM_DISPLAY_NAMES[param] || param;
            xSelect.add(new Option(name, idx));
            ySelect.add(new Option(name, idx));
        });

        // 默认选择前两个不同参数
        if (params.length >= 2) {
            xSelect.selectedIndex = 0;
            ySelect.selectedIndex = 1;
        }
    }

    async loadSensitivityAnalysis(force = false) {
        const container = document.getElementById('sensitivityTable');
        if (!container) return;

        // 如果没有 session，显示待评估
        if (!this.sessionId) {
            container.innerHTML = `
                <div class="sensitivity-fallback">
                    <div class="icon">⏳</div>
                    <div class="message">待评估</div>
                    <div style="font-size: 0.8rem; color: #868e96; margin-top: 0.5rem;">
                        开始优化后将自动分析参数敏感性
                    </div>
                </div>
            `;
            container.dataset.loaded = 'false';
            this._sensitivityData = null;
            return;
        }

        // 如果有缓存且不是强制刷新，直接渲染缓存数据
        if (!force && this._sensitivityData) {
            console.log('[loadSensitivityAnalysis] Using cached data');
            this.renderSensitivityAnalysis(this._sensitivityData);
            return;
        }

        // 显示加载状态
        container.innerHTML = '<div class="sensitivity-fallback"><div class="icon">⏳</div><div class="message">正在分析参数敏感性...</div></div>';

        try {
            const response = await fetch(`/api/explain/sensitivity?session_id=${this.sessionId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            // 缓存数据（仅缓存非回退结果）
            if (!data.is_fallback || data.fallback_reason !== 'session_not_found') {
                this._sensitivityData = data;
            }
            this.renderSensitivityAnalysis(data);

        } catch (error) {
            console.error('[loadSensitivityAnalysis] Error:', error);
            // 不再重置 sessionId，只显示错误信息
            container.innerHTML = `<div class="sensitivity-fallback"><div class="icon">⚠️</div><div class="message">加载失败: ${error.message}</div><div style="font-size: 0.8rem; color: #868e96; margin-top: 0.5rem;">点击刷新按钮重试</div></div>`;
        }
    }

    renderSensitivityAnalysis(data) {
        const container = document.getElementById('sensitivityTable');

        // 检查是否是回退结果（数据不足等）
        if (data.is_fallback) {
            container.innerHTML = `
                <div class="sensitivity-fallback">
                    <div class="icon">📊</div>
                    <div class="message">${data.interpretation}</div>
                </div>
            `;
            return;
        }

        // 构建排名列表
        const rankings = data.rankings || [];
        if (rankings.length === 0) {
            container.innerHTML = `
                <div class="sensitivity-fallback">
                    <div class="icon">📊</div>
                    <div class="message">暂无敏感性数据</div>
                </div>
            `;
            return;
        }

        // 生成HTML
        let html = '<div class="sensitivity-ranking">';

        rankings.forEach((item, index) => {
            const displayName = PARAM_DISPLAY_NAMES[item.param_name] || item.param_name;
            const rankClass = index < 3 ? 'top3' : '';
            const barWidth = Math.round(item.sensitivity_score * 100);

            html += `
                <div class="sensitivity-item">
                    <div class="sensitivity-rank ${rankClass}">${item.importance_rank}</div>
                    <div class="sensitivity-info">
                        <div class="sensitivity-name">${displayName}</div>
                        <div class="sensitivity-meta">长度尺度: ${item.length_scale.toFixed(4)}</div>
                    </div>
                    <div class="sensitivity-score">
                        <div class="sensitivity-bar">
                            <div class="sensitivity-bar-fill" style="width: ${barWidth}%"></div>
                        </div>
                        <div class="sensitivity-label">${item.interpretation}</div>
                    </div>
                </div>
            `;
        });

        html += '</div>';

        // 添加说明文字
        if (data.interpretation) {
            html += `<div class="sensitivity-desc" style="margin-top: 1rem; padding: 0.75rem; background: #e7f5ff; border-radius: 6px; color: #1864ab;">${data.interpretation}</div>`;
        }

        container.innerHTML = html;
    }

    // ========== 预测质量热力图 ==========

    async loadPredictionHeatmap(force = false) {
        const container = document.getElementById('predictionHeatmap');
        if (!container) return;

        // 如果没有 session，显示待评估
        if (!this.sessionId) {
            container.innerHTML = `
                <div class="sensitivity-fallback">
                    <div class="icon">⏳</div>
                    <div class="message">待评估</div>
                    <div style="font-size: 0.8rem; color: #868e96; margin-top: 0.5rem;">
                        开始优化后将自动生成预测热力图
                    </div>
                </div>
            `;
            this._heatmapData = null;
            return;
        }

        const xParam = document.getElementById('heatmapXParam')?.value || 0;
        const yParam = document.getElementById('heatmapYParam')?.value || 1;

        // 检查缓存：参数相同且有缓存数据时直接使用
        if (!force && this._heatmapData &&
            this._heatmapData.param_x_idx === parseInt(xParam) &&
            this._heatmapData.param_y_idx === parseInt(yParam)) {
            console.log('[loadPredictionHeatmap] Using cached data');
            this.renderPredictionHeatmap(this._heatmapData);
            return;
        }

        // 销毁旧的 ECharts 实例（避免 DOM 操作冲突）
        const oldChart = echarts.getInstanceByDom(container);
        if (oldChart) {
            oldChart.dispose();
        }

        // 显示加载状态
        container.innerHTML = '<div class="sensitivity-fallback"><div class="icon">⏳</div><div class="message">正在生成热力图...</div></div>';

        try {
            console.log(`[loadPredictionHeatmap] Requesting with session_id=${this.sessionId}, x_param=${xParam}, y_param=${yParam}`);
            const response = await fetch(`/api/explain/prediction_heatmap?session_id=${this.sessionId}&x_param=${xParam}&y_param=${yParam}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            console.log(`[loadPredictionHeatmap] Response status: ${response.status}`);

            if (!response.ok) {
                if (response.status === 404) {
                    throw new Error('会话不存在，请重新开始优化');
                }
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
            }

            const data = await response.json();

            // 检查是否有数据
            if (!data.predictions || data.predictions.length === 0) {
                container.innerHTML = `
                    <div class="sensitivity-fallback">
                        <div class="icon">📊</div>
                        <div class="message">数据量不足</div>
                        <div style="font-size: 0.8rem; color: #868e96; margin-top: 0.5rem;">
                            建议至少进行5轮实验后查看预测热力图
                        </div>
                    </div>
                `;
                this._heatmapData = null;
                return;
            }

            // 缓存数据
            this._heatmapData = data;
            this.renderPredictionHeatmap(data);

        } catch (error) {
            console.error('[loadPredictionHeatmap] Error:', error);
            // 不再重置 sessionId，只显示错误信息
            container.innerHTML = `
                <div class="sensitivity-fallback">
                    <div class="icon">⚠️</div>
                    <div class="message">加载失败: ${error.message}</div>
                    <div style="font-size: 0.8rem; color: #868e96; margin-top: 0.5rem;">
                        点击刷新按钮重试
                    </div>
                </div>
            `;
        }
    }

    renderPredictionHeatmap(data) {
        const container = document.getElementById('predictionHeatmap');
        if (!container) return;

        // 确保容器有高度
        if (container.clientHeight < 100) {
            container.style.height = '400px';
        }

        // 清理容器内容（移除加载提示等）
        if (container.innerHTML.includes('sensitivity-fallback')) {
            container.innerHTML = '';
        }

        // 初始化或获取 ECharts 实例
        let chart = echarts.getInstanceByDom(container);
        if (!chart) {
            chart = echarts.init(container);
        }

        // 获取参数显示名称
        const xParamName = PARAM_DISPLAY_NAMES[data.param_x] || data.param_x;
        const yParamName = PARAM_DISPLAY_NAMES[data.param_y] || data.param_y;

        // 转换预测值为 ECharts 热力图格式 [x, y, value]
        const heatmapData = [];
        const predictions = data.predictions;
        for (let i = 0; i < data.y_values.length; i++) {
            for (let j = 0; j < data.x_values.length; j++) {
                // ECharts 热力图: [x索引, y索引, 值]
                heatmapData.push([j, i, predictions[i][j]]);
            }
        }

        // 计算颜色范围
        const allValues = predictions.flat();
        const minValue = Math.min(...allValues);
        const maxValue = Math.max(...allValues);

        // 准备训练数据点(白色圆圈)
        const trainingPoints = data.training_points.map(p => {
            // 找到最接近的网格索引
            const xIdx = this._findNearestIndex(data.x_values, p[data.param_x]);
            const yIdx = this._findNearestIndex(data.y_values, p[data.param_y]);
            return {
                value: [xIdx, yIdx],
                itemStyle: {
                    color: 'white',
                    borderColor: 'black',
                    borderWidth: 1
                }
            };
        });

        // 准备当前最优点(红色星号)
        const currentBestPoint = data.current_best ? [{
            value: [
                this._findNearestIndex(data.x_values, data.current_best[data.param_x]),
                this._findNearestIndex(data.y_values, data.current_best[data.param_y])
            ],
            symbol: 'star',
            symbolSize: 20,
            itemStyle: {
                color: '#ff0000',
                borderColor: 'white',
                borderWidth: 2,
                shadowBlur: 10,
                shadowColor: 'rgba(255, 0, 0, 0.5)'
            }
        }] : [];

        const option = {
            tooltip: {
                position: 'top',
                formatter: (params) => {
                    if (params.seriesType === 'heatmap') {
                        const x = data.x_values[params.data[0]];
                        const y = data.y_values[params.data[1]];
                        const val = params.data[2];
                        return `
                            <div style="font-weight:bold">${xParamName}: ${x.toFixed(3)}</div>
                            <div style="font-weight:bold">${yParamName}: ${y.toFixed(3)}</div>
                            <div>预测误差: ${val.toFixed(4)}</div>
                        `;
                    }
                    return '';
                }
            },
            grid: {
                top: 30,
                right: 80,  // 为颜色条留出空间
                bottom: 50,
                left: 60
            },
            xAxis: {
                type: 'category',
                data: data.x_values.map(v => v.toFixed(2)),
                name: xParamName,
                nameLocation: 'middle',
                nameGap: 30,
                axisLabel: {
                    fontSize: 10,
                    interval: Math.floor(data.x_values.length / 5)  // 只显示约6个标签
                }
            },
            yAxis: {
                type: 'category',
                data: data.y_values.map(v => v.toFixed(2)),
                name: yParamName,
                nameLocation: 'middle',
                nameGap: 40,
                axisLabel: {
                    fontSize: 10,
                    interval: Math.floor(data.y_values.length / 5)
                }
            },
            visualMap: {
                min: minValue,
                max: maxValue,
                calculable: true,
                orient: 'vertical',
                right: 10,
                top: 'center',
                itemHeight: 200,
                inRange: {
                    // 蓝色(好) -> 青色 -> 黄色 -> 橙色 -> 红色(差)
                    color: ['#313695', '#4575b4', '#74add1', '#abd9e9', '#e0f3f8', '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027', '#a50026']
                },
                text: ['高(差)', '低(好)'],
                textStyle: {
                    fontSize: 11
                }
            },
            series: [
                {
                    name: '预测误差',
                    type: 'heatmap',
                    data: heatmapData,
                    emphasis: {
                        itemStyle: {
                            shadowBlur: 10,
                            shadowColor: 'rgba(0, 0, 0, 0.5)'
                        }
                    }
                },
                {
                    name: '已探索点',
                    type: 'scatter',
                    data: trainingPoints,
                    symbolSize: 8,
                    z: 10
                },
                {
                    name: '当前最优点',
                    type: 'scatter',
                    data: currentBestPoint,
                    z: 11
                }
            ]
        };

        chart.setOption(option, true);

        // 响应式调整
        if (!this._heatmapResizeHandler) {
            this._heatmapResizeHandler = () => {
                chart.resize();
            };
            window.addEventListener('resize', this._heatmapResizeHandler);
        }
    }

    /**
     * 找到数组中最接近目标值的索引
     * @private
     */
    _findNearestIndex(arr, target) {
        let minDiff = Infinity;
        let bestIdx = 0;
        for (let i = 0; i < arr.length; i++) {
            const diff = Math.abs(arr[i] - target);
            if (diff < minDiff) {
                minDiff = diff;
                bestIdx = i;
            }
        }
        return bestIdx;
    }

    // ========== UI状态持久化 ==========

    saveUIState() {
        const state = {
            // 算法设置
            algoSettings: {
                n_init: document.getElementById('nInit')?.value,
                n_iter: document.getElementById('nIter')?.value,
                batch_size: document.getElementById('batchSize')?.value,
                mode: document.getElementById('modeSelect')?.value
            },
            // 当前选中的件号
            selectedPart: this.partConfig?.name || null,
            // 时间戳
            timestamp: Date.now()
        };
        localStorage.setItem('injectionMoldingUIState', JSON.stringify(state));
    }

    loadUIState() {
        try {
            const saved = localStorage.getItem('injectionMoldingUIState');
            if (!saved) return;

            const state = JSON.parse(saved);

            // 恢复算法设置
            if (state.algoSettings) {
                const { n_init, n_iter, batch_size, mode } = state.algoSettings;
                if (n_init) document.getElementById('nInit').value = n_init;
                if (n_iter) document.getElementById('nIter').value = n_iter;
                if (batch_size) document.getElementById('batchSize').value = batch_size;
                if (mode) document.getElementById('modeSelect').value = mode;
            }

            // 恢复选中的件号（在件号列表加载后）
            if (state.selectedPart) {
                const checkAndSelect = () => {
                    const select = document.getElementById('partSelect');
                    if (select && select.querySelector(`option[value="${state.selectedPart}"]`)) {
                        select.value = state.selectedPart;
                        this.loadPartConfig(state.selectedPart);
                    }
                };
                // 延迟等待件号列表加载
                setTimeout(checkAndSelect, 500);
            }

            this.addLogEntry('info', '已恢复上次会话设置');
        } catch (e) {
            console.error('加载UI状态失败:', e);
        }
    }

    // 在关键操作后保存状态
    onStateChange() {
        this.saveUIState();
    }

    /**
     * 初始化可拖拽调整大小功能
     */
    initResizableLayout() {
        // 垂直分隔线（侧边栏宽度）
        this.initVerticalResizer('resizerVertical', '.sidebar', 250, 500, 'sidebarWidth');

        // 左侧水平分隔线（算法设置和参数配置之间）
        this.initHorizontalResizer('resizerConfigParam', '#configPanel', '#paramPanel', 150, 400, 'configPanelHeight');

        // 右侧水平分隔线（输入区和日志区之间）
        this.initHorizontalResizer('resizerInputLog', '.input-section', '.log-section', 200, 500, 'inputSectionHeight');

        // 右侧水平分隔线（日志区和实验记录之间）
        this.initHorizontalResizer('resizerLogRecords', '.log-section', '.records-section', 150, 400, 'logSectionHeight');
    }

    /**
     * 初始化垂直分隔线（调整宽度）
     */
    initVerticalResizer(resizerId, targetSelector, minSize, maxSize, storageKey) {
        const resizer = document.getElementById(resizerId);
        if (!resizer) return;

        let startX, startWidth;
        const targetEl = document.querySelector(targetSelector);

        // 恢复保存的宽度
        const savedWidth = localStorage.getItem(storageKey);
        if (savedWidth) {
            targetEl.style.width = savedWidth + 'px';
        }

        resizer.addEventListener('mousedown', (e) => {
            startX = e.clientX;
            startWidth = parseInt(document.defaultView.getComputedStyle(targetEl).width, 10);

            // 添加遮罩层
            const overlay = document.createElement('div');
            overlay.className = 'resizing-overlay';
            overlay.style.cursor = 'col-resize';
            document.body.appendChild(overlay);

            const doDrag = (e) => {
                const newWidth = startWidth + e.clientX - startX;
                if (newWidth >= minSize && newWidth <= maxSize) {
                    targetEl.style.width = newWidth + 'px';
                }
            };

            const stopDrag = () => {
                document.removeEventListener('mousemove', doDrag);
                document.removeEventListener('mouseup', stopDrag);
                // 保存宽度
                localStorage.setItem(storageKey, parseInt(document.defaultView.getComputedStyle(targetEl).width, 10));
                overlay.remove();
            };

            document.addEventListener('mousemove', doDrag);
            document.addEventListener('mouseup', stopDrag);
        });
    }

    /**
     * 初始化水平分隔线（调整高度）
     */
    initHorizontalResizer(resizerId, topSelector, bottomSelector, minSize, maxSize, storageKey) {
        const resizer = document.getElementById(resizerId);
        if (!resizer) return;

        // 初始隐藏左侧分隔线（因为对应面板可能隐藏）
        if (resizerId === 'resizerConfigParam') {
            // 监听面板显示状态
            const observer = new MutationObserver(() => {
                const configPanel = document.getElementById('configPanel');
                const paramPanel = document.getElementById('paramPanel');
                if (configPanel.style.display !== 'none' && paramPanel.style.display !== 'none') {
                    resizer.style.display = 'block';
                } else {
                    resizer.style.display = 'none';
                }
            });
            const configPanel = document.getElementById('configPanel');
            if (configPanel) {
                observer.observe(configPanel, { attributes: true, attributeFilter: ['style'] });
            }
        }

        let startY, startHeight;
        const topEl = document.querySelector(topSelector);

        // 恢复保存的高度
        const savedHeight = localStorage.getItem(storageKey);
        if (savedHeight) {
            topEl.style.flex = '0 0 ' + savedHeight + 'px';
        }

        resizer.addEventListener('mousedown', (e) => {
            startY = e.clientY;
            startHeight = parseInt(document.defaultView.getComputedStyle(topEl).height, 10);

            // 添加遮罩层
            const overlay = document.createElement('div');
            overlay.className = 'resizing-overlay';
            overlay.style.cursor = 'row-resize';
            document.body.appendChild(overlay);

            const doDrag = (e) => {
                const newHeight = startHeight + e.clientY - startY;
                if (newHeight >= minSize && newHeight <= maxSize) {
                    topEl.style.flex = '0 0 ' + newHeight + 'px';
                }
            };

            const stopDrag = () => {
                document.removeEventListener('mousemove', doDrag);
                document.removeEventListener('mouseup', stopDrag);
                // 保存高度
                localStorage.setItem(storageKey, parseInt(document.defaultView.getComputedStyle(topEl).height, 10));
                overlay.remove();
            };

            document.addEventListener('mousemove', doDrag);
            document.addEventListener('mouseup', stopDrag);
        });
    }
}

// 启动应用
document.addEventListener('DOMContentLoaded', () => {
    window.app = new OptimizationApp();
});
