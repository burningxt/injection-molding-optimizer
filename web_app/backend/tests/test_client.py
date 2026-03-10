"""优化系统测试客户端 - 模拟前端行为"""
import asyncio
import websockets
import json
from typing import List, Dict, Any, Optional
from datetime import datetime


class OptimizationTestClient:
    """优化系统测试客户端 - 模拟前端行为"""

    def __init__(self, base_url: str = "ws://localhost:8000"):
        self.base_url = base_url
        self.ws = None
        self.session_id: Optional[str] = None
        self.messages: List[Dict] = []
        self.records: List[Dict] = []
        self.logs: List[str] = []
        self._receive_task = None
        self._stop_receive = False

    async def connect(self, session_id: str = "new"):
        """连接到WebSocket"""
        uri = f"{self.base_url}/ws/optimization/{session_id}"
        self.ws = await websockets.connect(uri)
        self._stop_receive = False
        self._receive_task = asyncio.create_task(self._receive_loop())
        # 等待session_created或历史记录
        await asyncio.sleep(0.5)
        return self

    async def _receive_loop(self):
        """接收消息循环"""
        try:
            while not self._stop_receive:
                try:
                    message = await asyncio.wait_for(self.ws.recv(), timeout=0.1)
                    data = json.loads(message)
                    self.messages.append(data)
                    await self._handle_message(data)
                except asyncio.TimeoutError:
                    continue
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"[Receive Error] {e}")

    async def _handle_message(self, data: Dict):
        """处理收到的消息"""
        msg_type = data.get('type')

        if msg_type == 'session_created':
            self.session_id = data['data']['session_id']
            print(f"[TestClient] Session created: {self.session_id}")
        elif msg_type == 'history_records':
            self.records = data['data'].get('records', [])
            print(f"[TestClient] Loaded {len(self.records)} history records")
        elif msg_type == 'log_message':
            log_entry = f"[{data['data']['level']}] {data['data']['message']}"
            self.logs.append(log_entry)
            print(f"[TestClient] {log_entry}")
        elif msg_type == 'new_record':
            record = data['data']['record']
            self.records.append(record)
            print(f"[TestClient] New record: stage={record.get('stage')}, fe={record.get('form_error')}")
        elif msg_type == 'params_ready':
            print(f"[TestClient] Params ready for input")

    async def send(self, msg_type: str, data: Any = None):
        """发送消息"""
        if self.ws:
            await self.ws.send(json.dumps({'type': msg_type, 'data': data}))

    async def wait_for_message(self, msg_type: str, timeout: float = 10.0) -> Optional[Dict]:
        """等待特定类型的消息"""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            for msg in reversed(self.messages):
                if msg.get('type') == msg_type:
                    return msg
            await asyncio.sleep(0.1)
        return None

    async def wait_for_log(self, pattern: str, timeout: float = 10.0) -> bool:
        """等待包含特定模式的日志"""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            for log in self.logs:
                if pattern in log:
                    return True
            await asyncio.sleep(0.1)
        return False

    async def start_optimization(self, part_config: Dict, algo_settings: Dict):
        """启动优化"""
        print(f"[TestClient] Starting optimization: n_init={algo_settings.get('n_init')}")
        await self.send('start_optimization', {
            'part_config': part_config,
            'algo_settings': algo_settings
        })
        return await self.wait_for_message('optimization_started')

    async def submit_evaluation(self, form_error: float, is_shrink: bool = False):
        """提交评价"""
        await self.send('submit_evaluation', {
            'form_error': form_error,
            'is_shrink': is_shrink
        })

    async def save_and_exit(self):
        """保存并退出"""
        print("[TestClient] Sending save_and_exit")
        await self.send('save_and_exit')
        return await self.wait_for_message('optimization_stopped')

    async def stop_optimization(self):
        """停止优化"""
        await self.send('stop_optimization')
        return await self.wait_for_message('optimization_stopped')

    async def close(self):
        """关闭连接"""
        self._stop_receive = True
        if self._receive_task:
            try:
                self._receive_task.cancel()
                await asyncio.wait_for(self._receive_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        if self.ws:
            await self.ws.close()

    def get_records_by_stage(self, stage: str) -> List[Dict]:
        """获取特定阶段的记录"""
        return [r for r in self.records if r.get('stage') == stage]

    def get_iter_records(self) -> List[Dict]:
        """获取所有迭代阶段的记录"""
        return [r for r in self.records if r.get('stage', '').startswith('iter_')]

    def has_log_pattern(self, pattern: str) -> bool:
        """检查是否包含特定日志模式"""
        return any(pattern in log for log in self.logs)

    def print_summary(self):
        """打印测试摘要"""
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"Session ID: {self.session_id}")
        print(f"Total records: {len(self.records)}")
        print(f"Init records: {len(self.get_records_by_stage('init'))}")
        print(f"Iter records: {len(self.get_iter_records())}")
        print(f"Total logs: {len(self.logs)}")
        print("=" * 60)


# 测试数据
TEST_PART_CONFIG = {
    "name": "LS39860A-903",
    "fixed": {
        "Tc": 16,
        "F": 8,
        "t_pack": [2, 1, 0.5, 0.5]
    },
    "tunable": [
        {"name": "T", "type": "range", "min": 136, "max": 143, "step": 1},
        {"name": "p_vp", "type": "range", "min": 700, "max": 1200, "step": 20},
        {"name": "p_sw", "type": "range", "min": 240, "max": 600, "step": 20},
        {"name": "delay", "type": "range", "min": 0, "max": 2, "step": 0.5},
        {"name": "v1", "type": "range", "min": 5, "max": 40, "step": 5},
        {"name": "v2", "type": "range", "min": 5, "max": 40, "step": 5},
        {"name": "v3", "type": "range", "min": 5, "max": 40, "step": 5},
        {"name": "v4", "type": "range", "min": 5, "max": 40, "step": 5},
        {"name": "v5", "type": "range", "min": 5, "max": 40, "step": 5},
    ]
}

TEST_ALGO_SETTINGS = {
    "n_init": 10,
    "n_iter": 5,
    "batch_size": 4,
    "mode": "manual",
    "shrink_threshold": 30.0
}


# 简单的同步测试函数
async def run_basic_test():
    """运行基本测试 - 启动优化并完成初始化"""
    client = OptimizationTestClient()
    try:
        await client.connect()

        # 启动优化
        result = await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)
        print(f"Optimization started: {result}")

        # 完成所有初始化输入
        for i in range(TEST_ALGO_SETTINGS['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if msg:
                await client.submit_evaluation(float(i + 1), is_shrink=False)
                await asyncio.sleep(0.1)

        # 等待初始化完成
        await asyncio.sleep(1.0)

        # 打印摘要
        client.print_summary()

        # 保存退出
        await client.save_and_exit()
        await asyncio.sleep(0.5)

        print("\nSave exit logs:")
        for log in client.logs[-5:]:
            print(f"  {log}")

        return client.session_id

    finally:
        await client.close()


if __name__ == "__main__":
    # 独立运行测试
    session_id = asyncio.run(run_basic_test())
    print(f"\nTest completed. Session ID: {session_id}")
