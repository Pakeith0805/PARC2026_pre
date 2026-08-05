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
`HF_HUB_DISABLE_SYMLINKS`という環境変数はhuggingface_hubの版によって効いたり
効かなかったりする（`lerobot==0.4.4`が引く`huggingface_hub==0.35.3`では既に
廃止されていて無視される）ため、これに頼らず、ダウンロード後に
`_materialize_symlinks()`でsymlinkを実ファイルへ手動で置き換えている。
併せて、コピー元として不要になった`blobs/`（実体の重複）と、ダウンロード時の
一時ログ`xet/`も削除してサイズを詰めている。
`zip -rq -X` → `validate_submission.py`の静的・動的チェック両方でPASSする
ことを確認済み（2026-08-04）。

`model_weights/`は`.gitignore`済み（約870MB、`submission_template/requirements.txt`
の`lerobot[smolvla]==0.4.4`本体とは別に、モデル重み自体もこのスクリプトで
再生成できるためgit管理しない）。提出zipを作るときは
`submission_template/`で以下を実行する
（[submission_template/README.md](../submission_template/README.md)参照）。
`submissions/`も`.gitignore`済み。

```bash
cd submission_template
zip -rq -X ../submissions/submission.zip \
    policy_server.py requirements.txt model_weights vendor \
    -x "*__pycache__*" "*.pyc"
```

`vendor/`（lerobot本体のソース）を忘れると、採点環境で`import lerobot`が
失敗して起動しない。提出したら[submission_log.md](../submission_log.md)に
1行追加すること。

### 既存キャッシュの上に作り直す場合

`MyPolicy`は`hf_cache/`が既にあると`HF_HUB_OFFLINE=1`を立てて同梱スナップショットを
直接読む（採点環境で確実にオフライン起動するため）。そのままでは再ダウンロードが
できないので、`download_model_weights.py`は`SMOLVLA_FORCE_ONLINE=1`を立てて
このオフライン化を明示的に無効化している。両経路が壊れていないことは2026-08-06に
実機確認済み:

- `SMOLVLA_FORCE_ONLINE=1` → `snapshot_download`を経由し、`HF_HUB_OFFLINE`は立たない
- 未設定 + `HF_HOME`/`HF_HUB_CACHE`を偽のパスに偽装 + `HF_HUB_OFFLINE=1`（＝本番と
  同じ敵対的条件）→ 同梱スナップショットから直接ロードして推論まで成功

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

**採点環境はPython 3.10.12。** ローカルの検証も同じ3.10系のvenvで行うこと
（詳細は[README.md](../README.md)の「採点環境」節参照。`lerobot>=0.5.0`は
`requires-python>=3.12`のためPython 3.10には入らず、`submission_template/
requirements.txt`は Python 3.10 で入る最新版 `lerobot[smolvla]==0.4.4` を
指定している。3.12のvenvで検証すると、この非互換に気づかないまま提出して
しまうので注意——実際に一度これで採点が失敗した）。

1. **ポリシーサーバー用の別venv**でモデルを動かす（GPU推奨）。

   このリポジトリでは`.local_libs/verify/venv_final_check/`（Python 3.10、
   `torch 2.10.0+cu128`）を使っている。2026-08-06時点でRTX 5090を認識し、
   モデルロード10.5秒・1推論0.31秒で動くことを確認済み。

   ```bash
   .local_libs/verify/venv_final_check/bin/python \
       submission_template/policy_server.py --port 8000
   ```

   新しく作り直す場合:

   ```bash
   uv venv --python 3.10 .venv_policy
   source .venv_policy/bin/activate
   uv pip install -r submission_template/requirements.txt
   python submission_template/policy_server.py --port 8000
   ```

   採点環境の提出物用venvは`--system-site-packages`付きで作られ、
   `requirements.txt`に書かなかったライブラリ（`torch`等）はプリインストール
   済みの版（`torch==2.11.0+cu130`等）がそのまま使われる。ローカルにはその
   プリインストールが無いので、上記のように`torch`を明示的に入れる必要がある
   （`lerobot[smolvla]==0.4.4`が`torch<2.11.0`を要求するため、pipが自動で
   適切な版を選ぶ。CUDA12系になるが、[README.md](../README.md)の「CUDA 12系の
   torchを使用する場合の注意」に記載の通り採点環境でも動作する想定）。

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

> **1つのポリシーサーバーに評価クライアントを同時に2つ以上つながないこと。**
> サーバー側のポリシーは単一インスタンスで、action chunkのキューと`/reset`が
> 混線し、成功率が実際より大幅に低く出る（実際に70%のところを15%/20%と
> 誤測定した。`competition_analysis.md`の「0点の真因」節参照）。

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

## eval_vanilla_libero.py

**摂動なしの素のLIBERO**（`LIBERO/`）で同じ評価を回す。`record_rollout.py`は
`env.sh`が指す`LIBERO-plus/`（摂動入り）を見るため、成功率が低いときに
「モデル自体が壊れているのか、摂動に弱いだけなのか」を切り分けられない。
このスクリプトは`LIBERO_ROOT`を素の`LIBERO/`に差し替えたうえで
`record_rollout.py`をそのまま起動する（引数は同じものが全部通る）。

```bash
source env.sh
venv/bin/python src/eval_vanilla_libero.py \
    --server-url http://localhost:8000 \
    --benchmark libero_object --episodes 1 --max-steps 300 --camera-size 128
```

素のLIBEROは`init_states`を`torch.load`で読むが、torch>=2.6の
`weights_only=True`既定に未対応で`UnpicklingError`になるため、このスクリプトが
ローカル検証用に既定を戻している（提出物には影響しない）。

**この切り分けが実際に効いた例**: `n_action_steps=50`のまま提出して0点だった
とき、素のLIBERO（libero_object 10タスク、128px）で

| 条件 | 成功率 |
|---|---|
| 128px / n=50 | 10% |
| 256px / n=50 | 30% |
| 128px / n=10 | **90%** |

という差が出て、原因が重みでも前処理でもなく開ループ長だと特定できた
（`my_strategy.md`方針8）。
