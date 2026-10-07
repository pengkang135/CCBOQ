"""⑧ 写回前 dry-run 映射预检：行级覆盖率 + 闭词表校验 + 前缀一致性。

把断层堵在写盘前，而不是写回后发现再返工（ZOO 分类教训：
B 册 903 行 unmapped、子分部"第X章"前缀不一致，全是写回后才发现）。

用法：
  python dry_run_precheck.py --results results.json \
    --mapping-fields status            # 有判定=这些字段任一非空
    [--closed-vocab vocab.json]        # {"field": [allowed...]} 或 [allowed...] 对应单字段
    [--group-by subcategory]           # unmapped 按此字段分布
    [--prefix-regex '^第[一二三四五六七八九十0-9]+章']  # 检查分组字段前缀一致性
    [--min-coverage 95]                # 覆盖率低于此值(0-100)退出码 1，阻止写回
    [--fail-on-zero-unmapped]          # unmapped>0 即退出码 1（严格模式）
    [--report precheck.html]           # 可选 HTML 报表

退出码：0=通过可写回，1=有断层需先补。
"""
import argparse
import json
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")


def norm(v):
    if v is None:
        return ""
    return str(v).strip()


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def html_escape(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    ap = argparse.ArgumentParser(description="写回前 dry-run 映射预检")
    ap.add_argument("--results", required=True)
    ap.add_argument("--mapping-fields", required=True, help="逗号分隔：有判定=这些字段任一非空")
    ap.add_argument("--closed-vocab")
    ap.add_argument("--group-by")
    ap.add_argument("--prefix-regex")
    ap.add_argument("--min-coverage", type=float, default=0)
    ap.add_argument("--fail-on-zero-unmapped", action="store_true")
    ap.add_argument("--report")
    args = ap.parse_args()

    rows = load_json(args.results)
    fields = [f.strip() for f in args.mapping_fields.split(",") if f.strip()]
    group_field = args.group_by
    prefix_re = re.compile(args.prefix_regex) if args.prefix_regex else None

    vocab = {}
    if args.closed_vocab:
        raw = load_json(args.closed_vocab)
        for f in fields:
            v = raw.get(f)
            if isinstance(v, list):
                vocab[f] = {str(x).strip() for x in v}
            elif isinstance(v, dict):
                vocab[f] = {str(x).strip() for x in v.values()}
            else:
                vocab[f] = {str(x).strip() for x in raw}
        if len(fields) == 1 and not any(f in raw for f in fields):
            vocab[fields[0]] = {str(x).strip() for x in raw}

    unmapped, mapped, violations, prefix_bad = [], [], [], []
    for r in rows:
        row_id = r.get("row", r.get("excel_row", r.get("id", "")))
        has_judge = any(norm(r.get(f)) for f in fields)
        if has_judge:
            mapped.append(r)
        else:
            unmapped.append(r)
        for f in fields:
            val = norm(r.get(f))
            if val and f in vocab and val not in vocab[f]:
                violations.append((row_id, f, val))
        gv = norm(r.get(group_field)) if group_field else ""
        if prefix_re and gv and prefix_re.match(gv):
            prefix_bad.append((row_id, gv))

    total = len(rows)
    mapped_n = len(mapped)
    cov = mapped_n / total * 100 if total else 0

    print(f"总行数: {total}  mapped: {mapped_n}  unmapped: {len(unmapped)}  覆盖率: {cov:.1f}%")
    if group_field:
        dist = Counter(norm(r.get(group_field)) or "(无分组)" for r in unmapped)
        print("unmapped 按分组分布:")
        for g, c in dist.most_common(20):
            print(f"  {g}: {c}")
    if violations:
        print(f"闭词表违规 {len(violations)} 项(前20):")
        for v in violations[:20]:
            print(f"  row{v[0]} {v[1]}={v[2]!r}")
    if prefix_bad:
        print(f"前缀未去除 {len(prefix_bad)} 项(前20):")
        for v in prefix_bad[:20]:
            print(f"  row{v[0]} group={v[1]!r}")

    if args.report:
        html_rows = []
        for r in unmapped:
            g = html_escape(norm(r.get(group_field)) if group_field else "-")
            html_rows.append(f"<tr><td>{r.get('row', '')}</td><td>{g}</td><td>unmapped</td></tr>")
        for row_id, f, val in violations[:100]:
            html_rows.append(f"<tr><td>{row_id}</td><td>-</td><td>词表违规 {f}={html_escape(val)}</td></tr>")
        for row_id, g in prefix_bad[:100]:
            html_rows.append(f"<tr><td>{row_id}</td><td>{html_escape(g)}</td><td>前缀未去除</td></tr>")
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>dry-run 预检</title></head>
<body><h2>映射预检报表</h2>
<p>总 {total} · mapped {mapped_n} · unmapped {len(unmapped)} · 覆盖率 {cov:.1f}%</p>
<table border="1" cellpadding="4"><tr><th>row</th><th>分组</th><th>问题</th></tr>
{''.join(html_rows)}</table></body></html>""")

    fail = (len(unmapped) > 0 and args.fail_on_zero_unmapped) or cov < args.min_coverage
    if fail:
        print("未通过：有断层，先补再写盘")
        sys.exit(1)
    print("通过：可写盘")


if __name__ == "__main__":
    main()
