"""合成的な「全次元」ローカル評価セット（libero_omni）のタスク一覧を生成する。

## なぜ必要か

既存のローカル評価セット（`compe/t1/T1_TASKS.csv`のexample 4件、
`compe/t1/holdout_test_tasks.csv`の15件）は、LIBERO-plusの7摂動次元のうち
**Background Textures と Light Conditions の2次元しか触っていない**。
そのためベース重みがローカルholdoutで77.8%を出す一方、本番スコアは0.12839と
大きく乖離した（`competition_analysis.md`参照）。ローカル指標が本番の代理に
なっていない状態では、モデルの改善を判断できない。

## 何を作るか

`my_strategy.md`方針2で学習から除外した3つの基本タスク（3スイート各1つ）に
ついて、**ローカルに実体ファイルが存在する全カテゴリ**の摂動変種を、難易度を
散らして選ぶ。学習に使っていない基本タスクなので、汎化性能の指標になる。

    libero_spatial : pick up the black bowl in the top drawer ... on the plate
    libero_object  : pick up the bbq sauce and place it in the basket
    libero_goal    : put the bowl on the stove

## カバーできる次元とできない次元（2026-08-06実測）

上記3基本タスクの変種について、`.bddl`実体の有無を数えた結果:

| 次元 | 変種数 | `.bddl`実体 | 扱い |
|---|---|---|---|
| Background Textures | 79 | あり | **採用** |
| Light Conditions | 97 | あり | **採用** |
| Objects Layout | 117 | あり | **採用**（既存セットは未使用。L4/L5が66件と難物が揃う） |
| Language Instructions | 82 | 無し | 難易度ラベル付きの名前には実体が無いが、**ラベル無しの
  `<base>_language_N.bddl`が各50件実在**するので、そちらを**採用**（難易度は不明として扱う） |
| Camera Viewpoints | 127 | 無し | **不可**。ハーネスの`camera_view_shift`も未実装（`PerturbationConfig`に
  フィールドはあるが`environment.py`から一度も参照されていない） |
| Robot Initial States | 116 | 無し | **不可**。`get_perturbed_init_states()`は
  `robot_init_pos_noise>0`でログを出すだけで`sampled_states`を書き換えていない |
| Sensor Noise | 110 | 無し | 静的ファイルは無いが、ハーネスの`apply_observation_noise()`は
  **実装済み**なので実行時ノイズで近似できる（このスクリプトの範囲外。別途対応） |

つまりこのセットは7次元中4次元をカバーする。残る3次元（カメラ視点・ロボット
初期状態・センサノイズ）は本番で確実に問われるため、ローカル値は依然として
本番より甘い。**それでも2次元→4次元は大きな改善**で、特にObjects Layoutの
L4/L5が入る意味は大きい。

## 選定ルール（決定的、seed固定）

各(基本タスク × カテゴリ)について、難易度L1/L3/L5から1変種ずつ選ぶ
（存在しないレベルは飛ばす）。Language Instructionsは難易度ラベルが無いため
一律3変種を選ぶ。名前でソートしてから固定seedでサンプルするので、何度実行しても
同じCSVになる。

使い方:

    .local_libs/verify/venv_final_check/bin/python src/build_omni_eval_set.py
"""

from __future__ import annotations

import csv
import json
import random
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LIBERO = _REPO_ROOT / "LIBERO-plus" / "libero" / "libero"
_OUT = _REPO_ROOT / "compe" / "t1" / "omni_eval_tasks.csv"

_SEED = 42
_LEVELS = (1, 3, 5)
_N_LANGUAGE = 3

# my_strategy.md 方針2 で学習から除外した基本タスク（suite -> (task名, 素の指示文)）
_BASES = {
    "libero_spatial": (
        "pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate",
        "Pick the akita black bowl in the top layer of the wooden cabinet and place it on the plate",
    ),
    "libero_object": (
        "pick_up_the_bbq_sauce_and_place_it_in_the_basket",
        "Pick the bbq sauce and place it in the basket",
    ),
    "libero_goal": (
        "put_the_bowl_on_the_stove",
        "Put the bowl on the stove",
    ),
}

_LANGUAGE_RE = re.compile(r"\(:language\s+(.+?)\)\s*$", re.MULTILINE)


def _index_bddl() -> dict[str, Path]:
    """全スイートフォルダを横断して .bddl を名前で引けるようにする。

    Objects Layout(`_add_N`)や Language(`_language_N`)は、そのタスクが属する
    スイートのフォルダではなく`libero_mix/`に置かれているため、
    フォルダ決め打ちでは見つからない。
    """
    return {
        p.stem: p
        for d in (_LIBERO / "bddl_files").iterdir()
        if d.is_dir()
        for p in d.glob("*.bddl")
    }


def _instruction_from_bddl(path: Path, fallback: str) -> str:
    m = _LANGUAGE_RE.search(path.read_text())
    return m.group(1).strip() if m else fallback


def main() -> None:
    rng = random.Random(_SEED)
    bddl = _index_bddl()
    cls = json.loads((_LIBERO / "benchmark" / "task_classification.json").read_text())

    rows: list[dict] = []

    for suite, (base, base_instruction) in _BASES.items():
        # 難易度ラベル付きカテゴリ（実体があるものだけ）
        by_cat_lvl: dict[tuple[str, int], list[str]] = {}
        for t in cls[suite]:
            if not t["name"].startswith(base) or t["name"] not in bddl:
                continue
            by_cat_lvl.setdefault((t["category"], t["difficulty_level"]), []).append(t["name"])

        for (cat, lvl), names in sorted(by_cat_lvl.items()):
            if lvl not in _LEVELS:
                continue
            name = rng.choice(sorted(names))
            rows.append(
                {
                    "task_id": name,
                    "instruction": _instruction_from_bddl(bddl[name], base_instruction),
                    "suite": bddl[name].parent.name,
                    "category": cat,
                    "difficulty_level": f"L{lvl}",
                }
            )

        # Language Instructions は難易度ラベルが無いので別扱い
        lang = sorted(n for n in bddl if n.startswith(base + "_language_"))
        for name in rng.sample(lang, min(_N_LANGUAGE, len(lang))):
            rows.append(
                {
                    "task_id": name,
                    "instruction": _instruction_from_bddl(bddl[name], base_instruction),
                    "suite": bddl[name].parent.name,
                    "category": "Language Instructions",
                    "difficulty_level": "unlabeled",
                }
            )

    rows.sort(key=lambda r: (r["category"], r["difficulty_level"], r["task_id"]))
    for i, r in enumerate(rows, 1):
        r["task_num"] = i

    fields = ["task_num", "task_id", "instruction", "suite", "category", "difficulty_level"]
    with open(_OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: r[k] for k in fields} for r in rows)

    print(f"{_OUT} に {len(rows)} 件を書き出した")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    for c, n in sorted(counts.items()):
        print(f"  {n:3d}  {c}")


if __name__ == "__main__":
    main()
