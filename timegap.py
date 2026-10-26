"""timegap —— 把各类时间戳统一成同一基准，再计算差值。

设计原则：
1. 先归一化再计算，不允许两种时间基准混在同一个式子里。
2. 输出带单位（天/小时/分钟/秒），人看量级，脚本拿秒数。
3. 解析不了的输入直接报错，不静默跳过——时间类工具最怕静默出错。

仅依赖 Python 标准库。

用法:
    python timegap.py --help
    python timegap.py --a "2026-10-20 10:00:00" --b "2026-10-21T12:30:00"
    python timegap.py --a "2026-10-20T10:00:00Z" --b @1760000000
    python timegap.py --a "2026-10-20 10:00:00" --b "2026-10-21 12:30:00" --json
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# 格式识别
# ---------------------------------------------------------------------------

# 纯数字：epoch 秒 / 毫秒 / 微秒，按位数判断
EPOCH_RE = re.compile(r"^-?\d{9,19}$")

# ISO 8601 及常见变体：2026-10-20T10:00:00 / 2026-10-20 10:00:00 / 2026/10/20
ISO_RE = re.compile(
    r"^(?P<y>\d{4})[-/](?P<mo>\d{1,2})[-/](?P<d>\d{1,2})"
    r"(?:[T ](?P<h>\d{1,2}):(?P<mi>\d{2})(?::(?P<s>\d{2})(?:\.(?P<frac>\d+))?)?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?)?$"
)

# 只到日期：2026-10-20
DATE_RE = re.compile(r"^(?P<y>\d{4})[-/](?P<mo>\d{1,2})[-/](?P<d>\d{1,2})$")

SUPPORTED_FORMATS = (
    "epoch 秒 / 毫秒 / 微秒（按位数自动判断）",
    "ISO 8601：2026-10-20T10:00:00[.ffffff][Z|+08:00]",
    "斜杠分隔：2026/10/20 10:00:00",
    "仅日期：2026-10-20（按当日 00:00:00 处理）",
)


class ParseError(ValueError):
    """无法解析的时间戳。"""


def _parse_tz(raw: str | None) -> timezone | None:
    """把时区标记转成 tzinfo。None 表示输入没有时区信息。"""
    if not raw:
        return None
    if raw == "Z":
        return timezone.utc
    sign = 1 if raw[0] == "+" else -1
    body = raw[1:].replace(":", "")
    hours = int(body[:2])
    minutes = int(body[2:4])
    if hours > 23 or minutes > 59:
        raise ParseError(f"时区偏移超出范围：{raw}")
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def parse_timestamp(raw: str) -> tuple[datetime, str]:
    """解析一个时间戳，返回 (带时区的 datetime, 识别到的格式说明)。

    无时区信息的输入按 UTC 解释，并在格式说明里标注出来——
    不猜测本地时区，因为猜错会让差值静默偏掉。
    """
    text = raw.strip()
    if not text:
        raise ParseError("时间戳为空")

    # @ 前缀：等价于 epoch 写法，方便在 shell 里避免被当成选项
    if text.startswith("@"):
        text = text[1:].strip()
        if not text:
            raise ParseError("@ 之后没有时间戳")

    # epoch
    if EPOCH_RE.match(text):
        digits = text.lstrip("-")
        value = int(text)
        if len(digits) <= 10:          # 秒
            return datetime.fromtimestamp(value, tz=timezone.utc), "epoch 秒"
        if len(digits) <= 13:          # 毫秒
            return datetime.fromtimestamp(value / 1_000, tz=timezone.utc), "epoch 毫秒"
        if len(digits) <= 16:          # 微秒
            return datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc), "epoch 微秒"
        return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc), "epoch 纳秒"

    # 仅日期
    m = DATE_RE.match(text)
    if m:
        try:
            dt = datetime(int(m["y"]), int(m["mo"]), int(m["d"]), tzinfo=timezone.utc)
        except ValueError as e:
            raise ParseError(f"日期数值不合法：{raw}（{e}）") from e
        return dt, "仅日期（按 UTC 当日 00:00:00）"

    # ISO 及变体
    m = ISO_RE.match(text)
    if m:
        tz = _parse_tz(m["tz"])
        frac = m["frac"] or ""
        micro = int((frac + "000000")[:6]) if frac else 0
        try:
            naive = datetime(
                int(m["y"]), int(m["mo"]), int(m["d"]),
                int(m["h"] or 0), int(m["mi"] or 0), int(m["s"] or 0), micro,
            )
        except ValueError as e:
            raise ParseError(f"日期数值不合法：{raw}（{e}）") from e
        if tz is None:
            return naive.replace(tzinfo=timezone.utc), "ISO 8601（无时区，按 UTC 处理）"
        return naive.replace(tzinfo=tz), f"ISO 8601（偏移 {m['tz']}）"

    raise ParseError(
        f"无法识别的格式：{raw}\n支持的格式：\n  " + "\n  ".join(SUPPORTED_FORMATS)
    )


def to_epoch_seconds(dt: datetime) -> float:
    """统一换算成 epoch 秒。所有差值计算都走这里。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def humanize(seconds: float) -> dict:
    """把秒数拆成天/小时/分钟/秒，同时保留原始秒数。"""
    sign = -1 if seconds < 0 else 1
    total = abs(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    return {
        "seconds": round(seconds, 6),
        "days": int(days),
        "hours": int(hours),
        "minutes": int(minutes),
        "seconds_part": round(secs, 6),
        "display": (f"{sign * days:.0f} 天 {sign * hours:.0f} 小时 "
                    f"{sign * minutes:.0f} 分 {sign * secs:.6f} 秒"),
    }


def compare(a_raw: str, b_raw: str) -> dict:
    """比较两个时间戳的差值。"""
    a_dt, a_fmt = parse_timestamp(a_raw)
    b_dt, b_fmt = parse_timestamp(b_raw)
    a_epoch = to_epoch_seconds(a_dt)
    b_epoch = to_epoch_seconds(b_dt)
    delta = b_epoch - a_epoch
    return {
        "a": {"input": a_raw, "parsed": a_dt.isoformat(), "format": a_fmt,
              "epoch_seconds": a_epoch},
        "b": {"input": b_raw, "parsed": b_dt.isoformat(), "format": b_fmt,
              "epoch_seconds": b_epoch},
        "difference": humanize(delta),
        "direction": "b 晚于 a" if delta > 0 else ("b 早于 a" if delta < 0 else "两者相同"),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="timegap",
        description="把各类时间戳归一化后计算时间差（仅依赖标准库）",
        epilog=(
            "示例:\n"
            "  python timegap.py --a '2026-10-20 10:00:00' --b '2026-10-21T12:30:00'\n"
            "  python timegap.py --a '2026-10-20T10:00:00Z' --b @1760000000\n"
            "  python timegap.py --a '2026-10-20' --b '2026-10-21' --json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--a", required=True, help="第一个时间戳（支持 @1760000000 形式）")
    ap.add_argument("--b", required=True, help="第二个时间戳（支持 @1760000000 形式）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--list-formats", action="store_true", help="列出支持的格式并退出")
    args = ap.parse_args(argv)

    if args.list_formats:
        print("支持的格式：")
        for f in SUPPORTED_FORMATS:
            print(f"  - {f}")
        print("\n注意：没有时区信息的输入按 UTC 处理，不猜测本地时区。")
        return 0

    a = args.a[1:] if args.a.startswith("@") else args.a
    b = args.b[1:] if args.b.startswith("@") else args.b

    try:
        result = compare(a, b)
    except ParseError as e:
        print(f"解析失败：{e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    diff = result["difference"]
    print(f"A: {result['a']['input']}")
    print(f"   解析为 {result['a']['parsed']}（{result['a']['format']}）")
    print(f"B: {result['b']['input']}")
    print(f"   解析为 {result['b']['parsed']}（{result['b']['format']}）")
    print()
    print(f"差值（秒）: {diff['seconds']}")
    print(f"差值（可读）: {diff['display']}")
    print(f"方向: {result['direction']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
