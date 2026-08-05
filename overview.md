# PARC2026 予選 — コンプリートノート

`competition_analysis.md`（競技理解・技術調査・Claudeの未採用仮説）と
`my_strategy.md`（自分が実際に決めた方針）を横断して、コンペと自分の方針に
関する情報を1ファイルに詰め込んだ統合ノート。新しい会話でまず読む用、あるいは
自分が全体像を素早く思い出す用。

**位置づけの注意**: 本体は2026-08-04時点のスナップショット。詳細な根拠・調査の
経緯は元の2ファイルにあり、そちらが一次情報。このファイルは自動同期していない
ので、元ファイルが更新されたら手動でこちらにも反映する必要がある。

## 2026-08-06の更新（本体未反映、要点のみ）

以下は2026-08-06に判明した重要事項で、このファイルの本体（08-04時点）には
まだ織り込んでいない。詳細は各リンク先を参照。

- **初めて採点が完走した**。3回目までは全て起動失敗。原因は`HF_HOME`の
  `setdefault`が採点環境の既設定に負けていたこと（`my_strategy.md`方針7）。
- **ただしスコアは0点だった。真因は`n_action_steps`の既定値50**。20Hz換算で
  2.5秒の開ループが、採点環境の128×128という低解像度と噛み合って破綻していた。
  **10に下げてローカルのT1 exampleで 0.0% → 70.0%**（`my_strategy.md`方針8、
  `competition_analysis.md`「0点の真因」節）。**未提出**。
- 提出物の再現性を確保した: `submission_template/vendor/`をgit追跡下に置き、
  提出履歴の台帳[submission_log.md](submission_log.md)を新設、
  切り分け用の[src/eval_vanilla_libero.py](src/eval_vanilla_libero.py)を常設化。
- 実装バグは無いことを検証済み（重み500キー完全一致、state 8次元一致、画像の
  向き・スケール整合）。次に効くのは推論時パラメータの調整とLoRA追加学習。

---

## 1. 競技の基本構造

- コンテスト課題名は「Vision-Language-Action（VLA）モデルが**駆使する汎化性能
  の3段階評価**」。Track1→2→3で1つのモデルの汎化能力を段階的に測る設計だと
  考えられる（強い推論だが、「Trackごとに別モデル禁止」と明文化した一文はまだ
  見つけていない）。
- **予選で評価されるのはTrack1のみ**（単一タスクベース、カメラ位置ズレ・
  ノイズへのロバスト性を評価）。
- 本選（6/19説明会情報、7/31正式ルールでは本選詳細は未記載につき要再確認）:
  仮想シミュレーター上でTrack1〜3すべてに挑戦。3ヶ月間、月次評価を経て上位
  50組に絞り込み。**ラウンドごとにTrackが追加されるのではなく、常にTrack1〜3
  合算で評価される**らしい。
  - Track2: 複数タスクの組み合わせ（複雑な一連のシーケンス）
  - Track3: 未知タスク・総合制御（完了率＋効率・安全性の総合評価）
- **参加者数の記述に食い違いあり（未解決）**: 6/19資料「予選開始500名選抜」
  vs 7/31正式ルール「予選上位200人を本選へ選出」。7/31の方が新しいが数字の
  食い違いは未確認のまま。Slackで最新情報を確認した方がよい。
- 対象ロボット: **Franka Emika Panda**（7-DOF垂直多関節アーム＋平行2指
  グリッパー、固定ベース）。カメラは2台（`agentview`固定俯瞰視点、
  `robot0_eye_in_hand`手首視点）。

## 2. 提出の仕組み

- 提出物は **HTTPポリシーサーバー一式のzip**。中身は
  `policy_server.py`（**`MyPolicy`クラスのみ編集可**、サーバー部分は変更不可）
  + `requirements.txt`（必須） + `model_weights/`（任意）。
- 3エンドポイント: `GET /health`、`POST /reset`（`instruction`, `seed`を
  JSONで受け取る）、`POST /act`（msgpackでobs→action）。
- **⚠️ `requirements.txt`に`git+https://…`や`--index-url`等の外部ソース指定は
  禁止。採点環境は外部通信を遮断する。** → これは`pip install`だけの制約ではなく
  「採点環境はネットワークに出られない」という一般的な事実の帰結だと考えられる
  （[第13節](#13-要対応要注意点まだ手を付けていないこと)に直結する重要な
  未対応課題あり）。
- 提出前チェック: `python validate_submission.py submission.zip`
  （zip健全性・サイズ上限・必須ファイル・エンドポイント・起動スモークテストまで）。
- ローカルでの評価実行: `python -m pipeline --server-url http://localhost:8000
  --track track1 --n-episodes 2 --max-steps 600`。zip一括評価は`evaluate.py`。

## 3. 観測・アクション仕様

`get_action(self, obs) -> action` の入出力（ソースコード読解で裏取り済み）。

**入力 `obs`（dict）**

| キー | shape | dtype | 単位・値域 |
|---|---|---|---|
| `agentview_image` | `(128,128,3)` | `uint8` | 0–255 |
| `robot0_eye_in_hand_image` | `(128,128,3)` | `uint8` | 0–255 |
| `robot0_joint_pos` | `(7,)` | float | ラジアン |
| `robot0_eef_pos` | `(3,)` | float | メートル、ワールド座標系 |
| `robot0_eef_quat` | `(4,)` | float | 無次元、**xyzw順** |
| `robot0_gripper_qpos` | `(2,)` | float | メートル、`[finger1∈[0,0.04], finger2∈[-0.04,0]]` |

言語指示は`obs`に含まれない。`reset(instruction="")`でエピソード開始時に
1回だけ渡される（`self.instruction`等に保持する必要あり）。

**出力 `action`**: `(7,)` `float32` = `[dx, dy, dz, droll, dpitch, dyaw, gripper]`

| 成分 | 内容 |
|---|---|
| `dx,dy,dz` | 正規化`[-1,1]`、内部でOSCコントローラが±0.05mの並進デルタにスケール |
| `droll,dpitch,dyaw` | 正規化`[-1,1]`、内部で±0.5radの回転デルタにスケール。**実体はroll/pitch/yawではなくaxis-angle表現`[ax,ay,az]`**（ドキュメントの命名がやや不正確） |
| `gripper` | 符号のみ意味を持つ。`-1=open`, `+1=close` |

NaN/Infを含まないこと、10秒以内に返すことが必須。

**成功判定**: タスクのゴール条件を満たし、かつ**衝突が発生していない**場合のみ
成功。衝突は「操作対象外の物体が初期位置からxyz変位の絶対値和で**1mm**を超えて
動いたか」で判定（対象外物体を動かしたら、後で元に戻しても失敗のまま）。

## 4. タイムアウト制約

| 対象 | 上限 | 超過時 |
|---|---|---|
| サーバー起動（モデルロード込み、評価につき1回） | 120秒 | 評価不能 |
| 推論 `/act`・`/reset`（毎リクエスト） | **10秒** | **1回でもそのTrack全体が0点** |

→ 推論10秒制約の方が圧倒的に重い。action chunkingでキャッシュされている
リクエストはこの制約の対象外（実質「チャンク1回分の推論 ≤ 10秒」）。

## 5. ハードウェア・サイズ制約

- **推論（本番）**: GPUコンテナ上（旧情報ではL4、24GB VRAM。最新の
  `README.md`「採点環境」節ではGPUモデル名は明記されていないが矛盾する情報も
  無いので維持——要再確認）、単一GPU、モデル並列不可。
- **提出zip**: 20GB以内（展開後・モデル単体にも上限あり、いずれも20GB級）。
- **学習（自分の手元）**: これは別枠。開発機`askr5090`の**RTX5090（31.4GB）**が
  使える。学習側のVRAM・速度に余裕があっても、提出物の推論側の制約（上記）は
  変わらない点に注意——「学習は贅沢に、推論は軽量に」が前提。
- **採点環境の正確な構成（2026-08-04、`README.md`「採点環境」節で判明）**:
  `nvidia/cuda:13.0.3-cudnn-devel-ubuntu22.04`、**Python 3.10.12**、
  **torch 2.11.0+cu130（プリインストール済み）**、`MUJOCO_GL=EGL`。提出物の
  依存は**`--system-site-packages`付きの専用venv**に`pip install -r
  requirements.txt`される。`requirements.txt`に書かなかったライブラリは
  プリインストール版がそのまま使われる。詳細は
  [competition_analysis.md](competition_analysis.md)の「採点環境の正確な仕様が
  判明」参照。

→ 結論: SmolVLA級（数億パラメータ）の軽量VLAが現実的な選択肢。OpenVLA-7B等の
数十億パラメータ級はfp16でも重みだけ約14GBとなり厳しい。ゼロからの学習は
ルール上も現実的にも非現実的（ルールで基盤モデル使用が前提、かつ予選期間
2.5週間・単一GPUでは規模が全く足りない）。現実的な路線は公開VLA基盤モデルへの
**LoRA等によるファインチューニング**（ルールの「独自学習要素が最終的な
Action生成に実質的に寄与する必要がある」という要件にも合致）。

## 6. Track1 exampleタスク（`compe/t1/`）

`compe/t1/T1_TASKS.csv`にある4タスク。**本番の採点タスクセットはこれとは別
（非公開）**、あくまで同じ形式・難易度帯の練習問題という位置づけ。

| # | task_id | 指示 | suite | 摂動カテゴリ | 難易度 |
|---|---|---|---|---|---|
| 1 | `pick_up_the_black_bowl_..._table_2` | 黒いボウルをキャビネット上段から皿に | libero_spatial | Background Textures | L3 |
| 2 | `pick_up_the_tomato_sauce_..._table_27` | トマトソースをバスケットに | libero_object | Background Textures | L5 |
| 3 | `pick_up_the_milk_..._light_15` | 牛乳をバスケットに | libero_object | Light Conditions | L2 |
| 4 | `put_the_bowl_on_the_stove_light_11` | ボウルをコンロに | libero_goal | Light Conditions | L4 |

各タスクに意図的なディストラクター（紛らわしい非対象物）あり。1タスクあたりの
既定試行回数は配布キットで20エピソード（コード上のデフォルト）だが、**本番の
実際の試行数・タスク数は非公開**。

## 7. 私が実際に決めたこと（`my_strategy.md`より）

1. **単一モデルでTrack1〜3すべてに対応する。** 課題名の「汎化性能の3段階評価」
   という設計思想に沿う。予選対応で終わらせず、instructionの多様性・タスク
   構成の広さを早めに意識したデータ設計をする含意あり。
2. **Track1 exampleのタスク2（tomato_sauce, L5）を学習データからholdoutし、
   汎化性能の検証専用に使う。** `libero_object`はタスク2・3の2つあるので片方を
   保留すれば「同じ構造は学習済みだが対象物体・難易度は未見」という汎化テスト
   になる。留保: 4タスクしかないため3タスクでの学習は本番の学習データ設計とは
   切り離して考える必要あり。
3. **ベースモデルに`lerobot/smolvla_libero_plus`（SmolVLA）を採用し、まず
   追加学習なしで動作確認する。** `examples/`のLoRA学習notebookもこのモデル
   前提。前処理・後処理は自前実装せず`lerobot`の`make_pre_post_processors`で
   チェックポイント同梱の設定をそのまま使う方針（自前実装は事故りやすいため）。
   `SMOLVLA_MODEL_PATH`環境変数でモデル参照先を切り替えられる実装にし、LoRA
   学習後は同じコードでマージ済みモデルに差し替え可能。
4. **`lerobot`パッケージをpipインストールせず、ソースをvendor同梱する。**
   無条件必須依存の`pynput`→`evdev`が採点環境でビルド失敗するため（詳細は
   第10節）。`submission_template/vendor/lerobot/`にソース一式を同梱し、
   `policy_server.py`が`sys.path`に追加して使う。

## 8. 実装状況（`submission_template/policy_server.py`）

`MyPolicy`をSmolVLAベースの推論実装に置き換え済み。要点:

- 画像: `agentview_image`→`observation.images.front`、
  `robot0_eye_in_hand_image`→`observation.images.wrist`。**学習データと向きを
  揃えるため180度回転（`[::-1, ::-1, :]`）が必須**（見落としやすい）。
- 状態: `observation.state`は**8次元** `[eef_pos(3), eef_quatをaxis-angleに
  変換した3値, gripper_qpos(2)]`（`config.json`の`shape:[6]`という記載は古い
  メタデータで誤り、正規化統計・学習データセットは共に8次元）。
- 画像解像度: 前処理内部が任意サイズを512×512へパディングリサイズするので、
  本番128×128でも学習時256×256との解像度差を気にする必要はなかった。
- action chunking: `SmolVLAPolicy`が`chunk_size=50`で内部キュー管理。
  `reset()`で`self.policy.reset()`を呼べばクリアされる。自前実装不要。
- 起動高速化: `config.load_vlm_weights = False`でVLM初期重みの二重ダウンロード
  を回避（120秒起動制約対策）。
- `lerobot`本体はpipインストールせず`submission_template/vendor/lerobot/`に
  ソース同梱（**採点環境がPython 3.10.12のためlerobot>=0.5.0が入らない**上、
  Python 3.10で入る0.4.4も無条件必須依存`pynput`→`evdev`がビルド失敗する
  ため。詳細は第9節・第10節参照）。`requirements.txt`にはvendorした
  lerobotソースが実際に必要とする個別の依存
  （`torchvision`, `transformers`, `accelerate`, `datasets`等）を明記。
  `torch`/`numpy`/`huggingface_hub`等は明示せず、採点環境のプリインストール版
  （`--system-site-packages`経由）に任せる方針（torchのみtorchvisionの
  要求で自動的にCUDA12系へ巻き戻る）。
- **オフライン起動対応**: `src/download_model_weights.py`で
  `submission_template/model_weights/hf_cache/`にモデル一式（symlinkなし形式）
  を事前ダウンロード。あれば`HF_HUB_OFFLINE=1`で完全オフライン起動する
  （詳細は[第13節](#13-要対応要注意点まだ手を付けていないこと)）。
- 動画付きローカル評価ツール `src/record_rollout.py`（使い方は`src/README.md`）
  を追加。`pipeline/rollout.py`と同じ成功判定ロジックを踏襲しつつ動画も残す。
  `pipeline/`本体・`submission_template/`本体は無改変。

## 9. 重大インシデント: 採点環境でlerobot==0.6.0が入らず0点（2026-08-04）

実際に採点環境へ提出したところ、依存インストールの段階で失敗し0点になった。

```
ERROR: Could not find a version that satisfies the requirement lerobot==0.6.0
  (from versions: 0.1.0, 0.3.2, 0.3.3, 0.4.0, 0.4.1, 0.4.2, 0.4.3, 0.4.4)
```

- **原因**: PyPIの`lerobot`は`0.5.0`以降すべて`requires-python>=3.12`だが、
  採点環境はPython 3.10.12（[第5節](#5-ハードウェアサイズ制約)参照）。
  examples/notebookも自分のローカル検証（`.local_libs/verify/venv_smolvla/`）
  もPython 3.12で行っていたため、この版のズレに気づけなかった。
- **対応**: Python 3.10で入る最新版`lerobot[smolvla]==0.4.4`に切り替え。
  0.4.4にも同じSmolVLA実装・processor pipelineが既にあり、チェックポイントの
  `config.json`もそのまま読める。`from lerobot.configs import
  PreTrainedConfig`は0.6.0のみ通る書き方だったため、両バージョンで動く
  `from lerobot.configs.policies import PreTrainedConfig`に修正した。
  Python 3.10の別venv（`.local_libs/verify/venv_py310_check/`）で
  チェックポイントのロード・推論・`validate_submission.py`の静的/動的
  チェックまで実際に通ることを確認済み。
- **教訓**: 学習用ノートブック（Colab、Python 3.12）と推論コード
  （採点環境、Python 3.10）の前提Python版が違うことに、ローカル検証だけでは
  気づけなかった。今後はPython 3.10のvenvで最終確認してから提出する
  （詳細・requirements.txtの書き方は[my_strategy.md](my_strategy.md)方針5、
  [competition_analysis.md](competition_analysis.md)の該当節参照）。
- **修正後、ベース重み（LoRA未実施）での提出zipを再作成・再検証済み
  （2026-08-04）**: `submissions/submission_smolvla_base_2026-08-04.zip`
  （約686MB、`.gitignore`済み）。作成中にもう1つ罠があった:
  `HF_HUB_DISABLE_SYMLINKS`環境変数は`lerobot==0.4.4`が引く
  `huggingface_hub==0.35.3`では既に廃止されていて効かず、symlinkが復活していた。
  `src/download_model_weights.py`にダウンロード後の後処理
  （`_materialize_symlinks()`でsymlinkを実ファイルへ置換、不要になった
  `blobs/`と一時ログ`xet/`を削除）を追加して解決。この状態で
  `validate_submission.py`の静的・動的チェック両方PASS（errors=0）を確認済み。

## 10. 重大インシデント2: evdevビルド失敗とlerobotのvendor化（2026-08-04）

lerobot 0.4.4に切り替えて再提出したが、依存インストール段階で別のエラーが
出て再度0点になった。

```
× Building wheel for evdev (pyproject.toml) did not run successfully.
src/evdev/input.c:10:10: fatal error: Python.h: No such file or directory
```

- **原因**: `evdev`（Linux入力デバイス用、C拡張が必要）はPyPIに一度も
  wheelを公開しておらず常にソースビルドが必要。採点環境にはPythonヘッダーが
  無くビルドが失敗する。`evdev`は`pynput`（lerobotが無条件必須依存として
  宣言、smolvla extraとは無関係）が要求しており、lerobotのバージョンを
  0.3.x〜0.4.4のどれに変えても同じ依存宣言があるため回避不可（実際に各
  バージョンのPyPIメタデータを確認した）。
- **pynput/evdevはSmolVLA推論に一切使われていない**ことを、削除した状態で
  importチェーンが正常に動くことを実機確認して裏取りした（ゲームパッド等の
  実機テレオペ機能向けの依存）。
- **requirements.txt側での回避は構造的に不可能**: ローカル`.whl`参照・
  `file://`参照・`--find-links`はいずれも`validate_submission.py`の静的検査
  で明示的に拒否される（`req.local_path`/`req.external_url`/
  `BANNED_REQ_OPTIONS`、「setup.pyがinstall時に実行される」ためのセキュリティ
  対策）。
- **対応（`my_strategy.md`方針6参照）**: `lerobot`パッケージをpipインストール
  するのをやめ、ソース一式を`submission_template/vendor/lerobot/`に同梱し、
  `policy_server.py`が`sys.path`に追加して使う方式にした。vendorしたソースが
  実際に必要とする依存（`lerobot.policies.__init__`が全ポリシー種別を無条件
  importする作りのため、`groot`経由で`robots`/`motors`/`pyserial`まで
  芋づる式に読み込まれる等）を、クリーンなPython 3.10環境で1つずつ
  importエラーを解消しながら特定した。幸いこれらは全てPyPIにwheelがあり、
  evdevのような問題は再発しなかった。
- **検証**: 採点環境のプリインストール状態を模した環境で、素の
  `pip install -r requirements.txt`が警告・エラーなしで完了し`evdev`/
  `pynput`が一切入らないこと、モデルのロード・推論、
  `validate_submission.py`の静的・動的チェック（zip展開込み）が全てPASS
  することを確認した。

## 11. 動作確認結果（2026-08-02、`askr5090`にて）

- **GPU環境**: `nvidia-smi`は`Driver/library version mismatch`で動かないが、
  `libcuda.so`直叩きでCUDA計算自体は正常と確認（RTX5090、31.4GB）。壊れているのは
  モニタリングだけ。
- **SmolVLA単体の動作確認**: 起動51.7秒（<120秒）、推論は通常0.001秒・
  chunk再計算時でも最大0.33秒（<10秒）。出力shape/dtype/NaN全て正常。
  `policy_server.py`側の修正は不要で一発で通った。
- **Track1 example 4タスクでの試走（追加学習なしのベース重み）**: task平均
  成功率**3.1%**（black_bowl 0/3, tomato_sauce 0/3, milk 0/3, stove 1/8）。
  低いのは想定内（LoRA未実施）。
- **同一タスク・同一初期状態でも試行ごとに結果がぶれることを繰り返し確認**:
  `stove`タスクだけで3/3成功した回・0/3だった回・1/5だった回があった。
  `SmolVLAPolicy`のflow-matchingサンプリングにノイズが乗るため
  （`noise`引数固定なし）。**今後LoRA後のモデルを比較する際は試行回数を
  増やさないと結論を誤りやすい。**
- **動画コーデックの罠**: `cv2.VideoWriter`既定の`mp4v`はブラウザ`<video>`で
  再生不可。`imageio`+`imageio-ffmpeg`（`libx264`, `yuv420p`）で解決。

## 12. 会話内で出た未採用の戦略仮説（Claude発、まだ決定していない）

- **学習時の分布拡張アプローチ**: Track3（未知タスク）対策として、個々のタスクを
  覚えさせるのではなく「タスクの構成要素（物体・動作・指示表現）の組み合わせ方への
  頑健性」を自作の多様なタスクバリエーションで鍛える発想。Track1→カメラ視点
  ジッタ等のdomain randomization、Track2→複数ステップ連結instructionの自作、
  Track3→物体組み合わせ・言い回しのバリエーション拡大、という対応付け。
  競技資料に明記された話ではなく未検証。
- **RTX5090が使えることで、`freeze_vision_encoder=true`（examples/notebookの
  既定）を外す選択肢が現実的になった**という指摘。Track1の評価軸が背景
  テクスチャ・照明条件への頑健性なので、視覚エンコーダを凍結したままだと
  そこに直接対応できない可能性がある。まだ採用は決めていない。

## 13. ⚠️ 要対応・要注意点（まだ手を付けていないこと）

- **【対応済み・2026-08-02】オフライン制約への対応**: [README.md](README.md)に
  「採点環境は外部通信を遮断する」と明記されており、`MyPolicy`がデフォルトで
  Hugging Face Hubからモデルを取得する実装のままでは本番で起動に失敗する疑いが
  あった。`src/download_model_weights.py`で`MyPolicy`を実際に一度ネットワーク
  ありで動かし、触れたファイル一式を`submission_template/model_weights/hf_cache/`
  にHFキャッシュとして保存する方式にし、`policy_server.py`側もこのディレクトリの
  有無で`HF_HUB_OFFLINE=1`に自動切替するよう変更した。symlinkが
  `validate_submission.py`の`zip.slip_symlink`チェックに引っかかる罠があったが
  `HF_HUB_DISABLE_SYMLINKS=1`で回避。zip化した上で`validate_submission.py`の
  静的・動的チェック両方PASS（errors=0）を確認済み（約686MB、20GB制限に十分
  収まる）。詳細は[my_strategy.md](my_strategy.md)の方針4、
  [src/README.md](src/README.md)参照。**今はベース重み（LoRA未実施）を
  同梱している状態。LoRAでマージ済みモデルができたら同梱し直す必要あり。**
- LoRAの具体的な学習設定（rank、`freeze_vision_encoder`を外すか、steps数、
  学習データの範囲）はまだ何も決めていない。
- タスク2holdoutで学習データが実質3タスクだけになる量的不足リスク（方針2の
  留保事項、本番学習データ設計では別途データを増やす必要がある）。
- 予選/本選の参加者数の食い違い（500名 vs 200名）、本選のTrack構成の正式資料
  未確認（6/19説明会情報のみ）。Slack等での最新確認が必要。

## 14. ファイルマップ

| パス | 役割 |
|---|---|
| [competition_analysis.md](competition_analysis.md) | 技術調査・未採用仮説の詳細（このファイルの一次情報） |
| [my_strategy.md](my_strategy.md) | 確定した意思決定の詳細（このファイルの一次情報） |
| [submission_template/policy_server.py](submission_template/policy_server.py) | 提出物本体（`MyPolicy`にSmolVLA実装済み） |
| [submission_template/vendor/lerobot/](submission_template/vendor/lerobot/) | pipインストールしない`lerobot`本体のvendorソース（evdevビルド回避、第10節参照） |
| [submissions/](submissions/) | 提出用に作ったzip一式（`.gitignore`済み） |
| [src/record_rollout.py](src/record_rollout.py), [src/README.md](src/README.md) | 動画付きローカル評価ツール |
| [src/download_model_weights.py](src/download_model_weights.py) | モデル重みをオフライン用に事前ダウンロード（`submission_template/model_weights/`、`.gitignore`済み） |
| [examples/smolvla_libero_spatial_lora.ipynb](examples/smolvla_libero_spatial_lora.ipynb) | SmolVLA LoRA学習notebook（Colab想定） |
| [compe/t1/T1_TASKS.csv](compe/t1/T1_TASKS.csv) | Track1 exampleタスク一覧 |
| `.local_libs/verify/` | 動作確認用の使い捨てスクリプト・専用venv・ログ（`.gitignore`済み） |

---
最終更新: 2026-08-04
