"""
测试函数模块 - 包含仿真函数和保压临界值计算
"""

import math
import random
from typing import Tuple

# 默认物理常数 (Fallback)
DEFAULT_TC = 16.0
DEFAULT_F = 8.0
DEFAULT_T_PACK = [2.0, 1.0, 0.5, 0.5]

def critical_ph1_for_shrink(Tm: float) -> float:
    """
    给定模温 Tm（℃），返回"容易缩水的临界一段保压" Ph_crit（bar）。
    
    线性模型：
      Ph_crit(Tm) = 450 + 5 * (138 - Tm)
    
      Tm=135 → 465
      Tm=138 → 450
      Tm=141 → 435
      Tm=143 → 425
    
    再夹到 [420, 480]，避免太极端。
    
    Args:
        Tm: 模温（℃）
        
    Returns:
        临界保压值（bar）
    """
    Tm_ref = 138.0
    Ph_ref = 450.0
    slope = 5.0  # 每度 5 bar

    Ph_crit = Ph_ref + slope * (Tm_ref - Tm)
    Ph_crit = max(420.0, min(480.0, Ph_crit))
    return Ph_crit


def simulate_form_error_part_a(
    Tm: float,
    Pv: float,
    Ph: float,
    delay_time: float,
    V1: float,
    V2: float,
    V3: float,
    V4: float,
    V5: float,
    Tc: float = DEFAULT_TC,
    F: float = DEFAULT_F,
    noise_std: float = 0.0,
) -> float:
    """
    仿真"面型综合误差" FormError，数值越小越好。
    
    Args:
        Tm: 模温（℃）
        Pv: V-P压（bar）
        Ph: 保压压力（bar）
        delay_time: 延时时间（s）
        V1-V5: 5段射速（mm/s）
        Tc: 冷却时间 (s)
        F: 锁模力 (T)
        noise_std: 噪声标准差
        
    Returns:
        面型综合误差值
    """
    
    # 1. 基础物理项 (PV Component)
    # 假设最佳点附近：Tm=139, Pv=900, Ph=400
    PV_component = (
        0.002   * (Tm  - 139) ** 2 +
        0.00001 * (Pv  - 900) ** 2 +
        0.00001 * (Ph  - 400) ** 2
    )

    # 2. 射速单因子惩罚
    # 假设中速 25-30 是比较好的区间
    E_speed = (
        0.002 * (V1 - 25) ** 2 +
        0.002 * (V2 - 25) ** 2 +
        0.002 * (V3 - 30) ** 2 +
        0.002 * (V4 - 30) ** 2 +
        0.002 * (V5 - 30) ** 2
    )

    # 3. 延时时间惩罚
    # 假设最佳延时是 0.5s
    E_delay = 0.1 * (delay_time - 0.5) ** 2

    # 4. 耦合项
    
    # VP 与 最后一段射速(模拟剪口速度) 耦合
    # V5 越大，所需的切换压力可能越小
    # Pv_opt = 900 + (30 - V5) * 5
    Pv_opt = 900 + (30 - V5) * 5
    E_couple_VP_V5 = 0.00002 * (Pv - Pv_opt) ** 2

    # 模温 × 冷却时间 (Tc 变动)
    # Tc 越短，对 Tm 的限制越严
    # 如果 Tc=16，Tm>142 有惩罚；如果 Tc=15，Tm>140 可能就有惩罚
    # 简单的物理关联：需要的最小冷却时间 Tc_min = k * (Tm - T_eject) ... 简化为
    # 惩罚 = max(0, Tm - Threshold(Tc))
    # 假设 Tc=16 -> Th=142; Tc=15 -> Th=140
    # Th = 142 + (Tc - 16) * 2 = 110 + 2*Tc
    Th_Tm = 110 + 2 * Tc
    E_couple_Tm_Tc = 0.01 * max(0, Tm - Th_Tm) 

    # 锁模力 × 保压
    # F固定 (8T or 15T)，保压 Ph 变动。
    # 15T 能承受更大的保压。
    # 假设承压能力 P_limit = 450 * (F / 8.0)
    P_limit = 450 * (F / 8.0)
    E_couple_F_Ph = 0.0001 * max(0, Ph - P_limit) ** 2

    # 平均射速
    V_mean = (V1 + V2 + V3 + V4 + V5) / 5.0
    E_couple_Vmean = 0.001 * (V_mean - 28) ** 2

    E_couples = (
        E_couple_VP_V5 +
        E_couple_Tm_Tc +
        E_couple_F_Ph +
        E_couple_Vmean
    )

    # 5. 多局部最优高斯坑 (Multimodal)
    # 制造一些波折，测试优化器能力
    
    # Basin 1: 低压高速区
    E_basin1 = -0.3 * math.exp(
        - ((Tm  - 140) ** 2 / 5 +
           (Pv  - 800) ** 2 / 10000 +
           (V_mean - 35) ** 2 / 50)
    )

    # Basin 2: 高压低速区
    E_basin2 = -0.2 * math.exp(
        - ((Tm - 138) ** 2 / 5 +
           (Pv - 1100) ** 2 / 10000 +
           (V_mean - 20) ** 2 / 50)
    )

    E_multimodal = E_basin1 + E_basin2

    # 6. 缩水惩罚 (Shrinkage)
    Ph_crit = critical_ph1_for_shrink(Tm)
    if Ph < Ph_crit:
        delta = Ph_crit - Ph
        # 指数惩罚
        E_shrink = 0.5 * (math.exp(0.02 * delta) - 1.0)
    else:
        E_shrink = 0.0

    # 总误差
    FormError = 0.5 + PV_component + E_speed + E_delay + E_couples + E_multimodal + E_shrink

    if noise_std > 0:
        FormError += random.gauss(0, noise_std)

    return FormError


# ===========================
# Configuration B (New)
# ===========================

# 默认固定参数 (供 Config B 使用)
G_FIXED  = 40
V1_FIXED = 30
V4_FIXED = 30
V5_FIXED = 30
t1_FIXED = 1.6
t2_FIXED = 1.6
t3_FIXED = 0.4
t4_FIXED = 0.4
Tc_FIXED = 15
F_FIXED  = 15

def simulate_form_error_part_b(
    Tm, Pv, Ph1, Vg,
    G,                # 二级参数：保压递减梯度
    V1, V4, V5,
    t1, t2, t3, t4,
    Tc, F,
    noise_std: float = 0.0,
) -> float:
    """
    仿真"面型综合误差" FormError (Config B)，数值越小越好。
    """
    sg = 0 if Vg == 5 else 1  # 剪口模式：0=低速，1=高速

    # PV 子成分
    PV_component = (
        0.002   * (Tm  - 139) ** 2 +
        0.00001 * (Pv  - 900) ** 2 +
        0.00001 * (Ph1 - 600) ** 2 +
        0.0004  * (G   - 40) ** 2
    )

    # 单因子惩罚
    E_single = (
        0.005   * (V1  - 30) ** 2 +
        0.005   * (V4  - 30) ** 2 +
        0.005   * (V5  - 30) ** 2 +
        0.05    * (t1  - 1.6) ** 2 +
        0.05    * (t2  - 1.6) ** 2 +
        0.2     * (t3  - 0.4) ** 2 +
        0.2     * (t4  - 0.4) ** 2 +
        0.01    * (Tc  - 15) ** 2 +
        0.02    * (F   - 15) ** 2
    )

    # V-P × 剪口速度 耦合
    Pv_opt = 900 + 60 * (0.5 - sg)  # Vg=5 → 930, Vg=30 → 870
    E_couple_VP_gate = 0.00003 * (Pv - Pv_opt) ** 2

    # 模温 × 冷却时间
    E_couple_Tm_Tc = 0.001 * max(0, (Tm - 138)) * max(0, (15 - Tc))

    # 一段保压 × 梯度
    E_couple_Ph1_G = 0.000002 * max(0, Ph1 - 600) * max(0, G - 40)

    # 锁模力 × 一段保压
    E_couple_F_Ph1 = 0.00001 * max(0, 600 - F * 40) * max(0, Ph1 - 600)

    # 平均射速 × 剪口模式
    V_mean = (V1 + V4 + V5) / 3.0
    V_mean_opt = 30 + (sg - 0.5) * 10  # sg=0→25, sg=1→35
    E_couple_Vmean = 0.002 * (V_mean - V_mean_opt) ** 2

    E_couples = (
        E_couple_VP_gate +
        E_couple_Tm_Tc +
        E_couple_Ph1_G +
        E_couple_F_Ph1 +
        E_couple_Vmean
    )

    # 多局部最优高斯坑
    E_basin1 = -0.5 * math.exp(
        - ((Tm  - 140) ** 2 / 4 +
           (Pv  - 1050) ** 2 / 20000 +
           (Ph1 - 650) ** 2 / 5000)
    )

    E_basin2 = -0.4 * math.exp(
        - ((Tm - 137) ** 2 / 4 +
           (Tc - 15) ** 2 / 4 +
           (10 * sg) ** 2 / 10)
    )

    E_basin3 = -0.3 * math.exp(
        - ((Pv - 870) ** 2 / 15000 +
           (V1 - 40) ** 2 / 20 +
           (V5 - 40) ** 2 / 20)
    )

    E_multimodal = E_basin1 + E_basin2 + E_basin3

    # Tm 相关的缩水惩罚（仿真内部仍保留）
    Ph1_crit = critical_ph1_for_shrink(Tm)
    if Ph1 < Ph1_crit:
        delta = Ph1_crit - Ph1
        E_shrink = 0.5 * (math.exp(0.02 * delta) - 1.0)
    else:
        E_shrink = 0.0

    FormError = 0.5 + PV_component + E_single + E_couples + E_multimodal + E_shrink

    if noise_std > 0:
        FormError += random.gauss(0, noise_std)

    return FormError


def simulate_form_error_validation(
    Tm: float,
    Pv: float,
    Ph: float,
    Vg: float,
    noise_std: float = 0.0
) -> float:
    """
    验证算法专用测试函数。
    
    特性：
    1. 全局最优: T=138, Pv=960, Ph=530, Vg=5 -> Fitness ≈ 10
    2. 局部最优: T=136, Pv=630, Ph=570, Vg=5 -> Fitness ≈ 25
    3. 缩水逻辑: 只要 Ph 低于当前 T 的下限，Fitness > 100
    4. Vg影响: Vg=30 比 Vg=5 差，且在优良区域(Fitness小)差异更明显
    """
    
    # --- 1. 缩水判定 ---
    # 定义温度对应的保压下限
    shrink_limits = {
        135: 590,
        136: 560,
        137: 530,
        138: 500,
        139: 490,
        140: 480,
        141: 470
    }
    
    # 获取当前温度的下限 (简单的最近邻或直接查表，假设输入T是整数或接近整数)
    t_key = round(Tm)
    limit = shrink_limits.get(t_key, 470) # 默认470
    
    # 如果保压不足，直接返回异常大的值
    if Ph < limit:
        # 基础惩罚 100 + 差值 * 系数
        return 120.0 + (limit - Ph) * 0.5

    # --- 2. 正常成型区域 (Multimodal) ---
    
    # Basin 1: 全局最优 (T=138, Pv=960, Ph=530)
    # 权重调整：T敏感度高，压力敏感度低
    f1 = 10.0 + \
         2.0 * (Tm - 137)**2 + \
         0.0005 * (Pv - 960)**2 + \
         0.0005 * (Ph - 530)**2

    # Basin 2: 局部最优 (T=136, Pv=630, Ph=570)
    # 稍差一些，基准值 25.0
    f2 = 25.0 + \
         3.0 * (Tm - 136)**2 + \
         0.0005 * (Pv - 630)**2 + \
         0.0005 * (Ph - 570)**2
         
    # 取两个盆地的最小值作为基础得分
    base_score = min(f1, f2)
    
    # --- 3. Vg (剪口速度) 影响 ---
    # "同等工艺下，Vg=5 优于 Vg=30，Fitness越小越明显"
    # 实现：添加一个与当前分数成反比的惩罚项
    # 当 base_score = 10 (最优) 时，惩罚大；当 base_score = 80 (差) 时，惩罚小
    
    vg_penalty = 0.0
    if abs(Vg - 30) < 1e-3: # Vg == 30
        # 这里的系数 300 是调节强度的
        # At base=10: penalty = 300/10 = 30 -> Total 40 (明显变差)
        # At base=80: penalty = 300/80 = 3.75 -> Total 83.75 (不太明显)
        vg_penalty = 300.0 / (base_score + 1e-6)
    
    final_score = base_score + vg_penalty
    
    # 添加噪声
    if noise_std > 0:
        final_score += random.gauss(0, noise_std)
        
    return final_score
