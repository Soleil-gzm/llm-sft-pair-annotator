#!/usr/bin/env python3
"""将多个补丁文件合并为一个完整的会话数组。

支持 3 种格式（自动识别）：
  - sparse_edits: { edits: [{ conv_idx, msg_idx, content }] }
      → 无法直接合并为完整数组（缺少原始数据），会在输出中提示并跳过
  - recorded:     { data_sig?, conversations: [...] }
      → 提取 conversations 参与合并
  - raw_array:    [ { messages: [...] }, ... ]
      → 直接参与合并

特性：
  - 自动处理 Windows 记事本保存的 UTF-8 BOM（用 utf-8-sig 读取）
  - 可按完整会话去重（--dedup），对齐 JS 版 patchLib.convHash
  - 支持 glob 模式批量指定文件

用法：
  python3 merge_patches.py 补丁A.json 补丁B.json -o 合并结果.json --dedup
  python3 merge_patches.py -d ./patches --dedup
  python3 merge_patches.py "./patches/*.json" --dedup
"""
import argparse
import glob
import json
import os
import sys
from datetime import datetime


def sort_keys(obj):
    """递归排序字典键，对齐 JS 版 patchLib.sortObjectKeys 和 Python json.dumps(sort_keys=True)。"""
    if obj is None or not isinstance(obj, dict):
        return [sort_keys(x) for x in obj] if isinstance(obj, list) else obj
    return {k: sort_keys(obj[k]) for k in sorted(obj.keys())}


def conv_hash(conv):
    try:
        return json.dumps(sort_keys(conv), ensure_ascii=False)
    except Exception:
        return None


def read_patch_file(path):
    """读取单个补丁文件并识别格式，返回 (format, conversations_or_None, reason)。"""
    try:
        # utf-8-sig 自动剥掉 BOM，兼容 Windows 记事本保存的 UTF-8 文件
        with open(path, 'r', encoding='utf-8-sig') as f:
            obj = json.load(f)
    except Exception as e:
        return ('invalid', None, f'JSON 解析失败: {e}')

    if isinstance(obj, dict) and isinstance(obj.get('edits'), list):
        return ('sparse_edits', None, '')

    if isinstance(obj, dict) and isinstance(obj.get('conversations'), list):
        convs = obj['conversations']
        if not convs:
            return ('invalid', None, 'conversations 数组为空')
        if not isinstance(convs[0], dict) or not isinstance(convs[0].get('messages'), list):
            return ('invalid', None, 'conversations 元素缺少 messages 字段')
        return ('recorded', convs, '')

    if isinstance(obj, list):
        if not obj:
            return ('invalid', None, '空数组')
        if not isinstance(obj[0], dict) or not isinstance(obj[0].get('messages'), list):
            return ('invalid', None, '数组元素缺少 messages 字段')
        return ('raw_array', obj, '')

    return ('invalid', None, '无法识别的 JSON 结构')


def collect_files(sources):
    """把位置参数（直接文件 / glob 模式 / 目录）展开为文件列表。"""
    files = []
    for src in sources:
        if os.path.isdir(src):
            for name in sorted(os.listdir(src)):
                if name.endswith('.json'):
                    files.append(os.path.join(src, name))
        elif any(c in src for c in '*?['):
            files.extend(sorted(glob.glob(src)))
        elif os.path.isfile(src):
            files.append(src)
    return sorted(set(files))


def main():
    ap = argparse.ArgumentParser(description='合并多个补丁文件为一个完整的会话数组')
    ap.add_argument('sources', nargs='*',
                    help='补丁文件路径、包含 JSON 的目录，或 glob 模式（如 "./patches/*.json"）')
    ap.add_argument('-o', '--output', default=None, help='输出文件名（默认自动生成带时间戳）')
    ap.add_argument('--dedup', action='store_true', default=True, help='按完整会话去重（默认开启）')
    ap.add_argument('--no-dedup', action='store_false', dest='dedup', help='关闭去重')
    args = ap.parse_args()

    if not args.sources:
        ap.print_help()
        sys.exit(1)

    files = collect_files(args.sources)
    if not files:
        print('未找到任何 JSON 文件。')
        sys.exit(1)

    valid_arrays = []
    per_file_stats = []   # [(name, fmt, conv_count, valid_flag)]
    sparse_count = 0
    invalid_count = 0

    for path in files:
        fmt, convs, reason = read_patch_file(path)
        name = os.path.basename(path)
        if convs is not None:
            valid_arrays.append(convs)
            per_file_stats.append((name, fmt, len(convs), True))
        elif fmt == 'sparse_edits':
            sparse_count += 1
            per_file_stats.append((name, 'sparse_edits', 0, False))
        else:
            invalid_count += 1
            per_file_stats.append((name, f'invalid: {reason}', 0, False))

    if not valid_arrays:
        print('没有可合并的文件，请检查格式。')
        sys.exit(1)

    # 合并 + 去重
    merged = []
    seen = set() if args.dedup else None
    total_read = dup_count = bad_count = 0
    per_file_final = []
    valid_idx = 0
    for name, fmt, n_conv, is_valid in per_file_stats:
        if not is_valid:
            per_file_final.append((name, fmt, 0, 0, 0, 0, False))
            continue
        arr = valid_arrays[valid_idx]
        valid_idx += 1
        added = dup = bad = 0
        for conv in arr:
            if not isinstance(conv, dict) or not isinstance(conv.get('messages'), list):
                bad += 1
                continue
            if seen is not None:
                h = conv_hash(conv)
                if h is None or h in seen:
                    dup += 1
                    continue
                seen.add(h)
            merged.append(conv)
            added += 1
        per_file_final.append((name, fmt, n_conv, added, dup, bad, True))
        total_read += n_conv
        dup_count += dup
        bad_count += bad

    if not args.output:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.output = f'merged_patches_{ts}.json'

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    # 输出报告
    print('=' * 60)
    print(f'📁 合并完成')
    print(f'   输入文件: {len(files)} 个')
    if sparse_count:
        print(f'   跳过稀疏编辑格式: {sparse_count} 个（无法直接合并为完整数组）')
    if invalid_count:
        print(f'   跳过无效文件:     {invalid_count} 个')
    print(f'   实际合并:         {len(valid_arrays)} 个文件，共 {total_read} 条会话')
    if args.dedup:
        print(f'   去重后保留:       {len(merged)} 条（重复 {dup_count}，损坏 {bad_count} 已跳过）')
    else:
        print(f'   保留:             {len(merged)} 条（损坏 {bad_count} 已跳过）')
    print(f'   输出文件:         {args.output}')
    print('-' * 60)
    for fname, fmt, read_n, added, dup, bad, is_valid in per_file_final:
        if not is_valid:
            print(f'   • {fname} [{fmt}] ⏭ 未合并')
            continue
        parts = [f'{read_n}条', f'新增{added}']
        if args.dedup:
            parts.append(f'重复{dup}')
        if bad:
            parts.append(f'损坏{bad}')
        print(f'   • {fname} [{fmt}] {" · ".join(parts)}')
    print('=' * 60)


if __name__ == '__main__':
    main()
