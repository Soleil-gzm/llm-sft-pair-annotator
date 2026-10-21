"""将标注补丁合并回原始对话 JSON。

只替换 user/assistant 消息的 content；会话数、消息数、role 序列、
system 内容以及 loss 等其他字段均从原文件原样保留，合并后逐项校验。

用法: python3 merge_annotations.py 原始文件.json 补丁文件.json -o 输出文件.json
"""
import argparse
import copy
import json
import os
import sys


def fail(msg, errors=None):
    print(msg)
    for e in (errors or []):
        print(" -", e)
    sys.exit(1)


def load_edits(path):
    with open(path, encoding="utf-8") as f:
        patch = json.load(f)
    if isinstance(patch, list):
        return None, patch
    if isinstance(patch, dict) and isinstance(patch.get("edits"), list):
        return patch, patch["edits"]
    fail("补丁文件格式不正确：应为数组或含 edits 数组的对象")


def main():
    ap = argparse.ArgumentParser(description="合并标注补丁到原始对话 JSON")
    ap.add_argument("original", help="原始对话 JSON 文件")
    ap.add_argument("patch", help="标注工具导出的补丁 JSON 文件")
    ap.add_argument("-o", "--output", required=True, help="输出文件路径")
    ap.add_argument("--force", action="store_true",
                    help="补丁 source 与原文件名不一致时仍强制执行")
    args = ap.parse_args()

    with open(args.original, encoding="utf-8") as f:
        data = json.load(f)
    meta, edits = load_edits(args.patch)

    if meta and meta.get("source") and not args.force:
        if os.path.basename(args.original) != os.path.basename(meta["source"]):
            fail(f"错误：补丁来源 {meta['source']!r} 与原文件 {args.original!r} "
             "不一致（确认无误可加 --force 强制执行）")

    # 第一步：校验补丁合法性（任何一条非法即整体拒绝）
    errors = []
    seen = {}
    valid_roles = {"user", "assistant"}
    for k, e in enumerate(edits):
        where = f"补丁第 {k} 条"
        if not isinstance(e, dict) or not {"conv_idx", "msg_idx", "content"} <= set(e):
            errors.append(f"{where}: 缺少 conv_idx/msg_idx/content 字段")
            continue
        ci, mi, content = e["conv_idx"], e["msg_idx"], e["content"]
        if not (isinstance(ci, int) and isinstance(mi, int)) or not isinstance(content, str):
            errors.append(f"{where}: 字段类型不正确")
            continue
        if not (0 <= ci < len(data)):
            errors.append(f"{where}: conv_idx {ci} 超出范围（共 {len(data)} 条会话）")
            continue
        msgs = data[ci].get("messages", [])
        if not (0 <= mi < len(msgs)):
            errors.append(f"{where}: msg_idx {mi} 超出范围（会话 {ci} 共 {len(msgs)} 条消息）")
            continue
        role = msgs[mi].get("role")
        if role not in valid_roles:
            errors.append(f"{where}: 会话 {ci} 消息 {mi} 角色为 {role}，只允许修改 user/assistant")
            continue
        if (ci, mi) in seen:
            print(f"警告：会话 {ci} 消息 {mi} 存在多条补丁，以最后一条为准")
        seen[(ci, mi)] = content
    if errors:
        fail(f"补丁校验未通过，共 {len(errors)} 处问题，未做任何修改：", errors)

    # 第二步：以原文件为底应用补丁（只动 content）
    out = copy.deepcopy(data)
    for (ci, mi), content in seen.items():
        out[ci]["messages"][mi]["content"] = content

    # 第三步：整体校验，除补丁位置的 content 外必须与原文件完全一致
    diff_positions = set()
    for ci, (oc, nc) in enumerate(zip(data, out)):
        om, nm = oc["messages"], nc["messages"]
        if len(om) != len(nm):
            fail(f"结构校验失败：会话 {ci} 消息数发生变化")
        for mi, (o, n) in enumerate(zip(om, nm)):
            if set(o) != set(n):
                fail(f"结构校验失败：会话 {ci} 消息 {mi} 字段集合发生变化")
            if o["role"] != n["role"]:
                fail(f"结构校验失败：会话 {ci} 消息 {mi} 角色发生变化")
            if o["role"] == "system" and o["content"] != n["content"]:
                fail(f"结构校验失败：会话 {ci} system 内容被修改")
            for key in set(o) - {"content"}:
                if o[key] != n[key]:
                    fail(f"结构校验失败：会话 {ci} 消息 {mi} 字段 {key} 被修改")
            if o["content"] != n["content"]:
                diff_positions.add((ci, mi))
    if not diff_positions <= set(seen):
        fail("结构校验失败：存在补丁范围以外的内容差异")
    if len(out) != len(data):
        fail("结构校验失败：会话数发生变化")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    changed = len(diff_positions)
    touched_convs = len({ci for ci, _ in diff_positions})
    print(f"合并完成 → {args.output}")
    print(f"应用补丁 {len(seen)} 条：实际修改 {changed} 条，无变化 {len(seen) - changed} 条，"
          f"涉及会话 {touched_convs} 条")
    print("结构校验通过：会话数 / 消息数 / role 序列 / system 内容 / 其他字段均与原文件一致")


if __name__ == "__main__":
    main()
