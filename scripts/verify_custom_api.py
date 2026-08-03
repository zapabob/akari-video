#!/usr/bin/env python3
"""独自機能の .akari/*.json が公式最新スキーマ(packages/schemas)に追従しているか検証する。

jsonschema があれば厳密検証、無ければ必須キー/型の構造検査にフォールバックする。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "packages" / "schemas"

# 独自データファイル -> 公式スキーマ
PAIRS = {
    ".akari/intake.json": "intake.schema.json",
    ".akari/connections.json": "connections.schema.json",
}
# 公式スキーマが無い独自拡張（TS インターフェース準拠を目視確認する対象）
NO_SCHEMA = [".akari/workflow.json"]


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def structural_check(data, schema, path="$") -> list[str]:
    errs: list[str] = []
    t = schema.get("type")
    if t == "object" and isinstance(data, dict):
        for req in schema.get("required", []):
            if req not in data:
                errs.append(f"{path}: 必須キー '{req}' が欠落（公式スキーマ更新に未追従）")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in data:
                if k not in props:
                    errs.append(f"{path}.{k}: 公式スキーマに無いキー（独自拡張 or 廃止済み）")
        for k, v in data.items():
            if k in props:
                errs += structural_check(v, props[k], f"{path}.{k}")
    elif t == "array" and isinstance(data, list):
        item = schema.get("items")
        if isinstance(item, dict):
            for i, v in enumerate(data):
                errs += structural_check(v, item, f"{path}[{i}]")
    elif t and isinstance(t, str):
        ok = {
            "string": str, "number": (int, float), "integer": int,
            "boolean": bool, "object": dict, "array": list,
        }.get(t)
        if ok and not isinstance(data, ok):
            errs.append(f"{path}: 型不一致 期待={t} 実際={type(data).__name__}")
    if "enum" in schema and data not in schema["enum"]:
        errs.append(f"{path}: enum 外の値 {data!r} 許容={schema['enum']}")
    return errs


def main() -> int:
    try:
        import jsonschema  # type: ignore
        strict = True
    except ImportError:
        jsonschema = None
        strict = False
    print(f"■ 検証モード: {'jsonschema 厳密' if strict else '構造検査フォールバック'}")

    failed = 0
    for rel, sname in PAIRS.items():
        f, s = ROOT / rel, SCHEMA_DIR / sname
        if not f.exists():
            print(f"SKIP {rel}: 独自ファイルなし"); continue
        if not s.exists():
            print(f"WARN {rel}: 公式スキーマ {sname} が消滅 → API 変更の可能性"); failed += 1; continue
        data, schema = load(f), load(s)
        if strict:
            v = jsonschema.Draft7Validator(schema)
            errs = [f"$.{'.'.join(map(str, e.path))}: {e.message}" for e in v.iter_errors(data)]
        else:
            errs = structural_check(data, schema)
        if errs:
            failed += 1
            print(f"NG   {rel} ← {sname}")
            for e in errs[:20]:
                print("      -", e)
        else:
            print(f"OK   {rel} ← {sname} (公式最新スキーマに追従済み)")

    for rel in NO_SCHEMA:
        f = ROOT / rel
        if f.exists():
            print(f"INFO {rel}: 公式スキーマ未提供（TS: akari-workflow-service.ts の AkariWorkflow 準拠）")
            print(f"      keys = {sorted(load(f).keys())}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
