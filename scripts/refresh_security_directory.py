"""Regenerate the A-share code -> short-name snapshot used to verify stock identities.

Run manually or on a schedule; never on the request path (the exchange lists are
paginated and take ~2 minutes). The snapshot is replaced only after every source
succeeds and passes validation, so a failed refresh keeps the previous file.

Usage: python scripts/refresh_security_directory.py
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "data" / "a_share_directory.json"
MIN_SECURITIES = 4000  # SSE main + STAR + SZSE A shares; far fewer means a truncated download.


def fetch() -> dict[str, str]:
    import akshare as ak
    sources = [  # Beijing exchange is out of scope: tools only support SSE/SZSE A shares.
        (ak.stock_info_sh_name_code(symbol="主板A股"), "证券代码", "证券简称"),
        (ak.stock_info_sh_name_code(symbol="科创板"), "证券代码", "证券简称"),
        (ak.stock_info_sz_name_code(symbol="A股列表"), "A股代码", "A股简称"),
    ]
    directory = {}
    for frame, code_col, name_col in sources:
        for code, name in zip(frame[code_col], frame[name_col]):
            code, name = str(code).strip().zfill(6), re.sub(r"\s", "", str(name))
            if not re.fullmatch(r"[036][0-9]{5}", code) or not name:
                raise ValueError(f"invalid row: {code!r} {name!r}")
            if directory.get(code, name) != name:
                raise ValueError(f"conflicting names for {code}")
            directory[code] = name
    if len(directory) < MIN_SECURITIES:
        raise ValueError(f"only {len(directory)} securities; refusing to replace snapshot")
    return dict(sorted(directory.items()))


def main() -> int:
    try:
        directory = fetch()
    except Exception as exc:
        print(f"refresh failed, snapshot unchanged: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    payload = {"generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
               "source": "akshare stock_info_sh_name_code(主板A股, 科创板) + stock_info_sz_name_code(A股列表)",
               "securities": directory}
    tmp = TARGET.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(TARGET)
    print(f"wrote {len(directory)} securities to {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
