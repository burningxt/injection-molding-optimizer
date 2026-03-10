#!/usr/bin/env python3
"""WebSocket 自动化测试脚本 - 测试实验记录实时更新"""

import asyncio
import websockets
import json
import sys

# 彩色输出
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
RESET = '\033[0m'

def log_recv(msg):
    print(f"{GREEN}[接收]{RESET} {msg}")

def log_send(msg):
    print(f"{YELLOW}[发送]{RESET} {msg}")

def log_info(msg):
    print(f"[信息] {msg}")

def log_error(msg):
    print(f"{RED}[错误]{RESET} {msg}")

async def get_part_config(part_number: str) -> dict:
    """通过 REST API 获取件号配置"""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://localhost:8000/api/parts/{part_number}") as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                raise Exception(f"无法获取件号配置: {resp.status}")

async def test_optimization():
    # 使用新的会话 ID，避免历史记录干扰
    import uuid
    session_id = f"test_{uuid.uuid4().hex[:8]}"
    uri = f"ws://localhost:8000/ws/optimization/{session_id}"
    log_info(f"使用新会话 ID: {session_id}")

    log_info(f"连接到 {uri}")

    try:
        # 首先获取件号配置
        log_info("获取件号配置...")
        part_config = await get_part_config("LS39860A-903")
        log_info(f"配置加载成功: {part_config.get('name')}")

        async with websockets.connect(uri) as ws:
            log_info("WebSocket 已连接")

            # 等待连接成功消息
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(response)
            log_recv(f"类型: {data.get('type')}")

            if data.get('type') == 'session_created':
                session_id = data.get('data', {}).get('session_id')
                log_info(f"会话创建成功: {session_id}")

            # 发送开始优化请求（模拟模式）
            start_msg = {
                "type": "start_optimization",
                "data": {
                    "part_config": part_config,
                    "algo_settings": {
                        "n_init": 3,  # 少量初始点快速测试
                        "n_iter": 1,
                        "batch_size": 2,
                        "mode": "auto",  # 模拟模式
                        "init_mode": "auto"
                    }
                }
            }
            await ws.send(json.dumps(start_msg))
            log_send(f"start_optimization: part=LS39860A-903, n_init=3, mode=auto")

            # 统计计数
            new_record_count = 0
            log_count = 0

            # 监听消息
            for i in range(100):  # 最多接收100条消息
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    data = json.loads(msg)
                    msg_type = data.get('type')

                    if msg_type == 'new_record':
                        new_record_count += 1
                        record = data.get('data', {}).get('record', {})
                        stage = record.get('stage')
                        form_error = record.get('form_error')
                        params = record.get('params', {})
                        param_summary = ', '.join([f"{k}={v}" for k, v in list(params.items())[:3]])
                        log_recv(f"new_record #{new_record_count}: stage={stage}, form_error={form_error:.4f}, params=[{param_summary}...]")

                    elif msg_type == 'log_message':
                        log_count += 1
                        level = data.get('data', {}).get('level', 'info')
                        message = data.get('data', {}).get('message', '')
                        # 显示所有日志（临时调试）
                        if 'new_record' in message or 'WebSocket' in message or '模拟' in message or '初始化' in message:
                            log_recv(f"log_message [{level}]: {message}")

                    elif msg_type == 'optimization_started':
                        log_recv(f"optimization_started")

                    elif msg_type == 'optimization_completed':
                        log_recv(f"optimization_completed")
                        log_info("优化完成!")
                        break

                    elif msg_type == 'state_update':
                        state = data.get('data', {})
                        all_records = state.get('all_records', [])
                        log_info(f"state_update: 当前共有 {len(all_records)} 条记录")

                    elif msg_type == 'error':
                        error_msg = data.get('data', {}).get('message', '未知错误')
                        log_error(f"服务器错误: {error_msg}")

                    elif msg_type in ['convergence_data', 'pong']:
                        # 忽略这些类型的消息
                        pass
                    else:
                        log_recv(f"{msg_type}")

                except asyncio.TimeoutError:
                    log_error("等待消息超时 (10秒)")
                    break

            # 总结
            log_info("=" * 50)
            log_info(f"测试总结:")
            log_info(f"  - 收到 new_record 消息: {new_record_count} 条")
            log_info(f"  - 收到日志消息: {log_count} 条")

            if new_record_count >= 3:
                log_info(f"{GREEN}✓ 测试通过: 后端正常发送 new_record 消息{RESET}")
            else:
                log_error(f"✗ 测试失败: 期望至少3条 new_record，实际收到 {new_record_count}")

    except websockets.exceptions.ConnectionClosed:
        log_error(f"WebSocket 连接被关闭")
        sys.exit(1)
    except OSError as e:
        log_error(f"无法连接到服务器，请确保服务器在运行: {uri} - {e}")
        sys.exit(1)
    except Exception as e:
        log_error(f"测试过程中出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_optimization())
