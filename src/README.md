# src/

ポリシーサーバーの動作を、LIBERO環境を実際に動かして目で確認するための補助
ツール置き場。`submission_template/`や`pipeline/`本体には手を加えず、外側から
それらを使うだけのスクリプトを置く。

## download_model_weights.py

`submission_template/model_weights/hf_cache/` にモデル一式（SmolVLA本体＋
トークナイザ）を事前ダウンロードし、提出物を完全オフラインで起動できるように
する。

**背景**: [README.md](../README.md)に「`requirements.txt`に外部ソース指定を
使用できない（採点環境は外部通信を遮断する）」とある。一方
`policy_server.py`の`MyPolicy`はデフォルトでHugging Face Hubからモデルを
ダウンロードする実装になっており、このままでは採点環境で起動できない
可能性が高い。この事前ダウンロードで解決する。

```bash
# GPU + torch/lerobotが入ったvenvで実行（ネットワークが必要）
python src/download_model_weights.py
```

実行すると`MyPolicy`を実際に一度動かし（初期化＋推論1回）、そのとき触れた
ファイル一式を`HF_HOME`経由でキャッシュに落とす。`policy_server.py`は
`model_weights/hf_cache/`の有無を見て、あれば`HF_HUB_OFFLINE=1`で完全
オフライン動作に切り替わる（無ければ従来通りオンライン取得、ローカル開発用の
後方互換）。

**symlinkに関する注意**: 既定のHFキャッシュは`blobs/`の実体を`snapshots/`から
symlinkで参照する構造だが、`validate_submission.py`の`zip.slip_symlink`
チェックがsymlinkエントリを一律拒否するため、そのままでは提出zipに含められない。
このスクリプトは`HF_HUB_DISABLE_SYMLINKS=1`を設定し、実ファイルとして展開させる
ことでこれを回避している（2026-08-02、`zip -rq -X` → `validate_submission.py`
の静的・動的チェック両方でPASSすることを確認済み）。

`model_weights/`は`.gitignore`済み（約870MB、`submission_template/requirements.txt`
の`lerobot[smolvla]==0.6.0`本体とは別に、モデル重み自体もこのスクリプトで
再生成できるためgit管理しない）。提出zipを作るときは
`zip -r submission.zip policy_server.py requirements.txt model_weights/`
（[submission_template/README.md](../submission_template/README.md)参照）。

## record_rollout.py

ポリシーサーバー（`submission_template/policy_server.py`と同じ
`/health` `/reset` `/act` インターフェース）をLIBERO環境で実際に動かし、

- タスクごとの成功率（`pipeline/scorer.py`と同じ「タスク平均」で算出）
- 各エピソードの動画（mp4, H.264）

を出力する。`pipeline/rollout.py`の`_run_episode`と同じロジック（init_state
の当て方、collisionによる成功判定）を踏襲しているので、成功率の数字は
`python -m pipeline`本番実行と同じ基準で解釈できる。

### 前提: 2つのPython環境が必要

このリポジトリの評価ハーネス用`venv/`（`numpy==1.26.4`・`robosuite==1.4.0`など
バージョン固定）と、ポリシー側が使う`torch`/`lerobot`（`numpy>=2.0`を要求）は
同じPython環境に共存できない。そのため実行は必ず2プロセスに分ける。

1. **ポリシーサーバー用の別venv**でモデルを動かす（GPU推奨）。例:

   ```bash
   uv venv --python 3.12 .venv_policy
   source .venv_policy/bin/activate
   uv pip install torch --index-url https://download.pytorch.org/whl/cu128 \
       --extra-index-url https://pypi.org/simple
   uv pip install -r submission_template/requirements.txt
   python submission_template/policy_server.py --port 8000
   ```

2. **このリポジトリの`venv/`**（`env.sh`）でLIBERO環境を動かし、
   `record_rollout.py`からHTTP経由でポリシーサーバーを呼ぶ。

   ```bash
   source env.sh
   # このサンドボックスではEGLが/dev/driの権限不足で失敗することがある。
   # その場合はソフトウェアレンダリングにフォールバックする。
   export MUJOCO_GL=osmesa   # egl が動くなら不要

   python -m pip install -q imageio-ffmpeg   # 動画書き出し用、初回だけ

   python src/record_rollout.py --server-url http://localhost:8000
   ```

### 主な引数

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--server-url` | `http://localhost:8000` | ポリシーサーバーのURL |
| `--benchmark` | `libero_t1` | 評価するLIBEROベンチマーク名（`libero_t1`=compe/t1のexample） |
| `--tasks` | 全タスク | タスクIDをスペース区切りで指定して絞り込む |
| `--episodes` | `3` | タスクあたりのエピソード数 |
| `--record-episodes` | `1` | 先頭何エピソードを録画するか（残りは成功率の集計のみ） |
| `--max-steps` | `300` | エピソードあたりの最大ステップ数 |
| `--camera-size` | `256` | レンダリング解像度（正方形）。本番の採点は128固定 |
| `--fps` | `20` | 出力動画のfps |
| `--seed` | `42` | エピソード初期化の基準シード |
| `--out-dir` | `results/rollout_videos/` | 出力先（`results/`は`.gitignore`済み） |

タスクIDの一覧は`compe/t1/T1_TASKS.csv`の`task_id`列、またはこのスクリプトを
`--tasks`なしで実行したときのログ（各`=== task: ... ===`）で確認できる。

### 出力

`<out-dir>/<task_id>_ep<N>_<success|fail>.mp4` という名前で、録画対象に指定した
エピソードだけmp4が保存される。標準出力にはエピソードごとの成否・ステップ数、
タスクごと・全体の成功率（タスク平均）が出る。

### 既知の注意点

- **同じタスク・同じseedでも試行ごとに結果がぶれる。** SmolVLA（flow-matching
  ベースのpolicy）は行動生成にサンプリングノイズが乗るため、環境の初期状態が
  同じでも実行するたびに挙動が変わりうる。数エピソードだけの結果を過信しない
  こと（詳細は`competition_analysis.md`の「SmolVLAベース重み、Track1
  exampleタスクでの試走結果」参照）。
- `--camera-size`はあくまで目視確認用。本番の採点は128×128固定で、
  `pipeline/config.py`の`EvalConfig.camera_height/width`が環境変数
  `LIBERO_EVAL_CAMERA`から決まる仕組みを利用している（このスクリプトも同じ
  仕組みで解像度を切り替えている）。
- 動画コーデックは`imageio`+`libx264`（H.264）。OpenCVの`cv2.VideoWriter`の
  既定コーデック`mp4v`（MPEG-4 Part 2）はブラウザの`<video>`タグで再生できない
  ため意図的に避けている。
