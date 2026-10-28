#!/usr/bin/env python3
"""将切分的 part1, part2... 重新拼接回一个大 JSON"""
import json
import os
import sys
import re

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def main():
    if len(sys.argv) < 3:
        print("用法: python3 merge_split.py <包含切分文件的目录> <输出文件名.json>")
        sys.exit(1)
        
    folder = sys.argv[1]
    output_file = sys.argv[2]
    
    files = [f for f in os.listdir(folder) if f.endswith('.json')]
    files.sort(key=natural_sort_key)
    
    merged = []
    for f in files:
        with open(os.path.join(folder, f), 'r', encoding='utf-8') as file:
            data = json.load(file)
            if isinstance(data, list):
                merged.extend(data)
                
    with open(output_file, 'w', encoding='utf-8') as file:
        json.dump(merged, file, ensure_ascii=False, indent=2)
        
    print(f"✅ 拼接完成，共 {len(merged)} 条会话，已保存至 {output_file}")

if __name__ == "__main__":
    main()