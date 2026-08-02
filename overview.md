# PARC2026 予選 — コンプリートノート

`competition_analysis.md`（競技理解・技術調査・Claudeの未採用仮説）と
`my_strategy.md`（自分が実際に決めた方針）を横断して、コンペと自分の方針に
関する情報を1ファイルに詰め込んだ統合ノート。新しい会話でまず読む用、あるいは
自分が全体像を素早く思い出す用。

**位置づけの注意**: これは2026-08-02時点のスナップショット。詳細な根拠・調査の
経緯は元の2ファイルにあり、そちらが一次情報。このファイルは自動同期していない
ので、元ファイルが更新されたら手動でこちらにも反映する必要がある。

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
  （[第11節](#11-要対応要注意点まだ手を付けていないこと)に直結する重要な
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

- **推論（本番）**: L4（24GB VRAM）、単一GPU、モデル並列不可。
- **提出zip**: 20GB以内（展開後・モデル単体にも上限あり、いずれも20GB級）。
- **学習（自分の手元）**: これは別枠。開発機`askr5090`の**RTX5090（31.4GB）**が
  使える。学習側のVRAM・速度に余裕があっても、提出物の推論側の制約（上記）は
  変わらない点に注意——「学習は贅沢に、推論は軽量に」が前提。

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
- `requirements.txt`に`torch>=2.7`, `lerobot[smolvla]==0.6.0`,
  `huggingface_hub>=0.25`を追加済み。
- **オフライン起動対応**: `src/download_model_weights.py`で
  `submission_template/model_weights/hf_cache/`にモデル一式（symlinkなし形式）
  を事前ダウンロード。あれば`HF_HUB_OFFLINE=1`で完全オフライン起動する
  （詳細は[第11節](#11-要対応要注意点まだ手を付けていないこと)）。
- 動画付きローカル評価ツール `src/record_rollout.py`（使い方は`src/README.md`）
  を追加。`pipeline/rollout.py`と同じ成功判定ロジックを踏襲しつつ動画も残す。
  `pipeline/`本体・`submission_template/`本体は無改変。

## 9. 動作確認結果（2026-08-02、`askr5090`にて）

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

## 10. 会話内で出た未採用の戦略仮説（Claude発、まだ決定していない）

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

## 11. ⚠️ 要対応・要注意点（まだ手を付けていないこと）

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

## 12. ファイルマップ

| パス | 役割 |
|---|---|
| [competition_analysis.md](competition_analysis.md) | 技術調査・未採用仮説の詳細（このファイルの一次情報） |
| [my_strategy.md](my_strategy.md) | 確定した意思決定の詳細（このファイルの一次情報） |
| [submission_template/policy_server.py](submission_template/policy_server.py) | 提出物本体（`MyPolicy`にSmolVLA実装済み） |
| [src/record_rollout.py](src/record_rollout.py), [src/README.md](src/README.md) | 動画付きローカル評価ツール |
| [src/download_model_weights.py](src/download_model_weights.py) | モデル重みをオフライン用に事前ダウンロード（`submission_template/model_weights/`、`.gitignore`済み） |
| [examples/smolvla_libero_spatial_lora.ipynb](examples/smolvla_libero_spatial_lora.ipynb) | SmolVLA LoRA学習notebook（Colab想定） |
| [compe/t1/T1_TASKS.csv](compe/t1/T1_TASKS.csv) | Track1 exampleタスク一覧 |
| `.local_libs/verify/` | 動作確認用の使い捨てスクリプト・専用venv・ログ（`.gitignore`済み） |

---
最終更新: 2026-08-02
