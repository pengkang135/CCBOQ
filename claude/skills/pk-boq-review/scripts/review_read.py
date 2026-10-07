# -*- coding: utf-8 -*-
"""读回 HTML 审阅稿：打印修改清单和审阅意见，源文件在审阅期间变动时提醒。"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_html  # noqa: E402

DATA_RE = re.compile(r'<script type="application/json" id="review-data">(.*?)</script>', re.S)
COL_NAME = {"code": "编号", "en": "英文描述", "zh": "中文描述", "unit": "单位"}


def load(path):
    with open(path, encoding="utf-8") as f:
        m = DATA_RE.search(f.read())
    if not m:
        raise SystemExit("不是 pk-boq-review 生成的审阅稿（缺少 review-data）：%s" % path)
    return json.loads(m.group(1))


def _c(s):
    return (s or "").replace("|", "\\|").replace("\n", "<br>")


def report(data):
    meta, rv = data["meta"], data["review"]
    L = ["- 源文件：`%s` · 工作表 %s" % (meta["source"], meta["sheet"]),
         "- 保存时间：%s" % (rv.get("saved_at") or "未保存过")]
    if not os.path.exists(meta["source"]):
        L.append("- 注意：源文件不存在")
    elif review_html.file_sig(meta["source"]) != {k: meta[k] for k in ("source_mtime", "source_size")}:
        L.append("- 注意：审阅期间源文件被改过，行号可能错位，改版前按编号核对")
    edits, notes, dels = rv.get("edits") or [], rv.get("comments") or [], rv.get("deletes") or []
    if dels:
        L += ["", "| 删除行 | 编号 | 中文描述 |", "|---|---|---|"]
        L += ["| %s | %s | %s |" % (d["row"] or "新", d["code"], _c(d.get("desc"))) for d in dels]
    if edits:
        L += ["", "| 行 | 编号 | 列 | 原值 | 新值 |", "|---|---|---|---|---|"]
        L += ["| %s | %s | %s | %s | %s |" % (e["row"] or "新", e["code"], COL_NAME.get(e["col"], e["col"]),
                                            _c(e["old"]), _c(e["new"])) for e in edits]
    if notes:
        L += ["", "| 行 | 编号 | 中文描述 | 意见 |", "|---|---|---|---|"]
        L += ["| %s | %s | %s | %s |" % (c["row"] or "新", c["code"], _c(c.get("desc")), _c(c["text"])) for c in notes]
    L += ["", "合计：删除 %d 行，修改 %d 处，意见 %d 条" % (len(dels), len(edits), len(notes))
          if dels or edits or notes else "审阅稿无修改"]
    return "\n".join(L)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit("用法：python review_read.py <审阅稿.html>")
    print(report(load(argv[0])))


if __name__ == "__main__":
    main()
