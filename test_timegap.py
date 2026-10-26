"""timegap 的自检测试。用独立临时数据，不污染工作目录。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from timegap import (ParseError, compare, humanize, parse_timestamp,  # noqa: E402
                     to_epoch_seconds)


def test_parse_iso_with_tz() -> None:
    dt, fmt = parse_timestamp("2026-10-20T10:00:00+08:00")
    assert dt.isoformat() == "2026-10-20T10:00:00+08:00", dt.isoformat()
    assert "偏移" in fmt, fmt


def test_parse_iso_utc() -> None:
    dt, fmt = parse_timestamp("2026-10-20T10:00:00Z")
    assert dt.isoformat() == "2026-10-20T10:00:00+00:00", dt.isoformat()
    assert fmt == "ISO 8601（偏移 Z）", fmt


def test_parse_naive_defaults_to_utc() -> None:
    dt, fmt = parse_timestamp("2026-10-20 10:00:00")
    assert dt.tzinfo is not None
    assert fmt.endswith("按 UTC 处理）"), fmt


def test_parse_epoch_units() -> None:
    sec, f1 = parse_timestamp("1760000000")
    ms, f2 = parse_timestamp("1760000000000")
    us, f3 = parse_timestamp("1760000000000000")
    assert f1 == "epoch 秒", f1
    assert f2 == "epoch 毫秒", f2
    assert f3 == "epoch 微秒", f3
    assert abs(to_epoch_seconds(sec) - to_epoch_seconds(ms)) < 1e-3
    assert abs(to_epoch_seconds(sec) - to_epoch_seconds(us)) < 1e-6


def test_parse_date_only() -> None:
    dt, fmt = parse_timestamp("2026-10-20")
    assert dt.hour == 0 and dt.minute == 0
    assert "仅日期" in fmt, fmt


def test_parse_slash_form() -> None:
    dt, _ = parse_timestamp("2026/10/20 10:00:00")
    assert (dt.year, dt.month, dt.day) == (2026, 10, 20)


def test_parse_fractional_seconds() -> None:
    dt, _ = parse_timestamp("2026-10-20T10:00:00.123456")
    assert dt.microsecond == 123456


def test_parse_invalid_raises() -> None:
    for bad in ("", "   ", "not-a-time", "2026-13-45", "hello world"):
        try:
            parse_timestamp(bad)
        except ParseError:
            continue
        raise AssertionError(f"应当拒绝：{bad!r}")


def test_compare_same_instant_across_formats() -> None:
    # 同一时刻的两种写法，差值应为 0
    result = compare("2026-10-20T10:00:00Z", "2026-10-20T10:00:00+00:00")
    assert result["difference"]["seconds"] == 0, result


def test_compare_across_timezones_normalizes() -> None:
    # 10:00+08:00 与 02:00Z 是同一时刻
    result = compare("2026-10-20T10:00:00+08:00", "2026-10-20T02:00:00Z")
    assert abs(result["difference"]["seconds"]) < 1e-6, result


def test_compare_one_day() -> None:
    result = compare("2026-10-20 00:00:00", "2026-10-21 00:00:00")
    diff = result["difference"]
    assert diff["days"] == 1, diff
    assert diff["hours"] == 0 and diff["minutes"] == 0
    assert abs(diff["seconds"] - 86400) < 1e-6


def test_compare_negative_direction() -> None:
    result = compare("2026-10-21 00:00:00", "2026-10-20 00:00:00")
    assert result["difference"]["seconds"] < 0
    assert result["direction"] == "b 早于 a", result["direction"]


def test_compare_epoch_against_iso() -> None:
    result = compare("2026-10-20T10:00:00Z", "@1760000000")
    # 不要求具体差值，只要求两者能被解析并给出方向
    assert result["direction"] in ("b 晚于 a", "b 早于 a", "两者相同")


def test_humanize_breakdown() -> None:
    h = humanize(90061)
    assert h["days"] == 1
    assert h["hours"] == 1
    assert h["minutes"] == 1
    assert abs(h["seconds_part"] - 1) < 1e-6


def test_humanize_zero() -> None:
    h = humanize(0)
    assert h["days"] == 0 and h["seconds"] == 0


def test_cli_help_exits_zero() -> None:
    import subprocess
    entry = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timegap.py")
    r = subprocess.run([sys.executable, entry, "--help"],
                       capture_output=True, text=True, timeout=30,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    assert "timegap" in r.stdout


def test_cli_rejects_bad_input() -> None:
    import subprocess
    entry = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timegap.py")
    r = subprocess.run([sys.executable, entry, "--a", "nonsense", "--b", "2026-01-01"],
                       capture_output=True, text=True, timeout=30,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "解析失败" in r.stderr, r.stderr


def test_cli_json_output() -> None:
    import subprocess
    entry = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timegap.py")
    r = subprocess.run(
        [sys.executable, entry, "--a", "2026-10-20 00:00:00",
         "--b", "2026-10-21 00:00:00", "--json"],
        capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    import json
    data = json.loads(r.stdout)
    assert data["difference"]["days"] == 1, data


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK  ] {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n共 {len(tests)} 项，失败 {failed} 项")
    raise SystemExit(1 if failed else 0)