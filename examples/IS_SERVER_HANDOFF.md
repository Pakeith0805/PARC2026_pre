# IS計算機サーバー 作業依頼: 学習エピソード数を5→200に増やして再学習

作成日: 2026-08-06 / 作成環境: `askr5090`（IS計算機サーバーとは別マシン）

このファイルはIS計算機サーバー側で作業する人／AIエージェント向けの申し送りです。
**やることは2つだけです: (A) データセットの残りをダウンロードする、(B) 設定を1行変えて再学習する。**

---

## 背景（なぜやるのか）

現在の提出物は本番スコア `public_score 0.12839`。この状態から改善するために
ローカル（askr5090）で原因を切り分けた結果、**既存のLoRAは効いていない**ことと、
**その理由**が分かりました。

### 既存LoRAは弱点に一切効いていない

7摂動次元のうち4次元をカバーする評価セット（`libero_omni`、31タスク）で、
ベース重みと既存LoRA（40,000ステップ、マージ済み）を同条件比較した結果:

| カテゴリ | ベース | 既存LoRA | Δ |
|---|---|---|---|
| Background Textures | 85.7% | 71.4% | −14.3 |
| Light Conditions | 76.2% | 85.7% | +9.5 |
| Objects Layout | 29.2% | 29.2% | ±0 |
| Language Instructions | 11.1% | 11.1% | ±0 |
| **Overall** | **47.3%** | **46.2%** | **−1.1** |

Language Instructionsは9タスク全てで成功率が完全一致（＝LoRAの影響ゼロ）。
31タスク中22タスクが同一で、動いた分もノイズの範囲でした。

### 理由: 学習に使ったエピソードが全体の約1%だった

データセット `lerobot/libero_plus` のローカルキャッシュを直接開いて数えた結果:

- `total_episodes: 14347` / `total_frames: 2,238,036` / 40タスク
- **学習対象の30タスクだけで 11,556 エピソード**利用可能（1タスクあたり 200〜500）
- ところが `smolvla_parc_lora_config.yaml` は **`train_episodes_per_task: 5`**
- つまり **30タスク × 5 = 150エピソード**しか使わずに 40,000 ステップ回していた

背景・照明・物体配置の摂動バリエーションは1タスクあたり数百エピソードとして
データに入っているのに、そのうち5本しか見せていなかった、という状態です。
**「LoRAが効かなかった」のではなく、効きようのない条件で学習していました。**

（なお言語ロバスト性については、このデータセットの `meta/tasks.parquet` に
ユニークなtask labelが40件しか無く**全て素の指示文**で、言い換え表現が1件も
含まれていません。エピソード数を増やしても Language Instructions は改善しません。
そちらは別途データを作る必要があり、今回のスコープ外です。）

---

## (A) データセットの残りをダウンロードする

### 現状

askr5090側のキャッシュを調べたところ、動画ファイルが**76ファイル中34ファイル**しか
落ちていませんでした（front 16/40、wrist 18/36）。これはIS計算機サーバー側でも
同様である可能性が高いので、**まず現状を確認してください**。

```bash
D=$(ls -d "$HOME/parc_lora_workspace/lerobot_cache/hub/datasets--lerobot--libero_plus/snapshots/"*/ | head -1)
find "$D/videos" -name '*.mp4' | wc -l    # 76 なら完了済み。それ未満なら要ダウンロード
du -sh "$HOME/parc_lora_workspace/lerobot_cache/hub/datasets--lerobot--libero_plus/blobs"
```

askr5090では34ファイルで 6.6GB でした。全76ファイルだと **合計15GB前後**、
つまり**追加で8GB程度**のダウンロードと空き容量が要ります。

### ダウンロード手順

**ログインノード（ネットワークが使えるノード）で実行してください。**
計算ノードのジョブ内では `HF_HUB_OFFLINE=1` が設定されているため落とせません。

```bash
cd "$HOME/Projects/PARC2026_pre"
source .venv_train/bin/activate

export HF_HOME="$HOME/parc_lora_workspace/hf_cache"
export HF_LEROBOT_HOME="$HOME/parc_lora_workspace/lerobot_cache"
unset HF_HUB_OFFLINE          # ここが重要

python - <<'PY'
import os
from huggingface_hub import snapshot_download

path = snapshot_download(
    repo_id="lerobot/libero_plus",
    repo_type="dataset",
    revision="f3f49f426d75030177b18778374005bc12ccd588",   # configのdataset.revisionと一致させること
    cache_dir=os.environ["HF_LEROBOT_HOME"] + "/hub",
    max_workers=4,
)
print("完了:", path)
PY
```

- `revision` は `examples/smolvla_parc_lora_config.yaml` の `dataset.revision`
  と**必ず一致**させてください。ずれると学習時に別スナップショットを探しに行って
  オフラインで落ちます。
- 429（レート制限）が出たら `max_workers` を下げて再実行してください。
  途中まで落ちたファイルは再開されます。

### ダウンロード後の検証

```bash
D=$(ls -d "$HOME/parc_lora_workspace/lerobot_cache/hub/datasets--lerobot--libero_plus/snapshots/f3f49f426d75030177b18778374005bc12ccd588/")
for c in front wrist; do echo -n "$c: "; find "$D/videos" -path "*$c*" -name '*.mp4' | wc -l; done
# 期待値: front 40 / wrist 36
```

---

## (B) 設定を変えて再学習する

### 変更点は1行だけ

`examples/smolvla_parc_lora_config.yaml`:

```yaml
dataset:
  repo_id: lerobot/libero_plus
  revision: f3f49f426d75030177b18778374005bc12ccd588
  train_episodes_per_task: 200      # ← 5 から 200 に変更
```

### なぜ200なのか（これが上限です）

Notebookのセル12は `choose_evenly_spaced()` で各タスクから等間隔に
`train_episodes_per_task` 本を選び、そのあと

```python
if len(EPISODE_INDICES) != expected_episodes:
    raise RuntimeError("Episode selection failed: ...")
```

で件数を検証しています。**あるタスクの保有エピソード数を超える値を指定すると
同じインデックスが重複して選ばれ、`sorted(set(...))` で潰れた結果この
RuntimeErrorで落ちます。**

学習対象30タスクのうち最小は `open the top drawer and put the bowl inside` の
**200エピソード**です。したがって **200 が安全な最大値**で、
30タスク × 200 = **6,000エピソード**（現行の40倍）になります。

201以上にしたい場合は、`choose_evenly_spaced()` の呼び出しを
「保有数と指定値の小さい方を使う」形に変え、件数検証も併せて緩める必要があります
（タスクごとの本数が不均等になります）。**今回はまず200で、均等な条件のまま
「エピソード数を増やせば効くのか」を確かめたい**ので、コード変更は不要です。

### 学習時間は増えません

`steps: 40000` × `batch_size: 8` は変えないので、GPUの計算量は前回と同じです。
増えるのはデータの多様性だけです。ただし**データローダのI/Oは重くなります**
（40倍のエピソードにランダムアクセスするため）。`--num_workers=8` は既に
設定済みなので、`--cpus-per-task=16` を確保してください。

### 投入コマンド

```bash
cd "$HOME/Projects/PARC2026_pre"
sbatch -J parc_train_ep200 -p pro_6000 --gres=gpu:pro_6000:1 \
  --cpus-per-task=16 --time=2-00:00:00 examples/is_server_train.sbatch
```

`examples/is_server_train.sbatch` の冒頭コメントにある通り:

- **`--qos=low` は避けてください。** lowQoSは中断されうる一方、Notebookは
  `--save_freq={STEPS}` で最終ステップにしかチェックポイントを保存しません。
  中断されると40,000ステップ分が丸ごと消えます。normalQoSが使えるならそちらを。
  lowQoSしか使えない場合は、Notebookの `--save_freq` を 5000 程度に変えてから
  投入することを強く推奨します。
- `a100_1g` / `a100_3g` はCPU数不足のため本番学習には不適です。

### mode の選択

`config.yaml` の `mode` は現在 `holdout_eval` です。

- **`holdout_eval`**: holdout 3タスクを学習から除外（27タスク × 200 = 5,400エピソード）。
  学習後にrobosuite/MuJoCoを立てて自動評価まで走ります。**効果検証が目的なら
  こちら**（ただし後述の注意あり）。
- **`full_submission`**: 30タスク全部を使う（6,000エピソード）。提出用の重みを
  作るならこちら。

**まず `holdout_eval` で効果を確認し、良ければ `full_submission` で作り直す**、
という順を推奨します。

---

## 完了後にこちらに返してほしいもの

1. **マージ済みモデル一式**（`$HOME/parc_lora_workspace/smolvla_parc_lora_*_merged/`）。
   865MB程度です。
2. **学習ログ**（`parc_train_ep200-<jobid>.out`）と、実行済みNotebook
   （`$HOME/parc_lora_workspace/nbconvert_out/`）。
3. Notebook内蔵の評価結果が出ていればその数値（ただし下記の注意を参照）。

受け取ったら askr5090 側で `src/eval_omni.py` を使って、この申し送りの冒頭に
ある表と**同じ条件**で測り直します。

### Notebook内蔵の評価結果の扱いに注意

Notebookのセル24の評価は **`camera_height=256, camera_width=256`** で走ります。
**本番の採点は128×128固定**で、しかもこの解像度差は決定的な影響を持ちます
（`n_action_steps=50` のとき128pxで10%・256pxで30%という差が実測で出ています。
詳細は `competition_analysis.md` の「0点の真因」節）。

またNotebookの評価はcheckpointの `n_action_steps=50` をそのまま使いますが、
**提出物側は10に変更済み**です（`my_strategy.md` 方針8）。

したがって **Notebook内蔵の評価値は提出時の性能を表しません。**
判断材料にはせず、askr5090側での再測定を待ってください。

---

## 触ってはいけないもの

- `pipeline/` 配下（配布された評価ハーネス。読み取り専用で使う）
- `compe/t1/register.py`（配布ファイル。`register_holdout.py` /
  `register_omni.py` は自前の追加なので触ってよい）
- `submission_template/vendor/`（提出物に同梱するlerobot 0.4.4のソース。
  IS計算機サーバー側のlerobotは0.6.0で別物）

## 参照

- 判断の経緯: `my_strategy.md`（方針1〜8）
- 技術的な調査記録: `competition_analysis.md`
- 提出履歴とスコア: `submission_log.md`
- ローカル評価ツールの使い方: `src/README.md`
