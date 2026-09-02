"""Demo2：数据分析 + 可视化

功能链路：读取 CSV → 描述性统计（max/min/mean）→ 柱状图 + 折线图 → 导出 PNG
"""
import os
import matplotlib
# 非交互式后端：脚本直接保存图片，不弹窗（必须在 import pyplot 之前）
matplotlib.use("Agg")
# 中文字体 + 负号修复
matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
matplotlib.rcParams["axes.unicode_minus"] = False

import matplotlib.pyplot as plt
import pandas as pd

OUT_DIR = "charts"


def load_data(path):
    """读取 CSV 文件。"""
    df = pd.read_csv(path)
    # 排除非数值列（球员、球队），自动识别数值列
    return df


def compute_stats(df):
    """计算数值列的最大值、最小值、平均值，返回 DataFrame。"""
    numeric_cols = df.select_dtypes(include="number").columns
    stats = pd.DataFrame(
        {
            "max": df[numeric_cols].max(),
            "min": df[numeric_cols].min(),
            "mean": df[numeric_cols].mean(),
        }
    )
    # 平均值保留 2 位小数
    stats["mean"] = stats["mean"].round(2)
    return stats


def plot_bar(stats, out_path):
    """柱状图：NBA球员核心数据均值对比。"""
    fig, ax = plt.subplots(figsize=(8, 5))
    # 只统计得分/篮板/助攻三项核心数据，不包含总效率
    core_stats = stats.loc[["得分", "篮板", "助攻"]]
    ax.bar(core_stats.index, core_stats["mean"], color=["#5B9BD5", "#ED7D31", "#A5A5A5"])
    ax.set_title("NBA球员核心数据均值对比")
    ax.set_xlabel("数据项")
    ax.set_ylabel("数值")
    ax.set_ylim(0, 45)
    # 柱顶标数值
    for i, v in enumerate(core_stats["mean"]):
        ax.text(i, v + 0.5, f"{v}", ha="center", va="bottom")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_line(df, out_path):
    """折线图：按总效率降序排列的NBA球员排名。"""
    fig, ax = plt.subplots(figsize=(8, 5))
    # 按总效率降序
    sorted_df = df.sort_values("总效率", ascending=False).reset_index(drop=True)
    ax.plot(sorted_df["球员"], sorted_df["总效率"], marker="o", color="#4472C4", linewidth=2)
    ax.set_title("NBA球员总效率排名")
    ax.set_xlabel("球员（按总效率降序）")
    ax.set_ylabel("总效率")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def print_summary(stats):
    """控制台打印统计摘要。"""
    print("=" * 50)
    print("📊 Demo2 数据分析统计结果")
    print("=" * 50)
    print(stats.to_string())
    print("=" * 50)


def main():
    data_path = "data_student.csv"
    # 异常捕获：文件不存在
    try:
        df = load_data(data_path)
    except FileNotFoundError:
        print(f"[友好提示] 数据文件不存在: {data_path}")
        return

    stats = compute_stats(df)
    print_summary(stats)

    # 确保输出目录存在
    os.makedirs(OUT_DIR, exist_ok=True)

    bar_path = os.path.join(OUT_DIR, "bar_subject_avg.png")
    line_path = os.path.join(OUT_DIR, "line_total_score.png")

    plot_bar(stats, bar_path)
    plot_line(df, line_path)

    print(f"✅ 柱状图已保存: {bar_path}")
    print(f"✅ 折线图已保存: {line_path}")


if __name__ == "__main__":
    main()
