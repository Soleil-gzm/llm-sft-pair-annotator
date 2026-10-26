#!/usr/bin/env python3
"""将多个 patch_raw_*.json 文件合并为一个总文件。

用法：
  python3 merge_raw_patches.py -d 补丁目录 -o 输出文件.json
  python3 merge_raw_patches.py -d ./patches --dedup
"""
import argparse
import json
import os
import sys
from datetime import datetime

def get_raw_files(directory):
    """获取目录下所有 patch_raw_ 开头的 JSON 文件"""
    result = []
    for f in os.listdir(directory):
        if f.startswith("patch_raw_") and f.endswith(".json"):
            result.append(os.path.join(directory, f))
    return sorted(result)

def main():
    ap = argparse.ArgumentParser(description="合并多个 patch_raw JSON 文件")
    ap.add_argument("-d", "--dir", default=".", help="存放 patch_raw_*.json 的目录（默认当前目录）")
    ap.add_argument("-o", "--output", default=None, help="输出文件名（默认自动生成带时间戳的文件名）")
    ap.add_argument("--dedup", action="store_true", help="尝试去除完全重复的会话（基于内容哈希）")
    args = ap.parse_args()

    if not os.path.isdir(args.dir):
        print(f"错误：目录 {args.dir} 不存在")
        sys.exit(1)

    files = get_raw_files(args.dir)
    if not files:
        print(f"在 {args.dir} 下未找到任何 patch_raw_*.json 文件。")
        sys.exit(1)

    merged_data = []
    seen_hashes = set()
    total_read = 0

    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"跳过 {os.path.basename(fpath)}: 解析失败 - {e}")
            continue

        if not isinstance(data, list):
            print(f"跳过 {os.path.basename(fpath)}: 顶层不是数组")
            continue

        total_read += len(data)

        for conv in data:
            if args.dedup:
                # 将整个会话转为 JSON 字符串进行去重，保证完全相同的数据不重复合并
                conv_str = json.dumps(conv, sort_keys=True, ensure_ascii=False)
                if conv_str in seen_hashes:
                    continue
                seen_hashes.add(conv_str)
            merged_data.append(conv)

    if not args.output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"merged_patch_raw_{timestamp}.json"

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(merged_data, f, ensure_ascii=False, indent=2)

    print("=" * 50)
    print(f"合并完成！")
    print(f"共读取文件: {len(files)} 个")
    print(f"读取总会话: {total_read} 条")
    print(f"最终输出:   {len(merged_data)} 条")
    print(f"输出文件:   {args.output}")
    print("=" * 50)


if __name__ == "__main__":
    main()