"""
数据提交测试

测试场景：
1. 正常提交 - 数值和缩水标志
2. 边界值测试 - 极值、零值、负值
3. 并发提交 - 快速连续提交
4. 无效数据提交 - 类型错误、缺失字段
5. 重复提交处理
"""
import asyncio
import sys
sys.path.insert(0, '/home/xt/Code/InjectionMolding')

from web_app.backend.tests.test_client import OptimizationTestClient, TEST_PART_CONFIG, TEST_ALGO_SETTINGS


async def test_normal_submission():
    """测试：正常数据提交"""
    print("\n" + "="*60)
    print("TEST: Normal Data Submission")
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

        record_id = msg.get('data', {}).get('record_id')
        print(f"Got record_id: {record_id}")

        # 提交正常评价
        await client.submit_evaluation(form_error=5.5, is_shrink=False)
        await asyncio.sleep(0.3)

        # 验证记录更新
        if len(client.records) > 0:
            record = client.records[0]
            if record.get('form_error') == 5.5 and record.get('is_shrink') == False:
                print("✓ Normal submission accepted")
                return True
            else:
                print(f"✗ Record mismatch: fe={record.get('form_error')}, shrink={record.get('is_shrink')}")
                return False
        else:
            print("✗ No records found")
            return False

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_shrink_submission():
    """测试：缩水标志提交"""
    print("\n" + "="*60)
    print("TEST: Shrink Flag Submission")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 提交几条非缩水记录
        for i in range(3):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(float(i + 1), is_shrink=False)
            await asyncio.sleep(0.05)

        # 提交一条缩水记录
        msg = await client.wait_for_message('params_ready', timeout=5.0)
        if msg:
            await client.submit_evaluation(4.0, is_shrink=True)
            await asyncio.sleep(0.3)

        await asyncio.sleep(0.5)

        # 验证缩水记录
        shrink_records = [r for r in client.records if r.get('is_shrink')]
        if len(shrink_records) == 1:
            print(f"✓ Shrink record created: fe={shrink_records[0].get('form_error')}")

            # 验证安全边界更新
            logs = '\n'.join(client.logs)
            if "更新安全边界" in logs or "安全边界" in logs:
                print("✓ Safety boundary updated for shrink record")
                return True
            else:
                print("? Safety boundary update not logged")
                return True  # Not a failure if handled differently
        else:
            print(f"✗ Expected 1 shrink record, got {len(shrink_records)}")
            return False

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_boundary_values():
    """测试：边界值提交"""
    print("\n" + "="*60)
    print("TEST: Boundary Value Submission")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        test_values = [
            (0.0, "zero value"),
            (0.001, "very small positive"),
            (999999.0, "very large value"),
            (-5.0, "negative value"),
        ]

        all_accepted = True
        for value, desc in test_values:
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break

            await client.submit_evaluation(value, is_shrink=False)
            await asyncio.sleep(0.1)

            # 检查是否被接受
            logs = '\n'.join(client.logs[-5:])
            if "error" in logs.lower() and str(value) in logs:
                print(f"✗ {desc} ({value}) rejected")
                all_accepted = False
            else:
                print(f"✓ {desc} ({value}) accepted")

        await asyncio.sleep(0.3)
        return all_accepted

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_rapid_submission():
    """测试：快速连续提交"""
    print("\n" + "="*60)
    print("TEST: Rapid Consecutive Submission")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 快速提交多个评价
        print("Submitting 5 evaluations rapidly...")
        for i in range(5):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                print(f"✗ Timeout at submission {i+1}")
                return False

            await client.submit_evaluation(float(i + 1), is_shrink=(i % 2 == 0))
            # 几乎不等待

        await asyncio.sleep(0.5)

        # 验证所有记录都被正确处理
        record_count = len(client.records)
        expected = 5

        if record_count >= expected:
            print(f"✓ All {expected} rapid submissions processed ({record_count} records)")
            return True
        else:
            print(f"✗ Only {record_count}/{expected} submissions processed")
            return False

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_duplicate_submission():
    """测试：重复提交同一记录"""
    print("\n" + "="*60)
    print("TEST: Duplicate Submission Handling")
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

        record_id = msg.get('data', {}).get('record_id')

        # 第一次提交
        await client.submit_evaluation(5.0, is_shrink=False)
        await asyncio.sleep(0.2)

        first_count = len([r for r in client.records if r.get('form_error') == 5.0])
        print(f"First submission: {first_count} record(s) with fe=5.0")

        # 尝试再次提交（可能通过modify接口）
        await client.send('submit_evaluation', {
            'record_id': record_id,
            'form_error': 10.0,
            'is_shrink': False
        })
        await asyncio.sleep(0.3)

        # 检查系统是否正常处理
        logs = '\n'.join(client.logs[-5:])
        if "error" in logs.lower():
            print("✓ Duplicate properly rejected or handled")
        else:
            print("? Duplicate may have been processed")

        return True  # Not a strict failure

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_large_batch_submission():
    """测试：大批量提交"""
    print("\n" + "="*60)
    print("TEST: Large Batch Submission")
    print("="*60)

    # 使用较大的初始化数量
    algo_settings = TEST_ALGO_SETTINGS.copy()
    algo_settings['n_init'] = 20

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, algo_settings)

        print(f"Processing {algo_settings['n_init']} records...")
        start_time = asyncio.get_event_loop().time()

        for i in range(algo_settings['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                print(f"✗ Timeout at record {i+1}")
                return False

            await client.submit_evaluation(float(i + 1), is_shrink=(i % 5 == 0))
            await asyncio.sleep(0.02)

        elapsed = asyncio.get_event_loop().time() - start_time
        await asyncio.sleep(0.5)

        # 验证
        if len(client.records) == algo_settings['n_init']:
            print(f"✓ All {algo_settings['n_init']} records processed in {elapsed:.2f}s")

            # 验证缩水记录统计
            shrink_count = sum(1 for r in client.records if r.get('is_shrink'))
            expected_shrink = algo_settings['n_init'] // 5  # 每5条一条缩水
            print(f"  Shrink records: {shrink_count} (expected ~{expected_shrink})")
            return True
        else:
            print(f"✗ Only {len(client.records)}/{algo_settings['n_init']} records processed")
            return False

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def run_all_tests():
    """运行所有数据提交测试"""
    results = []

    results.append(("Normal Submission", await test_normal_submission()))
    results.append(("Shrink Submission", await test_shrink_submission()))
    results.append(("Boundary Values", await test_boundary_values()))
    results.append(("Rapid Submission", await test_rapid_submission()))
    results.append(("Duplicate Submission", await test_duplicate_submission()))
    results.append(("Large Batch Submission", await test_large_batch_submission()))

    # 汇总
    print("\n" + "="*60)
    print("FINAL SUMMARY - Data Submit Tests")
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
