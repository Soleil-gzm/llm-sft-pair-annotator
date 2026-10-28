#!/usr/bin/env python3
"""一键切分大 JSON 文件，并自动生成同名文件夹。

用法：
  python3 split_json.py 原始大文件.json
  python3 split_json.py 原始大文件.json --chunk-size 500

说明：
  - 默认每 1000 个会话切分为一个文件。
  - 切分后的文件存放在原文件同级的 `原文件名_split` 文件夹中。
  - 切分后会自动校验数据量是否与原始文件一致。
"""
import argparse
import json
import os
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description="一键切分大 JSON 文件")
    ap.add_argument("input_file", help="要切分的原始大 JSON 文件路径")
    ap.add_argument("--chunk-size", type=int, default=1000, help="每个分片包含的会话数量（默认 1000）")
    args = ap.parse_args()

    input_path = Path(args.input_file)
    if not input_path.is_file():
        print(f"❌ 错误：文件 {input_path} 不存在。")
        sys.exit(1)

    # 读取数据
    print(f"正在加载文件：{input_path.name} ...")
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ 错误：读取 JSON 失败 - {e}")
        sys.exit(1)

    if not isinstance(data, list):
        print("❌ 错误：顶层结构不是 JSON 数组。")
        sys.exit(1)

    total_convs = len(data)
    if total_convs == 0:
        print("⚠️ 文件内容为空，无需切分。")
        return

    # 创建输出目录
    output_dir = input_path.parent / f"{input_path.stem}_split"
    output_dir.mkdir(exist_ok=True)
    print(f"📁 切分文件将保存在：{output_dir}")

    # 开始切分
    chunk_size = args.chunk_size
    num_chunks = (total_convs + chunk_size - 1) // chunk_size
    split_counts = []

    print(f"🔪 正在切分（共 {total_convs} 条会话，每份 {chunk_size} 条，将生成 {num_chunks} 个文件）...")

    for i in range(num_chunks):
        start = i * chunk_size
        end = start + chunk_size
        chunk_data = data[start:end]
        
        # 命名规则：原文件名_part1.json, 原文件名_part2.json ...
        chunk_name = f"{input_path.stem}_part{i + 1}.json"
        chunk_path = output_dir / chunk_name
        
        with open(chunk_path, "w", encoding="utf-8") as f:
            json.dump(chunk_data, f, ensure_ascii=False, indent=2)
            
        split_counts.append(len(chunk_data))
        print(f"  ✅ 已生成：{chunk_name} （包含 {len(chunk_data)} 条会话）")

    # 校验环节
    print("\n🔍 正在进行切分后校验...")
    actual_total = 0
    for chunk_name in os.listdir(output_dir):
        if chunk_name.startswith(input_path.stem) and chunk_name.endswith(".json"):
            chunk_path = output_dir / chunk_name
            with open(chunk_path, "r", encoding="utf-8") as f:
                chunk_data = json.load(f)
            actual_total += len(chunk_data)

    if actual_total == total_convs:
        print(f"✅ 校验通过！原始数据 {total_convs} 条，切分后数据总和 {actual_total} 条。")
        print(f"\n🎉 处理完成！请将 {output_dir.name} 文件夹及里面的文件发给标注人员。")
    else:
        print(f"❌ 校验失败！原始数据 {total_convs} 条，切分后数据总和 {actual_total} 条。请检查文件！")
        sys.exit(1)


if __name__ == "__main__":
    main()