"""omni評価セット（`compe/t1/omni_eval_tasks.csv`、31件）で評価する。

既存のローカル評価セットがLIBERO-plusの7摂動次元のうち2次元しか触っておらず、
本番スコアの代理にならなかったため用意したもの（`competition_analysis.md`
「ローカル評価セットが本番の難易度を再現できていない」節）。
Background Textures / Light Conditions に加えて **Objects Layout** と
**Language Instructions** をカバーする。セットの作り方と、カバーできない
3次元（カメラ視点・ロボット初期状態・センサノイズ）については
`src/build_omni_eval_set.py`のdocstringを参照。

`eval_holdout.py`と同じく、`EnvironmentManager`の生成より前にスイートを
登録する必要がある。

使い方:

    # 別ターミナルでポリシーサーバーを起動しておくこと
    source env.sh
    venv/bin/python src/eval_omni.py --server-url http://localhost:8000 --episodes 3

結果はカテゴリ別に集計して表示する（どの次元で落ちているかを見るため）。

注意: 1つのポリシーサーバーに評価クライアントを同時に2つ以上つながないこと。
"""

from __future__ import annotations

import csv
import runpy
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_CSV = _REPO_ROOT / "compe" / "t1" / "omni_eval_tasks.csv"


def _category_of() -> dict[str, str]:
    with open(_CSV, newline="") as f:
        return {r["task_id"]: r["category"] for r in csv.DictReader(f)}


def main() -> None:
    from compe.t1.register_omni import register_omni

    register_omni()
    cats = _category_of()
    print(f"libero_omni スイートを登録した（{len(cats)}件）")

    argv = sys.argv[1:]
    if not any(a == "--benchmark" for a in argv):
        argv = ["--benchmark", "libero_omni", *argv]

    sys.argv = ["record_rollout.py"] + argv
    ns = runpy.run_path(str(_REPO_ROOT / "src" / "record_rollout.py"), run_name="__main__")

    # record_rollout.py 側が結果を返さないので、標準出力の集計は呼び出し側で
    # 行う。ここではカテゴリ対応表だけ出しておき、集計は summarize_omni() に任せる。
    del ns


def summarize(log_path: Path) -> None:
    """`eval_omni.py`の出力ログからカテゴリ別成功率を集計して表示する。"""
    import re

    cats = _category_of()
    per_task: dict[str, float] = {}
    for line in log_path.read_text().splitlines():
        m = re.match(r"^(\S+): ([\d.]+)% \(\d+ episodes\)$", line)
        if m and m.group(1) in cats:
            per_task[m.group(1)] = float(m.group(2))

    by_cat: dict[str, list[float]] = defaultdict(list)
    for task, rate in per_task.items():
        by_cat[cats[task]].append(rate)

    print(f"\n{'カテゴリ':24s} {'タスク数':>7s} {'成功率':>8s}")
    for cat in sorted(by_cat):
        rates = by_cat[cat]
        print(f"{cat:24s} {len(rates):7d} {sum(rates) / len(rates):7.1f}%")
    if per_task:
        overall = sum(per_task.values()) / len(per_task)
        print(f"{'Overall (タスク平均)':24s} {len(per_task):7d} {overall:7.1f}%")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--summarize":
        summarize(Path(sys.argv[2]))
    else:
        main()
