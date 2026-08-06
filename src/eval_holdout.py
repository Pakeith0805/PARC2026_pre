"""`compe/t1/holdout_test_tasks.csv` の15ケース（libero_holdout）で評価する。

`pipeline/environment.py`が自動登録するのは`libero_t1`（exampleタスク）だけで、
holdoutスイートは`compe.t1.register_holdout.register_holdout()`を明示的に
呼ばないとベンチマーク辞書に載らない。`EnvironmentManager.__init__`が
`get_benchmark_dict()`をスナップショットするため、**登録はEnvironmentManagerの
生成より前**でなければならない。このスクリプトはそれを保証したうえで
`record_rollout.py`をそのまま起動する（引数は同じものが全部通る）。

使い方:

    # 別ターミナルでポリシーサーバーを起動しておくこと
    source env.sh
    venv/bin/python src/eval_holdout.py --server-url http://localhost:8000 --episodes 3

holdoutは`my_strategy.md`方針2で「3スイートそれぞれから基本タスクを1つ抜いて
学習に使わない」と決めたもので、LoRAの効果を測る本命の指標。ただし本番の採点
タスクとも別物である点に注意（`submission_log.md`参照）。

注意: 1つのポリシーサーバーに評価クライアントを同時に2つ以上つながないこと。
action chunkのキューと`/reset`が混線して成功率が実際より大幅に低く出る。
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main() -> None:
    from compe.t1.register_holdout import register_holdout

    register_holdout()
    print("libero_holdout スイートを登録した（15ケース）")

    argv = sys.argv[1:]
    if not any(a == "--benchmark" for a in argv):
        argv = ["--benchmark", "libero_holdout", *argv]

    sys.argv = ["record_rollout.py"] + argv
    runpy.run_path(str(_REPO_ROOT / "src" / "record_rollout.py"), run_name="__main__")


if __name__ == "__main__":
    main()
