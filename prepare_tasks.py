"""校验多轮对话数据结构，确认可用于话术微调标注。

校验规则：
1. 顶层为会话数组，每个会话含非空 messages 列表
2. 每个会话首条消息为 system，且仅有这一条 system
3. system 之后 user / assistant 严格交替，且轮次完整（成对）
4. 每条消息含 role 与 content 字段，content 为字符串

用法: python3 prepare_tasks.py <数据文件.json>
"""
import argparse
import json
import sys


def validate(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    errors = []
    if not isinstance(data, list):
        return data, ["顶层结构不是 JSON 数组"]
    for i, conv in enumerate(data):
        msgs = conv.get("messages") if isinstance(conv, dict) else None
        if not isinstance(msgs, list) or not msgs:
            errors.append(f"会话 {i}: messages 缺失或为空")
            continue
        roles = []
        for j, m in enumerate(msgs):
            if not isinstance(m, dict) or "role" not in m or "content" not in m:
                errors.append(f"会话 {i} 消息 {j}: 缺少 role 或 content 字段")
                continue
            if not isinstance(m["content"], str):
                errors.append(f"会话 {i} 消息 {j}: content 不是字符串")
            roles.append(m["role"])
        if not roles:
            continue
        if roles[0] != "system":
            errors.append(f"会话 {i}: 首条消息不是 system")
        elif roles.count("system") > 1:
            errors.append(f"会话 {i}: 存在多条 system 消息")
        expected = ["user", "assistant"]
        for j, role in enumerate(roles[1:], start=1):
            if role not in expected:
                errors.append(f"会话 {i} 消息 {j}: 非法角色 {role!r}")
            elif role != expected[(j - 1) % 2]:
                errors.append(f"会话 {i} 消息 {j}: 应为 {expected[(j - 1) % 2]}，实际为 {role}")
        if (len(roles) - 1) % 2 != 0:
            errors.append(f"会话 {i}: 非 system 消息数为奇数，存在未配对的轮次")
    return data, errors


def main():
    ap = argparse.ArgumentParser(description="校验对话数据结构是否满足标注要求")
    ap.add_argument("data", help="原始对话 JSON 文件")
    args = ap.parse_args()

    data, errors = validate(args.data)
    if errors:
        print(f"校验未通过，共 {len(errors)} 处问题：")
        for e in errors[:50]:
            print(" -", e)
        if len(errors) > 50:
            print(f" ... 其余 {len(errors) - 50} 处省略")
        sys.exit(1)

    msg_counts = [len(c["messages"]) for c in data]
    turns = [(n - 1) // 2 for n in msg_counts]
    editable = sum(n - 1 for n in msg_counts)
    print(f"校验通过：{len(data)} 条会话")
    print(f"消息总数：{sum(msg_counts)}（可编辑 user/assistant {editable} 条）")
    print(f"会话轮次 min/max/avg：{min(turns)}/{max(turns)}/{sum(turns) / len(turns):.1f}")
    print("下一步：用浏览器打开标注工具，加载该文件开始标注")


if __name__ == "__main__":
    main()
