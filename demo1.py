"""Demo1: 文件数据处理小脚本

功能链路：读取 txt/csv → 文本清洗 → 关键词统计 → 写出结果文件
异常策略：文件不存在等错误以友好提示退出，不崩溃
"""
import csv
from pathlib import Path

# 预定义关键词：可自行增删，脚本会统计它们在文本中的出现次数
KEYWORDS = ["python", "数据", "处理", "文件", "异常"]


def read_file(path):
    """读取文件，返回原始行列表。txt 直接读，csv 用标准库按行拼接。"""
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        with open(path, "r", encoding="utf-8") as f:
            return [" ".join(row) for row in csv.reader(f)]
    # 默认按 txt 处理
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def clean_lines(lines):
    """清洗：strip 去首尾空白 → 过滤空行 → 合并行内连续空格为单个。"""
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:          # 过滤空行
            continue
        collapsed = " ".join(stripped.split())   # split() 默认按任意空白切，再拼接
        cleaned.append(collapsed)
    return cleaned


def count_keywords(lines, keywords):
    """统计每个关键词在所有行中的出现次数，大小写不敏感。"""
    stats = {kw: 0 for kw in keywords}
    for line in lines:
        lower_line = line.lower()
        for kw in keywords:
            stats[kw] += lower_line.count(kw.lower())
    return stats


def save_output(cleaned_lines, stats, clean_path, stats_path):
    """写出两个文件：清洗后文本 + 统计结果。"""
    with open(clean_path, "w", encoding="utf-8") as f:
        f.write("\n".join(cleaned_lines))
    with open(stats_path, "w", encoding="utf-8") as f:
        f.write("关键词统计结果\n")
        f.write("=" * 30 + "\n")
        for kw, cnt in stats.items():
            f.write(f"{kw}: {cnt}\n")


def main():
    input_path = "test.txt"
    clean_path = "output_clean.txt"
    stats_path = "output_stats.txt"

    # 读取阶段：捕获文件不存在等异常
    try:
        raw_lines = read_file(input_path)
    except FileNotFoundError:
        print(f"[友好提示] 文件不存在: {input_path}")
        print("请先创建测试输入文件后再运行本脚本。")
        return
    except Exception as e:
        print(f"[友好提示] 读取文件时发生异常: {e}")
        return

    cleaned = clean_lines(raw_lines)
    stats = count_keywords(cleaned, KEYWORDS)

    try:
        save_output(cleaned, stats, clean_path, stats_path)
    except Exception as e:
        print(f"[友好提示] 写出文件失败: {e}")
        return

    # 控制台预览
    print(f"清洗后行数: {len(cleaned)}")
    print("清洗结果预览（前 5 行）:")
    for line in cleaned[:5]:
        print(" ", line)
    print("\n关键词统计:")
    for kw, cnt in stats.items():
        print(f"  {kw}: {cnt}")
    print(f"\n输出已保存到: {clean_path} 和 {stats_path}")


if __name__ == "__main__":
    main()
