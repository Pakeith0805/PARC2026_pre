"""ローカル検証用: holdoutタスクをLIBERO-plusベンチマークに登録する。

`register.py`（配布された`register_t1`）は変更せず、その中の再利用可能な
ヘルパー（`_init_states_for` / `_install_support_contact_guard`）だけを
import して、`holdout_test_tasks.csv`（自前で選定した15件のholdout
テストケース）を"libero_holdout"という別ベンチマークスイートとして登録する。

`register_t1()`と同じ使い方:
    from compe.t1.register_holdout import register_holdout
    register_holdout()
"""

from __future__ import annotations

import csv
from pathlib import Path

from compe.t1.register import _init_states_for, _install_support_contact_guard

_SUITE = "libero_holdout"
_PKG_DIR = Path(__file__).resolve().parent
_CSV = _PKG_DIR / "holdout_test_tasks.csv"

_REGISTERED = False


def _load_rows() -> list[dict]:
    with open(_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise RuntimeError(f"{_CSV} is empty; cannot register {_SUITE}.")
    return rows


def register_holdout():
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
    class LIBERO_HOLDOUT(_b.Benchmark):
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
