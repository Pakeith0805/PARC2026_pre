"""摂動なしの素のLIBERO（`LIBERO/`）でポリシーサーバーを評価する。

`record_rollout.py`は`env.sh`が指す`LIBERO-plus/`（摂動入りタスク）を見るため、
「モデル自体が壊れているのか、摂動に弱いだけなのか」を切り分けられない。この
スクリプトは`LIBERO_ROOT`を素の`LIBERO/`に向けたうえで`record_rollout.py`を
そのまま起動する。切り分けの実例は`competition_analysis.md`の
「0点の真因: n_action_steps」節を参照。

素のLIBEROは`init_states`を`torch.load`で読むが、torch>=2.6の
`weights_only=True`既定に未対応で`UnpicklingError`になる。ローカル検証の
ためだけにここで既定を戻している（提出物には一切影響しない）。

使い方（引数は record_rollout.py と同じものがそのまま通る）:

    # 別ターミナルでポリシーサーバーを起動しておくこと
    source env.sh
    venv/bin/python src/eval_vanilla_libero.py \
        --server-url http://localhost:8000 \
        --benchmark libero_object --episodes 1 --max-steps 300 --camera-size 128

注意: 1つのポリシーサーバーに評価クライアントを同時に2つ以上つないではいけない。
サーバー側のポリシーは単一インスタンスで、action chunkのキューと`/reset`が
混線し、成功率が実際より大幅に低く出る（実際に15%/20%という嘘の数字を踏んだ）。
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VANILLA_LIBERO = _REPO_ROOT / "LIBERO"


def _patch_torch_load() -> None:
    import torch

    _orig_load = torch.load

    def _load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return _orig_load(*args, **kwargs)

    torch.load = _load


_REEXEC_FLAG = "_EVAL_VANILLA_LIBERO_REEXEC"


def _reexec_with_vanilla_libero() -> None:
    """PYTHONPATH/LIBERO_ROOTを差し替えて自分自身を起動し直す。

    `env.sh`が`PYTHONPATH`の先頭に`LIBERO-plus/`を置くため、インタプリタ起動後に
    `sys.path`をいじっても`libero`パッケージはLIBERO-plus側から解決されてしまう
    （実際にこれで摂動入りタスクを掴んだ）。環境変数はインタプリタ起動時にしか
    読まれないので、素直にexecし直す。
    """
    env = dict(os.environ)
    env["LIBERO_ROOT"] = str(_VANILLA_LIBERO)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_VANILLA_LIBERO), str(_REPO_ROOT), str(_REPO_ROOT / "compe")]
    )
    env[_REEXEC_FLAG] = "1"
    os.execve(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], env)


def main() -> None:
    if not _VANILLA_LIBERO.is_dir():
        sys.exit(f"素のLIBEROが見つからない: {_VANILLA_LIBERO}")

    if os.environ.get(_REEXEC_FLAG) != "1":
        _reexec_with_vanilla_libero()  # 戻ってこない

    _patch_torch_load()

    # liberoは名前空間パッケージ（__init__.pyが無い）で__file__がNoneのため、
    # __path__で解決元を確かめる。LIBERO-plus側から読まれていたら意味が無い。
    import libero

    origins = [str(p) for p in getattr(libero, "__path__", [])]
    if not any(o.startswith(str(_VANILLA_LIBERO)) for o in origins):
        sys.exit(f"liberoが素のLIBEROから読まれていない: {origins}")

    print(f"LIBERO_ROOT = {os.environ['LIBERO_ROOT']}（摂動なしの素のLIBERO）")
    sys.argv = ["record_rollout.py"] + sys.argv[1:]
    runpy.run_path(str(_REPO_ROOT / "src" / "record_rollout.py"), run_name="__main__")


if __name__ == "__main__":
    main()
