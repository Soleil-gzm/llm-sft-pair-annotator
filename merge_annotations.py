"""将一个或多个标注补丁合并回原始对话 JSON。

只替换 user/assistant 消息的 content；会话数、消息数、role 序列、
system 内容以及 loss 等其他字段均从原文件原样保留，合并后逐项校验。
多个补丁按传入顺序应用；同一消息被不同补丁改成不同内容时报错拒绝。

用法: python3 merge_annotations.py 原始文件.json 补丁1.json [补丁2.json ...] -o 输出文件.json
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


def data_sig(data):
    """与标注工具一致的数据指纹：会话数:消息总数:首条system字符数:末条消息字符数"""
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
    fail(f"补丁文件 {path} 格式不正确：应为数组或含 edits 数组的对象")


def main():
    ap = argparse.ArgumentParser(description="合并标注补丁到原始对话 JSON")
    ap.add_argument("original", help="原始对话 JSON 文件")
    ap.add_argument("patches", nargs="+", help="标注工具导出的补丁 JSON 文件，可多个")
    ap.add_argument("-o", "--output", required=True, help="输出文件路径（不得与原文件相同）")
    ap.add_argument("--force", action="store_true",
                    help="补丁 source/data_sig 与原文件不一致时仍强制执行")
    args = ap.parse_args()

    if os.path.abspath(args.output) == os.path.abspath(args.original):
        fail("错误：输出路径与原文件相同，为保护原始数据已拒绝执行")

    with open(args.original, encoding="utf-8") as f:
        data = json.load(f)
    sig = data_sig(data)

    # 第一步：加载并校验所有补丁，检查来源与冲突
    seen = {}    # (ci, mi) -> content
    origin = {}  # (ci, mi) -> 来源补丁文件名
    errors = []
    conflicts = []
    valid_roles = {"user", "assistant"}
    per_patch_counts = {}
    for path in args.patches:
        name = os.path.basename(path)
        meta, edits = load_patch(path)
        per_patch_counts[name] = len(edits)
        if not args.force:
            if meta.get("source") and os.path.basename(meta["source"]) != os.path.basename(args.original):
                fail(f"错误：补丁 {name} 来源 {meta['source']!r} 与原文件 {args.original!r} 不一致"
                     "（确认无误可加 --force 强制执行）")
            if meta.get("data_sig") and meta["data_sig"] != sig:
                fail(f"错误：补丁 {name} 的数据指纹 {meta['data_sig']} 与原文件 {sig} 不一致"
                     "（确认无误可加 --force 强制执行）")
        for k, e in enumerate(edits):
            where = f"{name} 第 {k} 条"
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
            if (ci, mi) in seen and seen[(ci, mi)] != content:
                conflicts.append(f"会话 {ci} 消息 {mi}: {origin[(ci, mi)]} 与 {name} 的修改内容不一致")
                continue
            seen[(ci, mi)] = content
            origin[(ci, mi)] = name
    if errors:
        fail(f"补丁校验未通过，共 {len(errors)} 处问题，未做任何修改：", errors)
    if conflicts:
        fail(f"发现 {len(conflicts)} 处冲突（同一消息被不同补丁改成不同内容），"
             "请人工裁定后重新导出：", conflicts)

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
    patch_desc = "、".join(f"{n}({c}条)" for n, c in per_patch_counts.items())
    print(f"合并完成 → {args.output}")
    print(f"补丁来源：{patch_desc}")
    print(f"应用补丁 {len(seen)} 条：实际修改 {changed} 条，无变化 {len(seen) - changed} 条，"
          f"涉及会话 {touched_convs} 条")
    print("结构校验通过：会话数 / 消息数 / role 序列 / system 内容 / 其他字段均与原文件一致")


if __name__ == "__main__":
    main()
