# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
import re
from pathlib import Path

# =========================
# 工具函数
# =========================
def normalize_col(c: str) -> str:
    """清洗列名：去全角空格、合并多空格。"""
    c = str(c).strip().replace("\u3000", " ")
    c = re.sub(r"\s+", " ", c)
    return c

def normalize_group(v) -> str | float:
    """把任意类似 'A 1' / 't-12' 标准化为 'A1' / 'T12'，否则 NaN。"""
    s = str(v).strip()
    m = re.search(r"([AaTt])\s*(\d{1,3})", s)
    return f"{m.group(1).upper()}{int(m.group(2))}" if m else np.nan

def norm_surface(x: str) -> str:
    """把面别标准化为 S1 / S2（去空格/连字符并大写）。"""
    return str(x).strip().upper().replace(" ", "").replace("-", "")

def group_sort_key(g: str):
    """排序键：先 A 再 T，数值从小到大。"""
    m = re.match(r"([AT])(\d+)$", g)
    return (0 if m and m.group(1) == "A" else 1,
            int(m.group(2)) if m else 999)

def detect_hole_col(df: pd.DataFrame) -> str | None:
    """
    常见列名关键词：穴、孔、孔位、点位、点号、位置、测点、hole、Hole。
    命中多个时取得分最高者；若均无则返回 None。
    """
    hole_keywords = ["穴", "孔", "孔位", "点位", "点号", "位置", "测点", "hole", "Hole", "HOLE", "spot", "Spot"]
    candidates = []
    for c in df.columns:
        lc = str(c).lower()
        score = 0
        if any(k.lower() in lc for k in hole_keywords):
            score += 2
        # 该列若主要是 1~200 的小整数/短标签（如 H1/H02/01），再加分
        s = df[c].astype(str).str.strip()
        is_small_int = pd.to_numeric(s, errors="coerce").between(1, 200).fillna(False)
        looks_like_tag = s.str.match(r"^[A-Za-z]?\d{1,3}$").fillna(False)
        score += is_small_int.mean() * 3 + looks_like_tag.mean() * 2
        candidates.append((c, score))
    candidates.sort(key=lambda x: x[1], reverse=True)
    if candidates and candidates[0][1] > 0:
        return candidates[0][0]
    return None

def calculate_gated_fitness(row):
    """层级化（Gated）Fitness 计算"""
    PV_GATE = 0.5
    pv = row.get("PV", np.nan)
    mae = row.get("MAE", np.nan)
    sym = row.get("SYM", np.nan)
    sui = row.get("SUI", np.nan)
    
    if pd.isna(pv):
        return np.nan
        
    # 坏区 (PV > Gate)
    if pv > PV_GATE:
        return 30.0 + 10.0 * pv
        
    # 好区 (PV <= Gate)
    else:
        return 10 * mae + 10 * sym + 20 * pv + 1 * (sui - 1.5)

def run_fitness_calculation(input_path: str | Path, output_path: str | Path):
    """核心计算逻辑封装"""
    input_path = Path(input_path)
    output_path = Path(output_path)
    
    # 1) 读取所有工作表并合并
    sheets = pd.read_excel(input_path, sheet_name=None)
    raw = pd.concat([df.assign(__sheet__=sn) for sn, df in sheets.items()], ignore_index=True)
    raw.columns = [normalize_col(c) for c in raw.columns]

    # 2) 识别组别列（A.. / T..）
    group_name_keywords = ["组", "Group", "group", "分组", "样本", "编号", "名称",
                           "镜片组", "label", "id", "ID", "Name", "name", "备注"]

    candidate_group_cols = []
    for c in raw.columns:
        score = 0
        if any(k.lower() in str(c).lower() for k in group_name_keywords):
            score += 2
        vals = raw[c].astype(str).str.strip()
        score += vals.str.contains(r"^[AaTt]\s*\d{1,3}$").fillna(False).mean() * 5
        candidate_group_cols.append((c, score))

    candidate_group_cols.sort(key=lambda x: x[1], reverse=True)
    if not candidate_group_cols or candidate_group_cols[0][1] == 0:
        raise RuntimeError("未能自动识别到组别列。")

    group_col = candidate_group_cols[0][0]
    raw["__group__"] = raw[group_col].apply(normalize_group)

    # ——动态保留所有 A/T 组——
    data = raw[raw["__group__"].str.match(r"^[AT]\d{1,3}$", na=False)].copy()
    if data.empty:
        raise RuntimeError("按组别正则 ^[AT]\\d{1,3}$ 过滤后，没有任何有效组别数据。")

    # 3) 识别“面别”列（S1 / S2）并标准化
    surface_col = next(
        (c for c in data.columns if any(k in str(c) for k in ["面别", "面", "surface", "Surface"])),
        None
    )
    if not surface_col:
        raise RuntimeError("未找到表示 S1/S2 的‘面别’列。")

    data["__surface__"] = data[surface_col].apply(norm_surface)
    data = data[data["__surface__"].isin(["S1", "S2"])].copy()
    if data.empty:
        raise RuntimeError("面别筛选后没有 S1/S2 数据。")

    # 4) 识别 MAE / SYM / PV / SUI 列并计算 F
    metric_cols: dict[str, str] = {}
    for c in data.columns:
        lc = str(c).strip().lower()
        if lc == "mae": metric_cols["MAE"] = c
        elif lc in ("sym", "symmetry", "对称"): metric_cols["SYM"] = c
        elif lc == "pv": metric_cols["PV"] = c
        elif lc in ("sui", "舒适度", "sui值"): metric_cols["SUI"] = c

    missing = [k for k in ["MAE", "SYM", "PV", "SUI"] if k not in metric_cols]
    if missing:
        raise RuntimeError(f"缺少列: {missing}")

    for k, col in metric_cols.items():
        data[k] = pd.to_numeric(data[col], errors="coerce")

    data["F"] = data.apply(calculate_gated_fitness, axis=1)

    # 5) “代表值”计算
    hole_col = detect_hole_col(data)

    def surface_mean_with_holes(df_gs: pd.DataFrame) -> float:
        if hole_col and hole_col in df_gs.columns:
            per_hole = (
                df_gs.groupby(df_gs[hole_col].astype(str).str.strip(), dropna=True)["F"]
                     .mean()
                     .dropna()
                     .to_frame("F_mean")
                     .reset_index()
            )
            n = len(per_hole)
            if n == 0: return np.nan
            per_hole = per_hole.sort_values("F_mean", ascending=True).reset_index(drop=True)
            if n >= 4:
                per_hole = per_hole.iloc[:-1, :]
                return per_hole.head(3)["F_mean"].mean()
            else:
                return per_hole["F_mean"].mean()
        else:
            return df_gs["F"].mean()

    by_surface_mean_list = []
    for (g, s), sub in data.groupby(["__group__", "__surface__"]):
        f_mean = surface_mean_with_holes(sub)
        by_surface_mean_list.append({"__group__": g, "__surface__": s, "平均F": f_mean})

    by_surface_mean = pd.DataFrame(by_surface_mean_list)
    
    all_groups_in_data = sorted(data["__group__"].unique(), key=group_sort_key)
    s1_groups = set(by_surface_mean[by_surface_mean["__surface__"] == "S1"]["__group__"])
    s2_groups = set(by_surface_mean[by_surface_mean["__surface__"] == "S2"]["__group__"])
    missing_s1 = sorted(list(set(all_groups_in_data) - s1_groups), key=group_sort_key)
    missing_s2 = sorted(list(set(all_groups_in_data) - s2_groups), key=group_sort_key)

    pivot = by_surface_mean.pivot(index="__group__", columns="__surface__", values="平均F").reset_index()
    pivot = pivot.rename(columns={"__group__": "组别", "S1": "S1(代表均值)", "S2": "S2(代表均值)"})

    if "S1(代表均值)" not in pivot.columns: pivot["S1(代表均值)"] = np.nan
    if "S2(代表均值)" not in pivot.columns: pivot["S2(代表均值)"] = np.nan

    pivot["S1(代表均值)"] = pivot["S1(代表均值)"].fillna(pivot["S2(代表均值)"])
    pivot["S2(代表均值)"] = pivot["S2(代表均值)"].fillna(pivot["S1(代表均值)"])
    pivot["代表值(S1均值+S2均值)"] = pivot["S1(代表均值)"] + pivot["S2(代表均值)"]
    pivot = pivot.sort_values(by="组别", key=lambda s: s.map(group_sort_key)).reset_index(drop=True)

    # 6) 导出
    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        pivot.to_excel(writer, index=False, sheet_name="代表值")

    all_groups = sorted(g for g in raw["__group__"].dropna().unique())
    
    return {
        "识别的组别列": group_col,
        "识别的面别列": surface_col,
        "识别的穴位列": hole_col if hole_col else "未识别，已回退为按行平均",
        "总行数": int(len(raw)),
        "识别到的组别数量": int(len(all_groups)),
        "导出行数(组数)": int(len(pivot)),
        "缺失S1并用S2补齐的组别": missing_s1,
        "缺失S2并用S1补齐的组别": missing_s2,
    }

if __name__ == "__main__":
    # 默认运行参数
    IN_XLSX  = Path("第1批次.xlsx")
    OUT_XLSX = Path("代表值_S1均值+S2均值_第1批次.xlsx")
    
    if IN_XLSX.exists():
        res = run_fitness_calculation(IN_XLSX, OUT_XLSX)
        print("计算完成！")
        print(res)
    else:
        print(f"未找到输入文件: {IN_XLSX}")
