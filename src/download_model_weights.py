"""submission_template/model_weights/hf_cache/ にモデル一式を事前ダウンロードする。

採点環境は外部通信を遮断するため（README.md参照）、提出物に同梱した
Hugging Faceキャッシュだけで完全にオフライン起動できる必要がある。この
スクリプトは MyPolicy を実際にネットワークありで一度動かし（初期化＋1回の
推論）、そのとき触れたファイル一式を HF_HOME 経由でキャッシュに落とす。
「どのファイルが要るか」を手で列挙するより、実際のコードパスを走らせて
何が要求されるかを見る方が確実（SmolVLM2のトークナイザ等、
`policy_server.py`のコードだけを眺めていると見落としがちなダウンロードが
裏で発生するため）。

使い方（GPU + torch/lerobotが入ったvenvで実行すること。詳細はsrc/README.md）:

    python src/download_model_weights.py

実行後、submission_template/model_weights/hf_cache/ にキャッシュができる。
policy_server.py はこのディレクトリの有無を見て、あれば
HF_HUB_OFFLINE=1 で完全オフライン動作に切り替わる。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HF_CACHE_DIR = _REPO_ROOT / "submission_template" / "model_weights" / "hf_cache"

# policy_server.py 側のオフライン切り替えロジックより前に、ここでは
# ダウンロードさせたいのでオフラインフラグは立てない。HF_HOMEだけ、
# 同梱予定のキャッシュ先に向ける。
os.environ["HF_HOME"] = str(_HF_CACHE_DIR)
os.environ.pop("HF_HUB_OFFLINE", None)
# 既定のHFキャッシュは blobs/ の実体を snapshots/ からsymlinkで参照する構造だが、
# validate_submission.py の zip.slip_symlink チェックがsymlinkエントリを
# 一律拒否するため、提出zipに含められない。symlinkを使わず実ファイルとして
# 展開させる。
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"

if str(_REPO_ROOT / "submission_template") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "submission_template"))


def main() -> None:
    import numpy as np

    from policy_server import MyPolicy

    print(f"HF_HOME = {os.environ['HF_HOME']}")
    print("MyPolicy() を初期化中（ネットワークからダウンロード）...")
    policy = MyPolicy()
    print("初期化完了。疎通確認のため1回だけ推論を実行します。")

    rng = np.random.default_rng(0)
    obs = {
        "agentview_image": rng.integers(0, 256, size=(128, 128, 3), dtype=np.uint8),
        "robot0_eye_in_hand_image": rng.integers(0, 256, size=(128, 128, 3), dtype=np.uint8),
        "robot0_joint_pos": rng.uniform(-2.8, 2.8, size=(7,)).astype(np.float32),
        "robot0_eef_pos": rng.uniform(-0.5, 0.5, size=(3,)).astype(np.float32),
        "robot0_eef_quat": np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
        "robot0_gripper_qpos": np.array([0.02, -0.02], dtype=np.float32),
    }
    policy.reset(instruction="pick up the black bowl and place it on the plate")
    action = policy.get_action(obs)
    print(f"推論成功: action={action}")

    # ダウンロード中に作られる一時ファイル・空のロックファイルはzipに含める
    # 必要がないので削除しておく。
    for lock_dir in _HF_CACHE_DIR.rglob(".locks"):
        import shutil

        shutil.rmtree(lock_dir, ignore_errors=True)

    symlinks = [f for f in _HF_CACHE_DIR.rglob("*") if f.is_symlink()]
    if symlinks:
        print(
            f"\n警告: symlinkが{len(symlinks)}件残っています"
            "（zip提出時にvalidate_submission.pyのzip.slip_symlinkチェックで"
            "弾かれる）。HF_HUB_DISABLE_SYMLINKS=1が効いているか確認すること。"
        )
        for s in symlinks[:5]:
            print(f"  {s}")

    total_bytes = sum(f.stat().st_size for f in _HF_CACHE_DIR.rglob("*") if f.is_file())
    print(f"\nキャッシュ先: {_HF_CACHE_DIR}")
    print(f"合計サイズ: {total_bytes / 1024**2:.1f} MB")
    print(
        "\n次回以降、policy_server.py はこのディレクトリを検出して"
        " HF_HUB_OFFLINE=1 で起動するようになる。"
    )


if __name__ == "__main__":
    main()
