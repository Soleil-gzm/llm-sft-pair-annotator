#!/usr/bin/env python3
"""批量合并标注补丁到对应的原始对话 JSON（按 data_sig / source 自动匹配）。

针对以下目录结构设计：
  M1/
  ├── 某任务1/
  │   └── timestamp/
  │       └── xxx.json  <-- 原文件
  ├── 某任务2/
  │   └── ...
  └── 补丁导出文件/
      ├── patch_张三_xxx.json  <-- 补丁
      └── patch_李四_xxx.json

用法：
  python3 batch_merge.py M1的路径
  python3 batch_merge.py M1的路径 --on-conflict first --priority 张三,李四
"""
import argparse
import copy
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def fail(msg):
    print("错误：" + msg, file=sys.stderr)
    sys.exit(1)


def data_sig(data):
    """与 pair_annotator.html / merge_annotations.py 一致的数据指纹。"""
    total = sum(len(c["messages"]) for c in data)
    sys_len = len(data[0]["messages"][0]["content"]) if data and data[0]["messages"] else 0
    last_len = len(data[-1]["messages"][-1]["content"]) if data and data[-1]["messages"] else 0
    return f"{len(data)}:{total}:{sys_len}:{last_len}"


def load_patch(path):
    with open(path, encoding="utf-8") as f:
        patch = json.load(f)
    if isinstance(patch, list):
        return {}, patch
    if isinstance(patch, dict) and isinstance(patch.get("edits"), list):
        return patch, patch["edits"]
    raise ValueError("补丁格式不正确：应为数组或含 edits 数组的对象")


def is_valid_dialogue(data):
    """简单校验是否为对话数据，用于排除日志、配置等无关 JSON。"""
    if not isinstance(data, list) or not data:
        return False
    if not isinstance(data[0], dict) or "messages" not in data[0]:
        return False
    return True


def sort_patches(patches, priority):
    pmap = {a: i for i, a in enumerate(priority)}

    def key(item):
        name, meta, _ = item
        ann = meta.get("annotator", "")
        if ann in pmap:
            return (0, pmap[ann], name)
        return (1, 0, name)

    return sorted(patches, key=key)


def merge_patches(original_data, patches, on_conflict="reject"):
    seen = {}
    origin = {}
    conflicts, errors = [], []
    valid_roles = {"user", "assistant"}

    for name, meta, edits in patches:
        for k, e in enumerate(edits):
            where = f"{name} 第 {k} 条"
            if not isinstance(e, dict) or not {"conv_idx", "msg_idx", "content"} <= set(e):
                errors.append(f"{where}: 缺少 conv_idx/msg_idx/content 字段")
                continue
            ci, mi, content = e["conv_idx"], e["msg_idx"], e["content"]
            if not (isinstance(ci, int) and isinstance(mi, int)) or not isinstance(content, str):
                errors.append(f"{where}: 字段类型不正确")
                continue
            if not (0 <= ci < len(original_data)):
                errors.append(f"{where}: conv_idx {ci} 超出范围")
                continue
            msgs = original_data[ci].get("messages", [])
            if not (0 <= mi < len(msgs)):
                errors.append(f"{where}: msg_idx {mi} 超出范围")
                continue
            role = msgs[mi].get("role")
            if role not in valid_roles:
                errors.append(f"{where}: 会话 {ci} 消息 {mi} 角色为 {role}，只允许修改 user/assistant")
                continue
            key = (ci, mi)
            if key in seen and seen[key] != content:
                if on_conflict == "first":
                    continue
                if on_conflict == "last":
                    pass
                else:
                    conflicts.append(
                        f"会话 {ci} 消息 {mi}: {origin[key]} 与 {name} 的修改内容不一致"
                    )
                    continue
            seen[key] = content
            origin[key] = name

    out = copy.deepcopy(original_data)
    for (ci, mi), content in seen.items():
        out[ci]["messages"][mi]["content"] = content

    changed = set()
    for ci, (oc, nc) in enumerate(zip(original_data, out)):
        om, nm = oc["messages"], nc["messages"]
        if len(om) != len(nm):
            errors.append(f"会话 {ci} 消息数发生变化")
            continue
        for mi, (o, n) in enumerate(zip(om, nm)):
            if set(o) != set(n):
                errors.append(f"会话 {ci} 消息 {mi} 字段集合变化")
                continue
            if o["role"] != n["role"]:
                errors.append(f"会话 {ci} 消息 {mi} 角色变化")
            for key in set(o) - {"content"}:
                if o[key] != n[key]:
                    errors.append(f"会话 {ci} 消息 {mi} 字段 {key} 变化")
            if o["content"] != n["content"]:
                changed.add((ci, mi))
    if not changed <= set(seen):
        errors.append("存在补丁范围外的内容差异")
    return out, changed, conflicts, errors


def main():
    ap = argparse.ArgumentParser(
        description="扫描指定目录批量合并标注补丁（原文件保存在同目录下加 _patch 后缀）"
    )
    ap.add_argument("root_dir", help="要扫描的根目录（如 M1 路径），包含原文件及补丁文件夹")
    ap.add_argument("--patch-dir", default="补丁导出文件", help="补丁文件夹名称（默认: 补丁导出文件）")
    ap.add_argument("--on-conflict", choices=["reject", "first", "last"], default="reject",
                    help="同一消息被多个补丁改成不同内容时的策略（默认 reject）")
    ap.add_argument("--priority", default="", help="标注人优先级，逗号分隔，如 '张三,李四'")
    ap.add_argument("--report", default=None, help="把报告另存到文件")
    args = ap.parse_args()

    root = Path(args.root_dir)
    if not root.is_dir():
        fail(f"目录不存在：{root}")

    patch_dir_path = root / args.patch_dir
    priority = [a.strip() for a in args.priority.split(",") if a.strip()]

    # ---------- 1. 加载并筛选原文件 ----------
    originals = {}
    sig_index = defaultdict(list)
    base_index = defaultdict(list)
    
    # 遍历 root_dir 下所有 json，跳过补丁目录和 _patch 文件
    for p in root.rglob("*.json"):
        if not p.is_file(): continue
        # 排除补丁文件夹
        if patch_dir_path in p.parents: continue
        # 排除已合并生成的文件
        if p.stem.endswith("_patch"): continue
        
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if not is_valid_dialogue(data):
                continue # 跳过日志、配置等无关 JSON
            
            sig = data_sig(data)
            originals[p] = (data, sig)
            sig_index[sig].append(p)
            base_index[p.name].append(p)
        except Exception:
            # 忽略解析失败的文件（如 intermediate 中的部分数据）
            continue

    if not originals:
        fail(f"在 {root} 下未找到有效的对话原文件")

    # ---------- 2. 加载补丁 ----------
    if not patch_dir_path.is_dir():
        fail(f"补丁目录不存在：{patch_dir_path}")

    patch_paths = [p for p in patch_dir_path.glob("*.json") if p.is_file()]
    if not patch_paths:
        fail(f"在 {patch_dir_path} 下未找到补丁文件")

    matched = defaultdict(list)
    unmatched = []
    for p in patch_paths:
        try:
            meta, edits = load_patch(p)
        except Exception as ex:
            unmatched.append((p.name, f"读取失败: {ex}"))
            continue
        target, reason = None, None

        # 尝试 data_sig 匹配
        sig = meta.get("data_sig")
        if sig:
            cands = sig_index.get(sig, [])
            if len(cands) == 1:
                target = cands[0]
            elif len(cands) > 1:
                # 如果有重名的，尝试用 source 进一步过滤
                src = meta.get("source", "")
                if src:
                    refined = [c for c in cands if c.name == src]
                    if len(refined) == 1:
                        target = refined[0]
                    else:
                        reason = f"data_sig 匹配到多个原文件且 source 无法唯一确定"
                else:
                    reason = f"data_sig 匹配到多个原文件"

        # 尝试 source 匹配
        src = meta.get("source")
        if target is None and not reason and src:
            cands = base_index.get(os.path.basename(src), [])
            if len(cands) == 1:
                target = cands[0]
            elif len(cands) > 1:
                reason = f"source 文件名匹配到多个原文件"

        # 兜底：如果全目录只有一个原文件
        if target is None and not reason and len(originals) == 1:
            target = next(iter(originals))

        if target is None:
            unmatched.append((p.name, reason or "无法匹配到原文件（缺 data_sig，source 也不匹配）"))
            continue

        matched[target].append((p.name, meta, edits))

    # ---------- 3. 合并并保存 ----------
    report = []
    def log(s):
        print(s)
        report.append(s)

    log("=" * 70)
    log(f"扫描根目录: {root}")
    log(f"补丁目录:   {patch_dir_path}")
    log(f"有效原文件: {len(originals)} 个 | 补丁总数: {len(patch_paths)} 个")
    log(f"冲突策略:   {args.on_conflict}" + (f"（优先级: {' > '.join(priority)}）" if priority else ""))
    log("=" * 70)
    log("")

    success, failed = 0, 0
    for orig_path, patches in sorted(matched.items()):
        data, _ = originals[orig_path]
        patches = sort_patches(patches, priority)
        merged, changed, conflicts, errors = merge_patches(data, patches, args.on_conflict)
        names = "、".join(n for n, _, _ in patches)

        if conflicts and args.on_conflict == "reject":
            log(f"[冲突] {orig_path.name}（{len(patches)} 个补丁）—— 未输出")
            for c in conflicts: log(f"    {c}")
            failed += 1
            continue
        if errors:
            log(f"[错误] {orig_path.name}（{len(patches)} 个补丁）—— 未输出")
            for e in errors: log(f"    {e}")
            failed += 1
            continue

        # 保存：原文件名加 _patch，保存在同目录
        out_path = orig_path.parent / (orig_path.stem + "_patch" + orig_path.suffix)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)

        touched = len({ci for ci, _ in changed})
        log(f"[完成] {orig_path.name}（{len(patches)} 个补丁: {names}）")
        log(f"    → 已保存至: {out_path}")
        log(f"    应用 {len(changed)} 条 / 涉及会话 {touched} 条"
            + (f"；处理了 {len(conflicts)} 处冲突" if conflicts else ""))
        success += 1

    if unmatched:
        log("")
        log(f"[未匹配补丁] {len(unmatched)} 个：")
        for name, reason in unmatched:
            log(f"    - {name}: {reason}")

    log("")
    log(f"合计：成功合并 {success} 个原文件，失败 {failed} 个，未匹配补丁 {len(unmatched)} 个")

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write("\n".join(report) + "\n")

    if failed or unmatched:
        sys.exit(1)


if __name__ == "__main__":
    main()