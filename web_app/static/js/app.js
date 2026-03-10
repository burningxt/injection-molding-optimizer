/**
 * 注塑成型工艺参数智能推荐系统 - 前端主应用
 */

class OptimizationApp {
    constructor() {
        this.ws = null;
        this.sessionId = localStorage.getItem('session_id') || null;
        this.partConfig = null;
        this.isRunning = false;
        this.recordsGrid = null;
        this.logEntries = [];

        this.init();
    }

    init() {
        this.initUI();
        this.initWebSocket();
        this.initAGGrid();
        this.loadPartList();

        // 心跳检测
        setInterval(() => this.checkConnection(), 30000);
    }

    initUI() {
        // 件号选择
        document.getElementById('partSelect').addEventListener('change', (e) => {
            this.loadPartConfig(e.target.value);
        });

        document.getElementById('refreshPartsBtn').addEventListener('click', () => {
            this.loadPartList();
        });

        // 控制按钮
        document.getElementById('startBtn').addEventListener('click', () => {
            this.startOptimization();
        });

        document.getElementById('stopBtn').addEventListener('click', () => {
            this.stopOptimization();
        });

        document.getElementById('resetBtn').addEventListener('click', () => {
            this.resetSession();
        });

        document.getElementById('clearLogBtn').addEventListener('click', () => {
            this.clearLog();
        });

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
    }

    initWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/optimization/${this.sessionId || 'new'}`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.updateConnectionStatus(true);

            // 发送心跳
            this.heartbeatInterval = setInterval(() => {
                if (this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({ type: 'ping' }));
                }
            }, 30000);
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
                this.sessionId = data.session_id;
                localStorage.setItem('session_id', this.sessionId);
                document.getElementById('sessionInfo').textContent = `Session: ${this.sessionId}`;
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
                document.getElementById('inputSection').style.display = 'none';
                break;

            case 'params_ready':
                this.showInputSection(data);
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
            const response = await fetch('/api/parts');
            const data = await response.json();

            const select = document.getElementById('partSelect');
            select.innerHTML = '<option value="">选择件号...</option>';

            data.parts.forEach(part => {
                const option = document.createElement('option');
                option.value = part;
                option.textContent = part;
                select.appendChild(option);
            });

            this.addLogEntry('info', `已加载 ${data.parts.length} 个件号配置`);
        } catch (error) {
            this.addLogEntry('error', `加载件号列表失败: ${error.message}`);
        }
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

            this.addLogEntry('info', `已加载件号配置: ${partNumber}`);
        } catch (error) {
            this.addLogEntry('error', `加载配置失败: ${error.message}`);
        }
    }

    renderParamList() {
        const container = document.getElementById('paramList');
        container.innerHTML = '';

        if (!this.partConfig || !this.partConfig.tunable) return;

        this.partConfig.tunable.forEach(param => {
            const div = document.createElement('div');
            div.className = 'param-item';

            const typeMap = {
                'fixed': '固定值',
                'range': '范围',
                'set': '离散集合',
                'choice': '模式选择',
                'mixed': '混合模式'
            };

            div.innerHTML = `
                <span class="param-name">${param.name}</span>
                <span class="param-type">${typeMap[param.type] || param.type}</span>
            `;

            container.appendChild(div);
        });
    }

    startOptimization() {
        if (!this.partConfig) {
            alert('请先选择件号');
            return;
        }

        const algoSettings = {
            n_init: parseInt(document.getElementById('nInit').value),
            n_iter: parseInt(document.getElementById('nIter').value),
            batch_size: parseInt(document.getElementById('batchSize').value),
            mode: document.getElementById('modeSelect').value,
            init_mode: 'auto',  // 简化处理
            shrink_threshold: 30.0
        };

        this.sendMessage('start_optimization', {
            part_config: this.partConfig,
            algo_settings: algoSettings
        });

        this.addLogEntry('info', '>>> 启动优化流程...');
    }

    stopOptimization() {
        this.sendMessage('stop_optimization');
        this.addLogEntry('warning', '正在停止优化...');
    }

    resetSession() {
        if (confirm('确定要清除历史并重新开始吗？')) {
            localStorage.removeItem('session_id');
            this.sessionId = null;
            location.reload();
        }
    }

    showInputSection(data) {
        const section = document.getElementById('inputSection');
        const paramsDisplay = document.getElementById('currentParams');

        // 显示参数
        const params = data.current_sample;
        let paramsText = '';
        for (const [key, value] of Object.entries(params)) {
            paramsText += `${key}: ${value}\n`;
        }
        paramsDisplay.textContent = paramsText;

        // 显示输入区
        section.style.display = 'block';
        section.scrollIntoView({ behavior: 'smooth' });

        // 清空输入
        document.getElementById('formErrorInput').value = '';
        document.getElementById('isShrinkInput').checked = false;
        document.getElementById('formErrorInput').focus();

        this.addLogEntry('info', data.prompt);
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

        document.getElementById('inputSection').style.display = 'none';
        this.addLogEntry('info', `已提交: form_error=${formError}, is_shrink=${isShrink}`);
    }

    updateState(data) {
        // 更新记录表格
        if (data.all_records) {
            this.updateRecordsGrid(data.all_records);
        }
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
        };

        this.recordsGrid = new agGrid.Grid(gridDiv, gridOptions);
    }

    updateRecordsGrid(records) {
        if (!this.recordsGrid) return;

        // 动态生成列定义
        if (records.length > 0 && records[0].params) {
            const paramKeys = Object.keys(records[0].params);
            const columnDefs = [
                { field: 'stage', headerName: '阶段', width: 100 },
                ...paramKeys.map(key => ({
                    field: `params.${key}`,
                    headerName: key,
                    valueGetter: params => params.data.params?.[key],
                    width: 100
                })),
                { field: 'form_error', headerName: '面型评价指标', width: 130 },
                { field: 'is_shrink', headerName: '是否缩水', width: 100 },
            ];
            this.recordsGrid.gridOptions.api.setColumnDefs(columnDefs);
        }

        const rowData = records.map(r => ({
            ...r,
            form_error: r.form_error !== null ? r.form_error.toFixed(4) : '-',
            is_shrink: r.is_shrink ? '是' : '否'
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
        document.getElementById('stopBtn').disabled = !this.isRunning;
    }

    checkConnection() {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.updateConnectionStatus(false);
        }
    }
}

// 启动应用
document.addEventListener('DOMContentLoaded', () => {
    window.app = new OptimizationApp();
});
