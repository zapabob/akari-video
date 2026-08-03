#!/usr/bin/env python3
"""zapabob/akari-video : 公式 upstream 追従マージツール

独自機能（.akari/ 設定・.claude/ スキル・レポート類）を維持したまま、
AkariLabs/akari-video の最新機能 / 脆弱性修正 / バグフィクスを取り込む。

使い方:
    py -3 scripts/merge_upstream.py --report      # 調査のみ（差分・独自ファイル・依存更新）
    py -3 scripts/merge_upstream.py --merge       # マージブランチ作成 + 実マージ
    py -3 scripts/merge_upstream.py --merge --push
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

UPSTREAM_URL = "https://github.com/AkariLabs/akari-video.git"
UPSTREAM_REF = "upstream/main"

# 独自機能として必ず保護するパス（upstream 側に無い / 上書きさせない）
OURS_PATHS = [
    ".akari/",
    ".claude/",
    "connections-report.html",
    "skills-index.md",
    "planning/",
    "exports/",
]
# 生成物なので upstream 優先で解決してよいパス
THEIRS_PATHS = ["package-lock.json"]


def run(*args: str, check: bool = True, cwd: Path | None = None) -> str:
    p = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=cwd, encoding="utf-8", errors="replace"
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{p.stderr}")
    return p.stdout.strip()


def ensure_upstream() -> None:
    remotes = run("remote").splitlines()
    if "upstream" not in remotes:
        run("remote", "add", "upstream", UPSTREAM_URL)
    run("fetch", "upstream", "--tags")


def classify(subject: str) -> str:
    s = subject.lower()
    if any(k in s for k in ("cve", "脆弱性", "security", "vuln", "bump", "dependabot")):
        return "security"
    if any(k in s for k in ("[修正]", "[修理]", "fix", "bug", "hotfix")):
        return "fix"
    if any(k in s for k in ("[機能", "[追加]", "feat", "[変更]")):
        return "feature"
    return "other"


def report() -> dict:
    ahead, behind = run("rev-list", "--left-right", "--count", f"HEAD...{UPSTREAM_REF}").split()
    commits = run("log", "--pretty=%H\t%s", f"HEAD..{UPSTREAM_REF}").splitlines()
    buckets: dict[str, list[str]] = {"security": [], "fix": [], "feature": [], "other": []}
    for line in commits:
        sha, _, subj = line.partition("\t")
        buckets[classify(subj)].append(f"{sha[:8]} {subj}")

    ours = run("diff", "--name-only", f"{UPSTREAM_REF}...HEAD").splitlines()
    # 衝突しうるファイル = 双方で変更されたもの
    theirs = set(run("diff", "--name-only", f"HEAD...{UPSTREAM_REF}").splitlines())
    overlap = sorted(set(ours) & theirs)

    return {
        "ahead": int(ahead),
        "behind": int(behind),
        "buckets": {k: v for k, v in buckets.items()},
        "our_files": ours,
        "potential_conflicts": overlap,
    }


def print_report(r: dict) -> None:
    print(f"■ fork ahead={r['ahead']} / behind={r['behind']}")
    for k in ("security", "fix", "feature", "other"):
        v = r["buckets"][k]
        print(f"\n── {k}: {len(v)} 件")
        for line in v[:15]:
            print("   ", line)
        if len(v) > 15:
            print(f"    ... 他 {len(v)-15} 件")
    print(f"\n■ 独自変更ファイル ({len(r['our_files'])}):")
    for f in r["our_files"]:
        print("   ", f)
    print(f"\n■ 衝突しうるファイル ({len(r['potential_conflicts'])}):")
    for f in r["potential_conflicts"]:
        print("   ", f)


def resolve_conflicts() -> list[str]:
    """未解決コンフリクトをポリシーに沿って自動解決。残りを返す。"""
    unresolved = []
    for line in run("diff", "--name-only", "--diff-filter=U", check=False).splitlines():
        if any(line.startswith(p.rstrip("/")) for p in OURS_PATHS):
            run("checkout", "--ours", "--", line)
            run("add", "--", line)
        elif any(line == p for p in THEIRS_PATHS):
            run("checkout", "--theirs", "--", line)
            run("add", "--", line)
        else:
            unresolved.append(line)
    return unresolved


def merge(push: bool) -> int:
    branch = f"merge/upstream-{date.today().isoformat()}"
    base = run("rev-parse", "--abbrev-ref", "HEAD")
    run("checkout", "-B", branch)
    print(f"■ ブランチ {branch} を {base} から作成")

    p = subprocess.run(
        ["git", "merge", "--no-ff", "--no-edit", UPSTREAM_REF],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print(p.stdout or p.stderr)
    if p.returncode != 0:
        rest = resolve_conflicts()
        if rest:
            print("■ 手動解決が必要:")
            for f in rest:
                print("   ", f)
            return 2
        run("commit", "--no-edit")
        print("■ コンフリクトをポリシー自動解決してコミット")

    # 独自ファイルの生存確認
    missing = [f for f in OURS_PATHS if not Path(f.rstrip("/")).exists()]
    if missing:
        print(f"!! 独自機能が消失: {missing}")
        return 3
    print("■ 独自機能ファイル 全て保持を確認")
    print(run("log", "--oneline", "-3"))
    if push:
        print(run("push", "-u", "origin", branch))
    else:
        print(f"■ push は未実行。必要なら: git push -u origin {branch}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    ensure_upstream()
    if a.merge:
        return merge(a.push)
    r = report()
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print_report(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
