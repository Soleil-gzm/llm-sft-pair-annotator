import json

with open("M1_BP_generate_10000_57_20261020_191548_dup85p.json", encoding="utf-8") as f:
    data = json.load(f)

subset = data[:1000]

with open("subset_1000.json", "w", encoding="utf-8") as f:
    json.dump(subset, f, ensure_ascii=False, indent=2)

print(f"原会话数：{len(data)}，截取后：{len(subset)}")