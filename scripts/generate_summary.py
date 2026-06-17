#!/usr/bin/env python3
r"""会话摘要生成器 —— 在项目 sessions/ 目录创建 Codex 会话摘要。

用法:
    python scripts/generate_summary.py "<标题/任务描述>"

输出:
    在 sessions/ 下创建 YYYY-MM-DD_HHMM.md 文件。
    用户可手动复制到 D:\01_Knowledge\Projects\202606_InsightAgent\会话摘要\
    与 Claude Code 摘要合并。
"""

import sys
from datetime import datetime
from pathlib import Path

SUMMARY_DIR = Path(__file__).resolve().parent.parent / "sessions"

TEMPLATE = """---
date: {date}
project: InsightAgent
tags:
  - codex-session
  - summary
  - dev-log
  - project/InsightAgent
---

# Codex 会话摘要 - {datetime_str}

## 主要任务
{title}

## 完成内容

| 类别 | 文件 | 改动要点 |
|------|------|----------|
| | | |

## 关键决策


## 遗留事项

"""


def main():
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    datetime_str = now.strftime("%Y-%m-%d_%H%M")

    filename = f"{datetime_str}.md"

    title = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    content = TEMPLATE.format(date=date_str, datetime_str=datetime_str, title=title)

    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    filepath = SUMMARY_DIR / filename
    filepath.write_text(content, encoding="utf-8")

    print(f"OK: {filepath}")


if __name__ == "__main__":
    main()

