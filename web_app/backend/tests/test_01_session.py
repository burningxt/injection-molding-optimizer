"""
会话管理测试

测试场景：
1. 创建新会话 - 验证session_id生成和初始化状态
2. 加载历史会话 - 验证checkpoint恢复
3. 会话隔离 - 多个会话数据不混淆
4. 历史记录恢复 - 重启后正确加载
"""
import asyncio
import sys
sys.path.insert(0, '/home/xt/Code/InjectionMolding')

from test_client import OptimizationTestClient, TEST_PART_CONFIG, TEST_ALGO_SETTINGS


async def test_create_new_session():
    """测试：创建新会话"""
    print("\n" + "="*60)
    print("TEST: Create New Session")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await asyncio.sleep(0.3)

        # 验证session_id生成
        if not client.session_id:
            print("✗ FAIL: No session_id generated")
            return False

        print(f"✓ Session ID: {client.session_id}")

        # 验证初始状态
        if len(client.records) == 0:
            print("✓ Initial records empty")
        else:
            print(f"! Unexpected records: {len(client.records)}")

        # 验证日志
        if client.has_log_pattern("已连接到会话"):
            print("✓ Connection log found")
            return True
        else:
            print("✗ Connection log not found")
            return False

    finally:
        await client.close()


async def test_session_isolation():
    """测试：会话隔离 - 多个会话数据不混淆"""
    print("\n" + "="*60)
    print("TEST: Session Isolation")
    print("="*60)

    # 创建两个独立会话
    client1 = OptimizationTestClient()
    client2 = OptimizationTestClient()

    try:
        # 会话1：添加一些记录
        await client1.connect()
        await client1.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)
        for i in range(3):
            await client1.wait_for_message('params_ready', timeout=5.0)
            await client1.submit_evaluation(float(i+1), is_shrink=False)
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)

        session1_id = client1.session_id
        session1_records = len(client1.records)
        print(f"Session 1: {session1_id} with {session1_records} records")

        # 会话2：独立运行
        await client2.connect()
        await client2.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)
        for i in range(5):
            await client2.wait_for_message('params_ready', timeout=5.0)
            await client2.submit_evaluation(float(i+10), is_shrink=True)
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)

        session2_id = client2.session_id
        session2_records = len(client2.records)
        print(f"Session 2: {session2_id} with {session2_records} records")

        # 验证会话ID不同
        if session1_id == session2_id:
            print("✗ FAIL: Same session ID")
            return False
        print("✓ Different session IDs")

        # 验证记录不混淆
        # 重新连接会话1
        client1_reconnect = OptimizationTestClient()
        await client1_reconnect.connect(session1_id)
        await asyncio.sleep(0.3)

        if len(client1_reconnect.records) == session1_records:
            print(f"✓ Session 1 records isolated: {len(client1_reconnect.records)}")
        else:
            print(f"✗ Session 1 records mismatch: expected {session1_records}, got {len(client1_reconnect.records)}")
            return False

        await client1_reconnect.close()

        # 重新连接会话2
        client2_reconnect = OptimizationTestClient()
        await client2_reconnect.connect(session2_id)
        await asyncio.sleep(0.3)

        if len(client2_reconnect.records) == session2_records:
            print(f"✓ Session 2 records isolated: {len(client2_reconnect.records)}")
        else:
            print(f"✗ Session 2 records mismatch: expected {session2_records}, got {len(client2_reconnect.records)}")
            return False

        # 验证会话2有缩水记录，会话1没有
        shrink_count_1 = sum(1 for r in client1_reconnect.records if r.get('is_shrink'))
        shrink_count_2 = sum(1 for r in client2_reconnect.records if r.get('is_shrink'))

        if shrink_count_1 == 0 and shrink_count_2 > 0:
            print(f"✓ Shrink records correctly isolated (s1: {shrink_count_1}, s2: {shrink_count_2})")
            return True
        else:
            print(f"✗ Shrink records not isolated (s1: {shrink_count_1}, s2: {shrink_count_2})")
            return False

    finally:
        await client1.close()
        await client2.close()


async def test_session_persistence():
    """测试：会话持久化 - 保存退出后恢复"""
    print("\n" + "="*60)
    print("TEST: Session Persistence")
    print("="*60)

    client = OptimizationTestClient()
    try:
        # 创建会话并添加数据
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        for i in range(5):
            await client.wait_for_message('params_ready', timeout=5.0)
            await client.submit_evaluation(float(i+1), is_shrink=(i % 2 == 0))
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.3)
        original_records = len(client.records)
        original_session_id = client.session_id
        print(f"Created {original_records} records in session {original_session_id}")

        # 保存退出
        await client.save_and_exit()
        await asyncio.sleep(0.3)

        # 完全断开
        await client.close()
        await asyncio.sleep(0.5)

        # 重新连接
        client2 = OptimizationTestClient()
        await client2.connect(original_session_id)
        await asyncio.sleep(0.5)

        # 验证恢复
        restored_records = len(client2.records)
        print(f"Restored {restored_records} records")

        if restored_records >= original_records:
            print(f"✓ All records restored ({original_records} -> {restored_records})")
        else:
            print(f"✗ Records lost: {original_records} -> {restored_records}")
            return False

        # 验证数据完整性
        restored_shrink = sum(1 for r in client2.records if r.get('is_shrink'))
        expected_shrink = sum(1 for r in client.records if r.get('is_shrink'))

        if restored_shrink == expected_shrink:
            print(f"✓ Shrink flags preserved ({restored_shrink})")
            return True
        else:
            print(f"✗ Shrink flags mismatch: expected {expected_shrink}, got {restored_shrink}")
            return False

    finally:
        await client.close()


async def run_all_tests():
    """运行所有会话测试"""
    results = []

    results.append(("Create New Session", await test_create_new_session()))
    results.append(("Session Isolation", await test_session_isolation()))
    results.append(("Session Persistence", await test_session_persistence()))

    # 汇总
    print("\n" + "="*60)
    print("FINAL SUMMARY - Session Tests")
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
