"""ローカル検証用: omni評価セットをLIBERO-plusベンチマークに登録する。

`register_holdout.py`と同じ作りで、`omni_eval_tasks.csv`（`src/build_omni_eval_set.py`
が生成する31件）を"libero_omni"という別スイートとして登録する。狙いは
`competition_analysis.md`「ローカル評価セットが本番の難易度を再現できていない」
節を参照。

`register_holdout`との違いは`problem_folder`の決め方だけ。Objects Layout
(`_add_N`)やLanguage(`_language_N`)の`.bddl`は、そのタスクが本来属するスイートの
フォルダではなく`libero_mix/`に置かれているため、CSVの`suite`列には
**実ファイルが在るフォルダ名**を入れてある（`build_omni_eval_set.py`が
`.bddl`の親ディレクトリ名をそのまま書いている）。

使い方:
    from compe.t1.register_omni import register_omni
    register_omni()
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import torch

from compe.t1.register import _install_support_contact_guard

_SUITE = "libero_omni"
_PKG_DIR = Path(__file__).resolve().parent
_CSV = _PKG_DIR / "omni_eval_tasks.csv"

_REGISTERED = False

# シーンそのものは変えない摂動。initはベースタスクのものを共有できる。
# 配布`register.py`の`_SUFFIX_RE`は`_light_*`と`_table_\d+`しか剥がさないので、
# 言い換え（`_language_N`）を足したこれを自前で使う。
# Objects Layout（`_add_N` / `*_level*_sample*`）は物体構成が変わるため
# ベースのinitを流用してはいけない（専用のinitが`init_files/libero_newobj/`に在る）。
_SCENE_PRESERVING_RE = re.compile(r"_light_[^.]*|_table_\d+|_language_\d+")


def _init_states_for(task, get_libero_path):
    """omniセット用のinit state解決。

    1. まず完全一致のファイルを探す（Objects Layoutはこちら。
       `init_files/libero_newobj/<folder>/`に在り、配布`register.py`の
       `<root>/<problem_folder>/`決め打ちでは見つからない）。
    2. 無ければシーン非変更の接尾辞を剥がしてベースのinitを使う
       （背景テクスチャ・照明・言い換え）。
    """
    root = Path(get_libero_path("init_states"))
    stem = Path(task.init_states_file).stem

    for candidate in (stem, _SCENE_PRESERVING_RE.sub("", stem)):
        hits = sorted(root.glob(f"*/{candidate}.pruned_init")) + sorted(
            root.glob(f"*/*/{candidate}.pruned_init")
        )
        if hits:
            states = torch.load(hits[0], weights_only=False)
            # ベースタスクのinitは (n_episodes, state_dim) だが、Objects Layout用の
            # initは1エピソード分だけの (state_dim,) で保存されている。呼び出し側は
            # `init_states[i]`で1本取り出す前提なので2次元に揃える。
            # （結果としてObjects Layoutは全エピソードが同じ初期状態になり、
            #   エピソード間の違いはポリシー側のサンプリングノイズだけになる）
            if states.ndim == 1:
                states = states.reshape(1, -1)
            return states

    raise FileNotFoundError(
        f"{task.name} のinit stateが見つからない（root={root}）。"
        "omni_eval_tasks.csv から外すか、LIBERO-plusのチェックアウトを確認すること。"
    )


def _load_rows() -> list[dict]:
    with open(_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise RuntimeError(f"{_CSV} is empty; cannot register {_SUITE}.")
    return rows


def register_omni():
    global _REGISTERED
    from libero.libero import benchmark as _b
    from libero.libero import get_libero_path

    _install_support_contact_guard()
    rows = _load_rows()
    _b.task_maps[_SUITE] = {
        r["task_id"]: _b.Task(
            name=r["task_id"],
            language=r["instruction"],
            problem="Libero",
            problem_folder=r["suite"],
            bddl_file=f"{r['task_id']}.bddl",
            init_states_file=f"{r['task_id']}.pruned_init",
        )
        for r in rows
    }
    if _SUITE not in _b.libero_suites:
        _b.libero_suites.append(_SUITE)

    if _REGISTERED:
        return _b.get_benchmark(_SUITE)

    @_b.register_benchmark
    class LIBERO_OMNI(_b.Benchmark):
        def __init__(self, task_order_index: int = 0):
            assert task_order_index == 0, (
                f"{_SUITE} has a variable task count; only task_order_index=0 supported."
            )
            super().__init__(task_order_index=task_order_index)
            self.name = _SUITE
            self._make_benchmark()

        def _make_benchmark(self):
            self.tasks = list(_b.task_maps[self.name].values())
            self.n_tasks = len(self.tasks)

        def get_task_init_states(self, i):
            return _init_states_for(self.tasks[i], get_libero_path)

    _REGISTERED = True

    return _b.get_benchmark(_SUITE)
