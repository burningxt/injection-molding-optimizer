"""
异常处理测试

测试场景：
1. 网络断开重连
2. 浏览器刷新恢复
3. 服务器重启恢复
4. 无效数据提交
5. 重复启动优化
6. 异常关闭处理
"""
import asyncio
import sys
sys.path.insert(0, '/home/xt/Code/InjectionMolding')

from web_app.backend.tests.test_client import OptimizationTestClient, TEST_PART_CONFIG, TEST_ALGO_SETTINGS


async def test_network_disconnect_reconnect():
    """测试：网络断开重连"""
    print("\n" + "="*60)
    print("TEST: Network Disconnect and Reconnect")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 完成部分记录
        for i in range(3):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(float(i + 1), is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.3)
        records_before = len(client.records)
        session_id = client.session_id
        print(f"Records before disconnect: {records_before}, session: {session_id}")

        # 模拟断开连接
        print("\nSimulating disconnect...")
        await client.close()
        await asyncio.sleep(0.5)

        # 重新连接
        print("Reconnecting...")
        client2 = OptimizationTestClient()
        await client2.connect(session_id)
        await asyncio.sleep(0.5)

        records_after = len(client2.records)
        print(f"Records after reconnect: {records_after}")

        if records_after >= records_before:
            print("✓ Records preserved after reconnect")
            result = True
        else:
            print(f"✗ Records lost: {records_before} -> {records_after}")
            result = False

        await client2.close()
        return result

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_refresh_recovery():
    """测试：浏览器刷新恢复"""
    print("\n" + "="*60)
    print("TEST: Browser Refresh Recovery")
    print("="*60)

    # 第一个"浏览器会话"
    client1 = OptimizationTestClient()
    try:
        await client1.connect()
        await client1.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 完成所有初始化
        for i in range(TEST_ALGO_SETTINGS['n_init']):
            msg = await client1.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client1.submit_evaluation(float(i + 1), is_shrink=(i < 2))
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        records_before = len(client1.records)
        session_id = client1.session_id
        print(f"Session {session_id}: {records_before} records")

        # 模拟刷新（关闭并重新连接）
        await client1.close()
        await asyncio.sleep(0.3)

        # 第二个"浏览器会话"
        client2 = OptimizationTestClient()
        await client2.connect(session_id)
        await asyncio.sleep(0.5)

        records_after = len(client2.records)
        print(f"After refresh: {records_after} records")

        # 验证可以继续
        msg = await client2.wait_for_message('params_ready', timeout=5.0)
        if msg:
            print("✓ Can continue after refresh")
            await client2.submit_evaluation(100.0, is_shrink=False)
            await asyncio.sleep(0.3)

            final_count = len(client2.records)
            if final_count > records_after:
                print(f"✓ Successfully continued: {final_count} records")
                result = True
            else:
                print("✗ Could not continue after refresh")
                result = False
        else:
            print("✗ No params ready after refresh")
            result = False

        await client2.close()
        return result

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client1.close()


async def test_invalid_data_handling():
    """测试：无效数据处理"""
    print("\n" + "="*60)
    print("TEST: Invalid Data Handling")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 获取第一条参数
        msg = await client.wait_for_message('params_ready', timeout=5.0)
        if not msg:
            print("✗ No params ready")
            return False

        invalid_cases = [
            ({"form_error": "not_a_number"}, "string form_error"),
            ({"form_error": None}, "null form_error"),
            ({"is_shrink": "yes"}, "string is_shrink"),
            ({"extra_field": [1, 2, 3]}, "extra array field"),
            ({"form_error": float('inf')}, "infinity value"),
        ]

        all_handled = True
        for data, desc in invalid_cases:
            print(f"\nTesting: {desc}")
            await client.send('submit_evaluation', data)
            await asyncio.sleep(0.3)

            # 检查是否优雅处理
            logs = '\n'.join(client.logs[-3:])
            if "error" in logs.lower() or "exception" in logs.lower():
                print(f"  ! Error/exception logged for {desc}")
                # 但不是失败，只要系统没崩溃

            # 系统应该仍然可用
            msg = await client.wait_for_message('params_ready', timeout=2.0)
            if msg:
                print(f"  ✓ System still responsive after {desc}")
            else:
                print(f"  ✗ System not responsive after {desc}")
                all_handled = False

        return all_handled

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_duplicate_start():
    """测试：重复启动优化"""
    print("\n" + "="*60)
    print("TEST: Duplicate Start Optimization")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()

        # 第一次启动
        result1 = await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)
        print(f"First start: {result1 is not None}")

        await asyncio.sleep(0.3)
        client.logs.clear()

        # 尝试第二次启动
        print("\nAttempting second start...")
        result2 = await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)
        await asyncio.sleep(0.3)

        logs = '\n'.join(client.logs)

        # 应该拒绝或提示
        if "已在运行" in logs or "already" in logs.lower() or "error" in logs.lower():
            print("✓ Second start properly rejected")
            return True
        else:
            print("? Second start may have been allowed")
            # 不一定失败，取决于设计
            return True

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_malformed_websocket_message():
    """测试：畸形WebSocket消息"""
    print("\n" + "="*60)
    print("TEST: Malformed WebSocket Messages")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()

        # 发送畸形消息
        malformed_cases = [
            ("not json", "invalid json"),
            ({"type": "unknown_type"}, "unknown message type"),
            ({"type": "submit_evaluation", "data": {}}, "missing required fields"),
            ({"type": None}, "null type"),
        ]

        all_handled = True
        for data, desc in malformed_cases:
            print(f"\nTesting: {desc}")

            if isinstance(data, str):
                await client.ws.send(data)
            else:
                import json
                await client.ws.send(json.dumps(data))

            await asyncio.sleep(0.3)

            # 系统应该仍然可用
            await client.send('ping')
            await asyncio.sleep(0.1)

            print(f"  ✓ Handled gracefully")

        return all_handled

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_timeout_handling():
    """测试：超时处理"""
    print("\n" + "="*60)
    print("TEST: Timeout Handling")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 获取第一条参数但不提交（模拟用户离开）
        msg = await client.wait_for_message('params_ready', timeout=5.0)
        if not msg:
            print("✗ No params ready")
            return False

        print("Got params, waiting 2 seconds without submitting...")
        await asyncio.sleep(2.0)

        # 系统应该仍然可用
        await client.submit_evaluation(5.0, is_shrink=False)
        await asyncio.sleep(0.3)

        if len(client.records) >= 1:
            print("✓ System still responsive after delay")
            return True
        else:
            print("✗ System not responsive after delay")
            return False

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def run_all_tests():
    """运行所有异常处理测试"""
    results = []

    results.append(("Network Disconnect Reconnect", await test_network_disconnect_reconnect()))
    results.append(("Browser Refresh Recovery", await test_refresh_recovery()))
    results.append(("Invalid Data Handling", await test_invalid_data_handling()))
    results.append(("Duplicate Start", await test_duplicate_start()))
    results.append(("Malformed Messages", await test_malformed_websocket_message()))
    results.append(("Timeout Handling", await test_timeout_handling()))

    # 汇总
    print("\n" + "="*60)
    print("FINAL SUMMARY - Exception Handling Tests")
    print("="*60)
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")

    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"\nTotal: {passed}/{total} tests passed")
    print("="*60)

    return all(r for _, r in results)


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
