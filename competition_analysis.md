# コンペ分析ノート（対話ベース）

このファイルは、配布資料を読むだけでは分からない、Claudeとの対話の中で明らかになった
理解・解釈・推論をまとめたものである。資料の引き写しではなく、「資料の記述をどう解釈す
べきか」「実務上どう動くべきか」を中心に記述する。

今後の対話で新たに分かったことがあれば、該当セクションに追記するか、新規セクションを
追加していく。

---

## 編集対象・実装の要点

- 編集してよいのは `submission_template/policy_server.py` の `MyPolicy` クラスのみ。
  サーバー部・シリアライゼーション部は変更不可。
- `__init__`: サーバー起動時に1回だけ呼ばれる。モデルロードはここで行う。
  `get_action` の中で毎回ロードするような実装にすると10秒制約に確実に間に合わない。
- `get_action(obs) -> action`: 提出物の実質的な心臓部。
- `reset(instruction)`: エピソードごとに呼ばれる。action chunkingのキャッシュ等の
  内部状態はここでクリアする設計にする。

## 入出力仕様（対話で確認した要点）

`get_action(self, obs)` の入出力。単位・値域・成分順は、`policy_server.py`や
READMEには明記がなかったため、`LIBERO-plus/libero/libero/envs/`と
`venv/.../robosuite`のソースを実際に読んで裏取りした（2026-08-02）。

**入力 `obs`（dict）**

| キー | shape | dtype | 単位・値域 | 備考 |
|---|---|---|---|---|
| `agentview_image` | `(128, 128, 3)` | `uint8` | 0–255 | 128×128はネイティブ描画解像度で、別途リサイズする処理はコード上見当たらない（`pipeline/environment.py`の`camera_heights/widths`がそのままrobosuiteのレンダラに渡る） |
| `robot0_eye_in_hand_image` | `(128, 128, 3)` | `uint8` | 0–255 | 同上 |
| `robot0_joint_pos` | `(7,)` | `float` | **ラジアン** | Pandaの関節可動域そのもの（例: `±2.8973 rad`）。robosuiteの`robot.py`の`qpos`センサをそのまま使用 |
| `robot0_eef_pos` | `(3,)` | `float` | **メートル、ワールド座標系** | MuJoCoの`site_xpos`をそのまま使用。ロボット基準座標ではない点に注意 |
| `robot0_eef_quat` | `(4,)` | `float` | 無次元、**xyzw順** | MuJoCoネイティブは`wxyz`だが、robosuiteの`convert_quat()`が明示的に`xyzw`へ変換してから渡している |
| `robot0_gripper_qpos` | `(2,)` | `float` | **メートル**、`[finger1∈[0,0.04], finger2∈[-0.04,0]]` | 順序は`[finger1, finger2]`。開≈`[0.04,-0.04]`、閉≈`[0,0]`、デフォルトreset値は`[0.0208,-0.0208]`（半開） |

言語指示は `obs` に含まれない。`reset(self, instruction: str = "")` でエピソード
開始時に1回だけ渡される（毎ステップではないので `self.instruction` 等に保持する
必要がある）。

**出力 `action`**

| shape | dtype | 内容 |
|---|---|---|
| `(7,)` | `float32` | `[dx, dy, dz, droll, dpitch, dyaw, gripper]` |

| 成分 | 単位・値域 | 備考 |
|---|---|---|
| `dx, dy, dz` | 入力は正規化 `[-1, 1]`、内部でロボットのOSCコントローラ（robosuite `OSC_POSE`のデフォルト設定）が**±0.05m**の並進デルタにスケール | パイプライン側（`pipeline/rollout.py`）はクリップ・スケーリングをせず出力をそのまま`env.step()`に渡す |
| `droll, dpitch, dyaw` | 入力は正規化 `[-1, 1]`、内部で**±0.5rad**の回転デルタにスケール | **名前に反し、実体は独立したroll/pitch/yawではなくaxis-angle表現の回転デルタ`[ax, ay, az]`**（robosuiteの`OSC`コントローラの仕様）。ドキュメントの命名がやや不正確という発見 |
| `gripper` | 値の大きさは無視され**符号のみ**が意味を持つ。`-1 = open`、`+1 = close` | `panda_gripper.py`の`format_action()`docstringに明記 |

正規化`[-1,1]`が前提であることは、テンプレートのランダムポリシーが
`np.random.uniform(-1, 1, size=7)`を返している点（`submission_template/policy_server.py`）
とも整合する。制約として、NaN/Infを含まないこと、1回の呼び出しは10秒以内に
返すことが必須。

**未確認のまま残った点**: `agentview_image`にはBDDLファイル名のパターン
（`_noise_`等）で有効化されるノイズ付加（motion blur等）のオプション経路が
コード上存在するが、`compe/t1/`の標準トラックで実際に使われているかは未確認。

## 対象ロボット: Franka Emika Panda

- 予選ルール文書に「評価環境（LIBERO Plus / ロボットはFranka Emika Panda）」と
  明記されている。7自由度（7-DOF）の垂直多関節アーム＋平行2指グリッパー
  （Panda Hand）、固定ベース。
- 上記の入出力仕様調査で、`robosuite/models/assets/robots/panda/robot.xml`の
  関節可動域や`panda_gripper.xml`のfinger joint構成が、実際に`robot0_joint_pos
  (7,)`・`robot0_gripper_qpos (2,)`と一致することを確認済み。
- カメラは2台: `agentview`（外部固定俯瞰視点）＋`robot0_eye_in_hand`（手首装着の
  アイ・イン・ハンド視点）。
- 実機のFranka Emika Panda（独Franka Emika社、現Franka Robotics）はロボット
  学習研究で広く使われる協働ロボットアームで、可搬重量約3kg・リーチ約855mm・
  7軸冗長構成（一般知識、リポジトリでは未検証）。LIBEROやRoboMimicなど多くの
  模倣学習ベンチマークでも標準機体として使われている。

### カメラ画像のサンプル

- `LIBERO-plus/static/images/main_img.png` と `libero-plus.jpg` に、LIBERO-plus
  ベンチマーク公式のプロジェクトページ掲載図（俯瞰視点の例＋各種摂動バリエーション）
  がある。ただしこれは**LIBERO-plus一般の例示画像**であり、このコンペ独自の
  タスクセット（`compe/t1/`）の実レンダリングそのものではない（同一シミュレータ・
  アセットなので雰囲気はほぼ同等）。
- 画像内の「Camera（第三者視点の角度違い）」「Noise（センサーノイズ）」パネルは、
  Track1の評価軸（カメラ位置のズレ・ノイズへのロバスト性）と直接対応しており、
  評価でどんな摂動が想定されているかのイメージを掴むのに役立つ。
- 評価パイプライン自体（`pipeline/rollout.py`等）には画像を保存する処理がない
  （grep調査で確認）。このリポジトリの実タスクで生の`agentview_image`を見るには、
  `LIBERO/benchmark_scripts/render_single_task.py`を流用するか、`get_action`内に
  一時的な保存処理を自分で追加する必要がある。

### 実際に評価を走らせてサンプル画像を採取した記録（2026-08-02）

`MyPolicy.get_action`に一時的な画像保存コードを仕込み、`compe/t1/`の実タスク
（例: `pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_...`）で
実際に評価を走らせ、`agentview_image`/`robot0_eye_in_hand_image`を取得できた
（作業後にコードは元に戻し、`policy_server.py`はリポジトリと差分なしの状態に
戻している）。

- 見た目: 木目調キャビネットの引き出し・黒いボウル・グリッパー・調味料ボトル
  などが確認でき、色情報も正しく載っていた（完全なグレースケールではない）。
  LIBERO-plusの例示画像（前項）と同系統の見た目。
- **このサンドボックス環境固有の注意点**: `env.sh`が既定で設定する
  `MUJOCO_GL=egl`は、このセッションでは`Cannot initialize a EGL device
  display`で失敗した（`nvidia-smi`も`Driver/library version mismatch`を返す
  状態で、GPU/ドライバがこのセッションから正常に見えていない）。
  setup.sh実行時（7/31）はEGLが動作確認OKだったとログに残っており、環境が
  セッションをまたいで変化した可能性がある。
  - 対処: `MUJOCO_GL=osmesa`（ソフトウェアレンダリング）に切り替えることで
    描画に成功した。ただし`.local_libs`に`libosmesa6`のネイティブライブラリ
    (`libOSMesa.so.*`) が展開されている必要がある。setup.sh自身もEGL失敗時は
    自動でこのosmesaフォールバック取得を行うロジックを持っている
    （`setup.sh`の`fetch_debs libosmesa6`）が、今回はEGLが「一見動く」判定を
    経てすり抜けたため未展開だった。手動で
    `dpkg-deb -x libosmesa6_*.deb .local_libs` すれば復旧できる。
  - 今後このサンドボックスで評価を回す際、EGLが失敗するようならまずこの
    osmesaフォールバックを疑うとよい。

### 画像解像度は128×128固定ではない（レンダラー側の上限ではない）

`LIBERO_EVAL_CAMERA=256` を環境変数で渡して同じタスクを実際に走らせたところ、
`(256, 256, 3)`のagentview画像が問題なく取得できた（`pipeline/config.py`の
`camera_height`/`camera_width`のデフォルトが128なだけで、レンダラー
（MuJoCo/robosuite）自体に解像度の上限があるわけではない）。

- **ただし本番の採点では128×128固定。** `policy_server.py`の`BasePolicy`
  docstringに`(128, 128, 3)`と明記された提出仕様であり、ここは変更できない。
- **要注意の落とし穴**: [examples/README.md](examples/README.md)のSmolVLA LoRA
  学習notebookは256×256で学習する設計になっている。学習解像度(256)と本番推論
  解像度(128)が異なるため、`get_action()`内でモデルが実際に学習した解像度に
  合わせて画像をリサイズする前処理が必要になる可能性が高い。見落としやすい点
  として記録しておく。

### exampleタスクの具体的な中身（BDDLファイルを読んで確認）

サンプル画像・動画に使った`pick_up_the_black_bowl_in_the_top_drawer_of_the_
wooden_cabinet_and_place_it_on_the_plate_table_2`タスクの定義（`LIBERO-plus/
libero/libero/bddl_files/libero_spatial/`配下の`.bddl`ファイル）を実際に
読んで中身を確認した。

**位置づけの整理（対話で確認）**: `compe/t1/`は文字通りTrack1の実装であり、
`--track track1`で動くのはこのタスク群そのもの。つまりこのタスクは
「Track1の中身」であると同時に「exampleタスク」でもあり、両立する。矛盾する
表現ではない。ただし、ここにある4タスクは**本番の予選採点で使われる
タスクセットそのものではない**点は変わらない（README:
「同梱されているのは公開されている example タスクのみ。本番の採点は公開
されていないタスクを含む別のタスクセットで実施される」）。位置づけとしては
「本番と同じ形式・同じ難易度帯の練習問題」に近い。

- `compe/t1/T1_TASKS.csv`にタスク一覧があり、各行は
  `task_id, instruction, libero_plus_id, suite, category, difficulty_level`
  の列を持つ。予選exampleは4タスクのみ（`libero_spatial`/`libero_object`/
  `libero_goal`から各1〜2、難易度L2〜L5混在）。
- **タスク種類数とは別に、1タスクあたりの試行回数（エピソード数）も複数**。
  `pipeline/cli.py:56`で`--n-episodes`のデフォルトは**20**（コード上で確認）。
  1タスクにつき20エピソード試行し成功率等を平均する設計。ただし本番評価での
  実際の試行数は非公開（[examples/README.md](examples/README.md)の比較表にも
  同様の記載あり）。評価は「複数タスク × タスクあたり複数エピソード」の2軸
  構成で、両方とも本番の正確な数字は非公開という点に注意。
- 上記タスクの`.bddl`のゴール条件は `(On akita_black_bowl_1 plate_1)` の
  1行のみ＝「黒いボウルを皿の上に置けたら成功」という単純なpick&placeタスク。
- シーンには**ディストラクター（紛らわしい非対象物）が意図的に配置されている**
  ことが`:objects`/`:init`から読み取れる: もう1つの見た目が同じ黒いボウル
  (`akita_black_bowl_2`)、クッキー、ラメキン皿など。`:obj_of_interest`に
  含まれない物体に触れると、[README記載の衝突判定](README.md#成功判定)で
  失敗になる。
- **タスク名と実装内容にズレがある**: タスク名は「top **drawer**（引き出し）」
  だが、BDDL上は`wooden_cabinet_1_top_region`という開いた棚のような領域
  （`Open wooden_cabinet_1_top_region`初期状態）として扱われており、実際に
  引き出しを開閉する操作は要求されていない。タスク名の言葉通りに実装を
  想像すると誤解する可能性がある点として記録しておく。

### Track1 exampleタスク4種、全件の内容（BDDL全件を読んで確認）

| # | task_id | 指示 | suite | 摂動カテゴリ | 難易度 | ゴール条件 | 主なディストラクター |
|---|---|---|---|---|---|---|---|
| 1 | `pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate_table_2` | 黒いボウルをキャビネット上段から取って皿に置く | libero_spatial | Background Textures | L3 | `On akita_black_bowl_1 plate_1` | 黒いボウル×1、クッキー、ラメキン皿 |
| 2 | `pick_up_the_tomato_sauce_and_place_it_in_the_basket_table_27` | トマトソースをバスケットに入れる | libero_object | Background Textures | L5 | `In tomato_sauce_1 basket_1_contain_region` | 牛乳・バター・オレンジジュース・チョコプディング・BBQソース（計5個） |
| 3 | `pick_up_the_milk_and_place_it_in_the_basket_light_15` | 牛乳をバスケットに入れる | libero_object | Light Conditions | L2 | `In milk_1 basket_1_contain_region` | クリームチーズ・トマトソース・バター・オレンジジュース・チョコプディング（計5個） |
| 4 | `put_the_bowl_on_the_stove_light_11` | ボウルをコンロに置く | libero_goal | Light Conditions | L4 | `On akita_black_bowl_1 flat_stove_1_cook_region` | クリームチーズ・ワインボトル・皿 |

- suiteは3種類（LIBERO本家のスイート構成を踏襲）: `libero_spatial`（位置関係を
  問う）、`libero_object`（対象物体の識別を問う）、`libero_goal`（ゴール状態を
  問う）。
- 摂動カテゴリ（Background Textures / Light Conditions）と難易度
  （L2〜L5）は別軸らしい。ディストラクター数（タスク2,3はどちらも5個）と
  難易度が単純比例していない（タスク2はL5、タスク3はL2）ことから、難易度の
  主因はディストラクター数だけでなく摂動側（背景/照明）の強さにもありそうだが、
  これは推測であり未検証。

## 2つのタイムアウト制約、どちらが重いか

- サーバー起動（モデルロード込み）: 120秒、**評価につき1回だけ**発生。
- 推論（`/act`, `/reset`）: 10秒、**全エピソード・全ステップで毎回**発生し、
  1回でも超過するとそのTrack全体が0点になる。
- → 推論10秒制約の方が圧倒的に重い。起動時間はよほど巨大なモデルでない限り
  心配不要で、優先して詰めるべきは推論速度の最適化（action chunking、精度削減等）。

## ベースモデル選定にかかる制約（対話で導いた推論）

タイムアウト・ハードウェア制約の組み合わせから、選べるベースモデルの規模が
事実上絞られる。

1. VRAM 24GB（L4）に載ること — 数十億パラメータ級（OpenVLA-7B等）はfp16でも
   重みだけで約14GBとなり、活性化・KVキャッシュの余地が厳しくなる。
2. 提出zip 20GB以内 — 大型モデルほど圧迫される（fp32の7B級で約28GBとなり単体で
   超過するケースもある）。
3. L4は推論特化の中位GPUで演算性能に上限がある — モデルが大きいほど1推論あたりの
   レイテンシが伸び、10秒制約に抵触しやすい。
4. 単一GPU、モデル並列不可。

→ 結論: SmolVLA級（数億パラメータ）の軽量VLAが現実的な選択肢。大規模VLAを使う
場合は量子化・蒸留などの追加の工夫がほぼ必須になる。

**学習ハードウェアと推論ハードウェアは別物**（2026-08-02追記）: 上記1〜4は
あくまで**提出後・本番の推論**（L4、単一GPU、10秒/120秒制約、20GB zip）の話。
学習（LoRA等）は自分の手元の計算資源で行うため制約が別で、開発機`askr5090`の
RTX5090（31.4GB、このファイルの「GPU環境の状態」節参照）が使える。学習側の
VRAM・速度に余裕があっても、提出物の推論側の制約（上記）は変わらない点に注意。

## ゼロからの学習について

- ルール上「ロボット基盤モデルを使用してください」と明記されており、公開基盤モデルを
  ベースにすることが前提。ゼロから学習するルートはそもそも想定されていない。
- 仮にルール上OKだったとしても、予選期間（2.5週間程度）ではVLAのゼロからの学習は
  非現実的（通常は大規模データ・大規模GPUクラスタで数日〜数週間かかる）。手元に
  RTX5090が使えるとはいえ単一GPUであり、大規模事前学習の規模には遠く及ばない。
- 現実的な路線は、公開VLA基盤モデルへのLoRA等によるファインチューニング。

## LoRAについて（このコンペでの位置づけ）

- 元の重み `W` を凍結し、低ランク行列 `A`, `B` のみを学習し、`W + A@B` を推論に使う。
- 少ない追加パラメータ・少ない計算資源で、基盤モデルの知識を保ったまま追加学習できる。
- 「公開重みは維持しつつ独自学習要素を追加する」という構成が、ルールの「独自学習要素が
  最終的なAction生成に実質的に寄与する必要がある」という要件とちょうど合致する。

## 本選のTrack構成（6/19説明会資料で判明）

以前「未確定」としていた、本選でTrack2・Track3が加わるかという疑問はほぼ解消した。
6/19の説明会要約に明確な記述がある。

- 本選は仮想シミュレーター上でTrack1〜3すべてに挑戦する構成。3ヶ月間実施され、
  月次評価を経て最終的に上位50組に絞り込まれる。
- Q&Aにも「特定のトラックだけ独立して評価するのではなく、Track1〜3を毎回総合的に
  評価して順位を決定する」と明記されており、**ラウンドごとにTrackが1つずつ追加される
  のではなく、本選を通じて常に3Track合算で評価される**らしい。
  （前回のノートで立てていた「1ラウンドごとに1Trackずつ追加されるのでは」という
  仮説は誤りだった可能性が高い。）
- 各Trackの内容（予選のTrack1と比較する上でも参考になる）:
  - Track1（基本動作・適応力）: 単一タスクをベースに、カメラ位置のズレやノイズへの
    ロバスト性を評価。予選で評価されるのはこのTrack1のみ。
  - Track2（複数タスクの組み合わせ）: 複雑な一連のシーケンスを実行する能力を評価。
  - Track3（未知のタスク・総合制御）: 実行完了率に加え、実行効率・安全性を満たし
    ながら自律的に動けるかを総合評価。

### Track1〜3は同一モデルで評価されると考えられる

対話の中で改めて突き合わせて気づいた点。単なる推測ではなく、正式ルール文書冒頭の
コンテスト課題名に直接の根拠がある。

- コンテスト課題は「Vision-Language-Action（VLA）モデルが**駆使する汎化性能の
  3段階評価**」と明記されている。1つのモデルの汎化能力をTrack1→2→3の3段階で
  測るという設計であり、Trackごとに別モデルを用意してしまうと「汎化性能評価」
  という趣旨自体が崩れる。
- 状況証拠: `policy_server.py` の提出インターフェース（`get_action(obs)` /
  `reset(instruction)`）はTrack固有の情報を受け取る仕組みがなく、どんなタスクが
  来ても同じポリシーで対応する前提の作りになっている。6/19 Q&Aの「Track1〜3を
  毎回総合的に評価して順位を決定する」という記述とも整合する。
- 留保: 「Trackごとに別モデルの提出は不可」と明文で禁止した一文はまだ見つけて
  いない。規約上の断言ではなく、競技趣旨とインターフェース設計から見た強い推論
  に留まる。本選の提出フォームがTrackごとに分かれているかは要確認。

## 開発方針について

→ 自分（ユーザー）が実際に採用した方針・意思決定は [my_strategy.md](my_strategy.md)
に分離して記録している（2026-08-02〜）。このファイルには、方針の背景となる
競技理解・技術調査・Claudeの未採用の仮説のみを置く。

### 学習時の分布拡張アプローチ（Claudeの戦略仮説、要検証）

「学習段階で自作の未知タスクに挑ませる」という発想の効き方を対話で整理した。
競技資料に明記された話ではなく、Claudeの推論であり実際に効果があるかは
今後手元で検証が必要。

- Track3の実評価タスクそのものは非公開のため、直接は当てられない。効くのは
  「個々のタスクを覚えさせる」ことではなく、**タスクの構成要素（物体・動作・
  指示表現）の組み合わせ方に対する頑健性を、自作の多様なタスクバリエーションで
  鍛える**という一段上のレイヤー。
- 各Trackが試す軸に対応させると学習戦略を立てやすい:
  - Track1（外乱ロバスト性）→ カメラ視点のジッタ・ノイズを加えたdomain
    randomizationが直接効く
  - Track2（複数タスクの組み合わせ）→ 複数ステップを連結した複合instructionを
    自作して学習データに混ぜる
  - Track3（未知タスク＋効率・安全性）→ 物体の組み合わせ・配置・言い回しを
    大量に自作しバリエーションを広げる。個別タスクの丸暗記に寄ると逆効果になり
    うる点に注意
- LIBERO-plusは複数のタスクスイート（spatial/object/goal等）を持つため、
  `compe/t1/` のexampleタスクだけでなく他スイートも学習に混ぜるのも一案。

## 未確定・要確認事項

- **参加人数の記述に食い違いがある。** 6/19説明会資料には「8月上旬: 予選開始
  （約500名選抜）」「本選の計算資源はNVIDIA RTX Pro 6000 Blackwellを予選通過者
  （約500名）に提供予定」という記述がある（後半は文字化けが激しく解読に自信が
  低い箇所を含む）。一方、正式ルール文書（2026/07/31 版 v1.0）は「予選最終評価
  ランキングとレポートの内容を踏まえ**上位200人**を本選へ選出」と明記している。
  - 6/19資料は正式ルール確定前の説明会時点の情報であり、日付上は7/31の正式ルールの
    方が新しい＝優先されるはずだが、数字が食い違ったまま放置されている点は注意。
  - 本選に何人残れるかは、対策の力配分（どれだけ上位を狙うか）に関わるため、
    Slackで最新の正式な数字を確認した方がよい。
- 上記のTrack構成の理解も6/19時点の説明会情報であり、7/31の正式ルール文書には
  本選のTrack詳細そのものは記載されていなかった（予選ルールのみが正式配布された
  段階のため）。本選開始が近づいた際に、正式資料での再確認が必要。

---

## LIBERO-plusの摂動カテゴリ別・ローカル資産カバレッジ（2026-08-02調査）

自前のholdoutテストケース（`compe/t1/holdout_test_tasks.csv`）を組む過程で、
LIBERO-plusが定義する7つの摂動カテゴリ（`task_classification.json`）のうち、
**このリポジトリのチェックアウトに実体ファイル（`.bddl`/`.pruned_init`）が
存在するのは一部だけ**であることが分かった。本番の評価ハーネスの実装を
直接見ることはできないが、この非対称性は本番側の仕組みを推測する手がかりに
なるかもしれないので記録しておく。

### カテゴリ別の状態

| カテゴリ | `.bddl`実体 | `.pruned_init`実体 | 備考 |
|---|---|---|---|
| Background Textures (`_table_N`) | ○ | ○（base名を共有、`register.py`の`_SUFFIX_RE`が対応済み） | 難易度ラベルとファイルが一致 |
| Light Conditions (`_light_N`) | ○ | ○（base名を共有、regex対応済み） | 同上 |
| Objects Layout (`_add_N`) | ローカルに見当たらず | `init_files/libero_newobj/`配下に別途あり | ディレクトリ構成が`register.py`の想定と異なる |
| Camera Viewpoints / Robot Initial States (`_view_..._initstate_N`) | **存在しない** | **存在しない** | 3スイートとも0件 |
| Sensor Noise (`_noise_N`) | **存在しない** | **存在しない** | 同上 |
| Language Instructions | **公式カタログの名前（`_language_N_view_0_0_100_0_0_initstate_0`のような接尾辞付き）には対応する`.bddl`が1件も無い** | 同左 | `libero_spatial`0/390、`libero_object`0/354、`libero_goal`0/410で全滅を確認 |

### Language Instructionsの厄介な点

`task_classification.json`が難易度L1〜L5を付与しているLanguage Instructions
バリアント名は、実際には接尾辞に`_view_0_0_100_0_0_initstate_0`のような
カメラ視点・ロボット初期状態のパラメータ（デフォルト値のまま）が付加された
複合名になっている。一方、**接尾辞なしの`<base>_language_N.bddl`という
シンプルな名前のファイルは実在する**が、そちらは`task_classification.json`に
一切登録されておらず、公式の難易度ラベルが付いていない。

- 「難易度が分かる名前」→ 実体ファイルが無い
- 「実体ファイルがある名前」→ 難易度が分からない

という食い違いが起きている。

### 推測（裏取りできていない仮説）

Camera Viewpoints・Robot Initial States・Sensor Noise・
（難易度付き）Language Instructionsの4カテゴリは、静的な`.bddl`/
`.pruned_init`ファイルとして配布されているのではなく、**本番の非公開評価
ハーネス側で、ベースタスクのシーンに対してカメラ視点・ロボット初期関節角・
観測ノイズ・指示文言い換えを実行時に動的に適用する**形で実装されている
可能性がある。ローカルのLIBERO-plusチェックアウトはBackground Textures /
Light Conditions / Objects Layoutのように「物理的なシーン配置そのものが
変わる摂動」だけを静的ファイルとして持ち、残りは評価時の処理として別途
実装されている、という仮説。ただしこれは`assets.zip`（HFの
`Sylvest/LIBERO-plus`データセット、レンダリング用アセット）側に含まれて
いないかまでは未確認であり、裏取りできていない。

### この調査を踏まえた対応（2026-08-02決定）

`register.py`の`_SUFFIX_RE`を拡張してLanguage Instructionsに対応させる案を
検討したが、上記の通り**そもそも難易度付きの実体ファイルが存在しないため
regexの修正だけでは解決しない**と判断し、見送った。holdoutテストケースは
Background Textures / Light Conditionsの2カテゴリのみを使う方針
（[my_strategy.md](my_strategy.md)の方針2-1）を維持する。

---

## SmolVLA (`lerobot/smolvla_libero_plus`) を policy_server.py に組み込む際の入出力仕様

`submission_template/policy_server.py`にSmolVLAベースの推論を実装するにあたり、
チェックポイント（`config.json`・正規化統計の`.safetensors`）を実際にHFからダウン
ロードして中身を確認し、LeRobot v0.6.0（`examples/`のノートブックが使うタグ）の
ソースを読んで、生のLIBERO観測からモデル入力への変換方法を裏取りした
（2026-08-02）。

- **画像キー**: `agentview_image`→`observation.images.front`、
  `robot0_eye_in_hand_image`→`observation.images.wrist`（チェックポイント同梱の
  `policy_preprocessor.json`の`rename_observations_processor`が、さらに内部で
  `camera1`/`camera2`にリネームする）。
- **画像の向き**: 学習データ側は生のrobosuite画像を**上下左右反転（180度回転）**
  させたものを使っている（LeRobotの`LiberoProcessorStep`が`torch.flip(img,
  dims=[2,3])`を行う一方、`lerobot`の`LiberoEnv._format_raw_obs`自体はraw画像を
  無加工で渡している点を確認した＝flipは環境側ではなく前処理側の仕事）。
  `get_action`内で`obs["agentview_image"][::-1, ::-1, :]`のように反転してから渡す
  必要がある。見落とすと画像の意味論が学習時と食い違ったまま推論することになる。
- **画像解像度**: 前処理内部（`prepare_images`→`resize_with_pad`）が任意サイズを
  512×512へパディングリサイズするため、本番の128×128入力でも学習時の256×256と
  別に手動リサイズする必要はなかった（以前「見落としやすい落とし穴」として記録
  していた懸念は解消）。
- **状態ベクトル `observation.state`**: `config.json`の`input_features`には
  shape `[6]`と書かれているが、これは古い/不整合なメタデータで、実際に保存されて
  いる正規化統計（`policy_preprocessor_step_5_normalizer_processor.safetensors`の
  `observation.state.mean`等）も、学習データセット`lerobot/libero_plus`の
  `meta/info.json`も、どちらも**8次元**。中身はLeRobotの`LiberoProcessorStep`と
  同じ`[eef_pos(3), eef_quatをaxis-angleに変換した3値, gripper_qpos(2)]`。
  quaternionはxyzw順（`robot0_eef_quat`と同じ順序なので変換だけでよい）。
- **言語指示**: `reset(instruction)`で受け取った文字列をそのまま`task`として
  渡せば、チェックポイントの`tokenizer_processor`がトークナイズする。
- **action chunking**: `SmolVLAPolicy`は`chunk_size=50`/`n_action_steps=50`で
  内部にactionキューを持ち、`select_action()`を呼ぶたびに自動で管理する
  （キューが空の時だけ推論を実行し、50ステップ分をキャッシュする）。
  `reset()`で`self.policy.reset()`を呼べばキューがクリアされる。自前でchunking
  ロジックを書く必要はない。
- **起動時間の落とし穴**: チェックポイントの`config.json`は`load_vlm_weights:
  true`になっており、素直にロードするとSmolVLM2-500Mの初期重みをHFから別途
  ダウンロードしてから、直後にcheckpoint全体の`model.safetensors`で上書きする
  という二度手間が発生する。`examples/`のノートブックもmerge後推論では
  `config.load_vlm_weights = False`にしてこれを回避しており、120秒の起動
  タイムアウト対策として同じ対応を`policy_server.py`実装に入れた。
- **前処理・後処理の実装方針**: 正規化統計やトークナイズ・リサイズを自前実装
  すると事故りやすいため、`lerobot.policies.factory.make_pre_post_processors`
  でチェックポイント同梱の`policy_preprocessor.json`/`policy_postprocessor.json`
  をそのまま読み込んで使う設計にした（手書きが必要なのはLIBERO環境固有の
  画像flipと状態ベクトル構築の部分だけ）。
- **実機での動作確認（2026-08-02、完了）**: `.local_libs/verify/venv_smolvla/`
  （既存の評価ハーネス用`venv/`とは別の、`uv venv --python 3.12`で作った専用
  venv。`.local_libs/`は`.gitignore`済みなので誤ってコミットされる心配はない）
  に`torch`（GPU版）+ `lerobot[smolvla]==0.6.0`を入れ、`MyPolicy`を実際に
  ロードしてダミー観測で`get_action()`を60ステップ・2エピソード分実行した
  （テストスクリプト: `.local_libs/verify/smoke_test.py`）。
  - 起動（`__init__`＝モデルロード）: 51.7秒（120秒制約に余裕あり）
  - 推論（`get_action`）: 通常ステップは約0.001秒、50ステップごとのchunk再計算
    時でも約0.33秒（10秒制約に大きな余裕）。GPUは後述のRTX5090で、本番の
    ターゲットハードL4より高速な点は考慮が必要。
  - 出力: shape `(7,)`、dtype `float32`、NaN/Infなし。`reset()`を挟んだ
    2エピソード目も正常動作。
  - `policy_server.py`側の修正は不要だった（一発で通った）。
  - 検証手順の再現方法: `uv venv --python 3.12 <どこか>/venv_smolvla` →
    `uv pip install torch --index-url https://download.pytorch.org/whl/cu128
    --extra-index-url https://pypi.org/simple` → `uv pip install
    "lerobot[smolvla]==0.6.0"` → `uv pip install -r
    submission_template/requirements.txt` →
    `python .local_libs/verify/smoke_test.py`。

## GPU環境の状態（`askr5090`、2026-08-02確認）

- `nvidia-smi`が`Failed to initialize NVML: Driver/library version mismatch`
  で失敗する。カーネルにロード済みのモジュール（`/proc/driver/nvidia/version`）
  は`595.71.05`、NVMLライブラリ側は`595.84`で版が食い違っている。
- **ただし実計算は正常に動く。** `libcuda.so`を`ctypes`で直接叩いて
  `cuInit`→`cuDeviceGetName`（"NVIDIA GeForce RTX 5090"取得）→`cuCtxCreate`→
  `cuMemAlloc`/`cuMemFree`まで成功することを確認済み。`torch.cuda.is_available()`
  も`True`を返し、実際に行列積・SmolVLAの推論（上記）まで動く。
  壊れているのは`nvidia-smi`によるモニタリングだけで、GPU自体は使える。
- VRAM: 総量約31.4GB、確認時点の空き約19.2GB（他ユーザーのジョブが一部を
  専有している可能性がある共有マシン）。`nvidia-smi`が使えないので、空き容量は
  `python -c "import torch; print(torch.cuda.mem_get_info())"`で確認する。
- 本番のターゲットハードはL4（24GB、`competition_analysis.md`の別セクション
  参照）なので、この`askr5090`環境（RTX5090、31.4GB）は動作確認には十分だが、
  推論速度はL4より速く出る点に注意（タイムアウト制約の余裕を過大評価しない）。

## SmolVLAベース重み、Track1 exampleタスクでの試走結果（2026-08-02）

`policy_server.py`のSmolVLA実装（追加学習なし、`lerobot/smolvla_libero_plus`
そのまま）を、`pipeline/`の部品（`EnvironmentManager`/`RemotePolicyClient`）を
使って実際に`compe/t1`の4 exampleタスクで走らせた。256×256レンダリング
（`LIBERO_EVAL_CAMERA=256`）・osmesaソフトウェアレンダリング（このマシンでは
EGLが`/dev/dri`の権限不足で使えず、フォールバック）。生成・録画用のツールは
使い捨てスクリプトから正式に`src/record_rollout.py`として切り出した
（使い方は`src/README.md`参照、pipeline本体は変更していない）。

- **結果（task平均成功率、公式の`scorer.py`と同じ集計方法）**: **3.1%**
  （black_bowl 0/3、tomato_sauce 0/3、milk 0/3、stove 1/8＝動画取得のため
  複数回に分けて実行し合算）。プールした素の成功率は1/17≈5.9%。
- **試行数は各タスク3エピソード程度**で、成功率の絶対値自体を追加学習効果の
  指標に使うにはサンプル不足。目的は「一気通貫でちゃんと動くか」の確認であり、
  達成できている（起動・推論・アクション出力すべて正常、10秒/120秒制約にも
  余裕）。
- **同一タスク・同一初期状態でも試行ごとに結果が変わることを繰り返し確認した**:
  `stove`タスクだけでも、3エピソード中2成功だった回・3エピソード中0成功
  だった回・5エピソード中1成功だった回があった。`SmolVLAPolicy._get_action_chunk`
  が呼ぶ`sample_actions`のflow-matchingサンプリングにノイズが乗る（`noise`
  引数を固定していない）ため、環境のseedが同じでも行動系列は毎回微妙に変わる。
  今後、学習後モデルの評価で試行回数を増やす際はこの点を踏まえること
  （1〜数エピソードだけでの比較は結論を誤りやすい）。
- **動画コーデックの落とし穴**: 最初`cv2.VideoWriter`の既定コーデック`mp4v`
  （MPEG-4 Part 2）でmp4を書き出したところ、ファイル自体は正常でも
  ブラウザの`<video>`タグで再生できなかった（H.264でないため）。
  `imageio` + `imageio-ffmpeg`（`libx264`, `yuv420p`）に切り替えて解決した。
  `src/record_rollout.py`はこの対応込みの実装になっている。
- ベース重み（追加学習なし）でこの程度の成功率が出ているのは想定内。次の
  ステップは`examples/`のLoRA学習ノートブックで実際にTrack1向けデータを
  学習させ、この試走をベースラインとして比較すること。

## 採点環境の正確な仕様が判明（2026-08-04、主催者配布のREADME.md更新版より）

配布環境READMEの更新版（現在は`README.md`本体に取り込み済み）に、以前は書かれていなかった
「採点環境」節が追加されていた。これまで`competition_analysis.md`/`my_strategy.md`
に書いていたハードウェア・ソフトウェア構成の記述はこの情報が無い時点の推測を
含んでいたため、正確な一次情報として記録する。

- ベースイメージ: `nvidia/cuda:13.0.3-cudnn-devel-ubuntu22.04`（Ubuntu 22.04.5）
- **Python: 3.10.12（システムPython、`/usr/bin/python3.10`）**
- CUDA Toolkit 13.0（`nvcc`によるソースビルド可）、cuDNN 9.14.0、NCCL 2.28.3、
  ドライバR580系
- **PyTorch: 2.11.0+cu130（プリインストール済み）**
- レンダリング: `MUJOCO_GL=EGL`（GPUレンダリング。このサンドボックス開発機とは
  異なり、本番はEGLが正常に使える）
- 評価パイプライン側の主要依存はローカルの`venv/`と同一版で固定
  （`numpy==1.26.4`, `mujoco==3.7.0`, `robosuite==1.4.0`, `gym==0.25.2`,
  `bddl==3.6.0`, `fastapi==0.140.7`, `uvicorn==0.51.0`, `msgpack==1.2.1`,
  `huggingface_hub==1.25.1`等）
- **提出物の依存インストール方式**: 提出物専用の**`--system-site-packages`
  付きvenv**に対して`pip install -r requirements.txt`する。
  - `requirements.txt`に書かなかったライブラリは、採点イメージにプリ
    インストールされている版がそのまま使われる（`torch`を書かなければ
    `2.11.0+cu130`がそのままCUDA13と整合した状態で使われる）。
  - 書いた版はvenv側が優先され、提出物のサーバーにのみ効く
    （評価パイプライン側には影響しない）。
- **CUDA12系torchを使う場合の注意**: 採点イメージには`libnvJitLink.so.13`しか
  無く`.so.12`の代替にはならない。CUDA12ビルドのtorchを使うなら、それが必要と
  する`nvidia-*-cu12`一式がvenv側にそろっている必要がある（特に
  `nvidia-nvjitlink-cu12`が無いと`ImportError: libnvJitLink.so.12: cannot
  open shared object file`で起動失敗する）。`pip install`時に
  「`X requires Y, but you have Z`」という依存衝突警告を残さないことが重要。
- 採点イメージには**競合ベースライン実装（pi0.5 / openpi、JAXベース）の依存
  一式も同時に焼き込まれている**（`jax[cuda12]==0.5.3`, `jaxlib==0.5.3`,
  `flax==0.10.2`, `orbax-checkpoint==0.11.13`, `transformers==4.53.2`等）。
  自分のモデルに必要な依存は「イメージに入っているはず」と仮定せず、
  `requirements.txt`に明示すること（イメージはアップデートされうる）。
- 提出前の確認方法として、`--system-site-packages`込みの本番相当venvを
  作った上で`python -c "import torch; print(torch.__version__,
  torch.cuda.is_available())"`を実行することが推奨されている。
  Dockerで本番相当（GPU）を再現する場合は`Dockerfile`の`FROM`をこの
  CUDA13イメージに、`setup.sh`のtorchを`torch==2.11.0`
  （`--index-url https://download.pytorch.org/whl/cu130`）に差し替えて
  `docker run --gpus all`で起動する。

## lerobotのPython版要求と、実際に採点で失敗した件（2026-08-04）

`policy_server.py`のSmolVLA実装（`lerobot[smolvla]==0.6.0`指定）を実際に
採点環境へ提出したところ、依存インストールの段階で失敗し0点になった。

```
ERROR: Could not find a version that satisfies the requirement lerobot==0.6.0
  (from versions: 0.1.0, 0.3.2, 0.3.3, 0.4.0, 0.4.1, 0.4.2, 0.4.3, 0.4.4)
```

- **原因**: PyPIの`lerobot`は`0.5.0`以降すべて`requires-python>=3.12`だが、
  採点環境は上記の通りPython 3.10.12。examples/のColabノートブックは
  Python 3.12前提（Colabで`sys.version_info < (3,12)`をチェックしている）
  だったため、この版のズレに気づいていなかった。ローカルの動作確認も
  Python 3.12の専用venv（`.local_libs/verify/venv_smolvla/`）で行っており、
  同じ理由で気づけなかった。
- **対応（`my_strategy.md`方針5参照）**: Python 3.10で入る最新版
  `lerobot[smolvla]==0.4.4`に切り替え、Python 3.10の別venv
  （`.local_libs/verify/venv_py310_check/`）で実際に`lerobot/
  smolvla_libero_plus`チェックポイントのロード・推論・`validate_submission.py`
  の静的/動的チェックまで通ることを確認した。
- **0.4.4と0.6.0のAPI差分（要調整）**: `from lerobot.configs import
  PreTrainedConfig`は0.6.0のみ（`lerobot/configs/__init__.py`が
  `from .policies import PreTrainedConfig`で再エクスポートしている）。0.4.4には
  この再エクスポートが無く、`from lerobot.configs.policies import
  PreTrainedConfig`という完全パスでの参照が必要。`make_pre_post_processors`
  （`lerobot.policies.factory`）・`SmolVLAPolicy`
  （`lerobot.policies.smolvla.modeling_smolvla`）・
  `prepare_observation_for_inference`（`lerobot.policies.utils`）は
  両バージョンで同じ場所にあった。
- **0.4.4のtorch要求**: `pyproject.toml`で`torch>=2.2.1,<2.11.0`。採点環境の
  プリインストールは`torch==2.11.0+cu130`（`<2.11.0`を満たさない）なので、
  `lerobot[smolvla]==0.4.4`を`requirements.txt`に入れると、pipが自動的に
  条件を満たすtorch（CUDA12系、手元の検証では`torch==2.10.0+cu128`が選ばれた）
  を提出物用venvにインストールする。これはREADMEの「CUDA12系torchを使う場合の
  注意」に記載の想定内の挙動。
- **教訓**: 学習用ノートブック（Colab、Python 3.12）と推論コード
  （`policy_server.py`、採点環境はPython 3.10）で前提とするPython版が違う
  ことに、事前のローカル検証だけでは気づけなかった。今後は必ずPython 3.10の
  venvで最終確認してから提出する（`my_strategy.md`方針5の「含意」参照）。

## requirements.txtの追加検証（2026-08-04、`--system-site-packages`を模擬）

前節の検証は空のvenvにいきなり`lerobot[smolvla]==0.4.4`を入れる形だった。
`README.md`の「requirements.txtの書き方」が想定する実際の状況——**採点環境の
プリインストール一式（`torch==2.11.0+cu130`, `numpy==1.26.4`等）が最初から
入っている状態に、それをpipで上書きする**——をより忠実に再現して再検証した
（`.local_libs/verify/venv_faithful/`）。

- 空のPython 3.10 venvに、README付録のプリインストール一覧のうち主要な版
  （`torch==2.11.0+cu130`, `numpy==1.26.4`, `huggingface_hub==1.25.1`,
  `fastapi==0.140.7`等）を先に`pip install`し、その後で`submission_template/
  requirements.txt`を（`uv pip`ではなく**素の`pip install -r`**、pip版も
  実環境と同じ`26.1.2`で）インストール。
- 結果: **「`X requires Y, but you have Z`」という衝突警告は一切出ず**、
  `torch`は`2.10.0+cu128`に、`numpy`は`2.2.6`に、`huggingface_hub`は`0.35.3`に
  それぞれクリーンに巻き戻った。`nvidia-nvjitlink-cu12`（README指摘の必須
  パッケージ）も正しく入り、`torch.cuda.is_available()`は`True`、実際の
  CUDA行列積も成功した。
- この環境で`policy_server.py`のロード・推論・`validate_submission.py`の
  動的チェック（zip展開込み）まで実行し、全てPASSを確認した。
- **副産物の発見**: このテストの過程で、シェルのデフォルト起動時に
  `.local_libs/parc_lora/venv`という別のvenvが自動的に有効化されることに
  気づいた（`~/parc_lora_workspace/lerobot`・`~/parc_lora_workspace/
  LIBERO-plus`をeditableインストール済み）。おそらく別セッション/別作業で
  LoRA学習の準備が進行中と思われる。今回の検証はこの環境には一切触れて
  いない（`python3 -m pip`で明示的に対象venvを指定して実行した）。

## 2回目の提出失敗: evdevのビルドエラー、そしてlerobotのvendor化（2026-08-04）

lerobotをPython 3.10対応の0.4.4に切り替えて再提出したところ、依存インストール
段階で別のエラーが出て0点になった。

```
error: subprocess-exited-with-error
× Building wheel for evdev (pyproject.toml) did not run successfully.
...
src/evdev/input.c:10:10: fatal error: Python.h: No such file or directory
```

- **原因の特定**: `evdev`はLinux入力デバイス（キーボード・ゲームパッド等）を
  扱うライブラリで、C拡張（`_input`）のビルドにPythonヘッダー（`Python.h`）を
  要求する。PyPIの`evdev`はバージョン問わず一度もwheelを公開しておらず、常に
  ソースビルドが必要（`https://pypi.org/pypi/evdev/<version>/json`で全リリース
  確認）。採点環境にはこのヘッダーが無いためビルドが失敗する。
  `evdev`は`pynput`（`lerobot`が`pynput>=1.7.7,<1.9.0`をextrasと無関係に
  無条件必須依存として宣言）が要求しており、`lerobot`のバージョンを
  0.3.x〜0.4.4のどれに変えても同じ依存宣言があるため回避不可（PyPIの
  各バージョンのメタデータを実際に確認した）。
- **pynput/evdevが実際には不要なことの確認**: `SmolVLAPolicy`のロード・推論に
  実際に使うimportチェーン（`lerobot.configs.policies` →
  `lerobot.policies.factory` → `lerobot.policies.smolvla.*`等）を、
  pynput/evdevを削除した状態で実行しても正常に動作することを確認した
  （`pynput`はlerobotの実機テレオペ機能向けで、推論には無関係）。
- **requirements.txt側での回避を試みたが、全て`validate_submission.py`の
  静的検査で拒否されることを確認した**:
  - ローカル`.whl`ファイルを相対/絶対パスで参照 → `req.local_path`エラー
    （「setup.pyがinstall時に実行される」ため一律禁止）
  - `evdev @ file:///path/to.whl`のdirect reference構文 → `req.external_url`
    エラー（`parsed.url is not None`で検出）
  - `-f`/`--find-links`でローカルディレクトリを指す → `BANNED_REQ_OPTIONS`に
    含まれ一律禁止
  - つまり「evdevの偽の/軽量な代替パッケージを作ってローカル参照する」という
    アプローチはこの採点システムでは構造的に塞がれている。
- **最終対応（`my_strategy.md`方針6参照）**: `lerobot`パッケージ自体をpipで
  インストールするのをやめ、ソース一式を`submission_template/vendor/lerobot/`
  に同梱し、`policy_server.py`が起動時に`sys.path`へ追加する方式にした。
  vendorしたソースが実際に必要とする依存（`lerobot.policies.__init__`が
  全ポリシー種別を無条件importする作りのため、`groot`経由で`robots`/`motors`/
  `pyserial`まで芋づる式に読み込まれる等）を、Python 3.10のクリーンな環境で
  1つずつ実行時エラーを解消しながら特定し、`requirements.txt`に明示した
  （`torchvision`, `transformers`, `accelerate`, `safetensors`, `num2words`,
  `opencv-python-headless`, `draccus`, `datasets`, `diffusers`, `deepdiff`,
  `av`, `gymnasium`, `pyserial`, `imageio[ffmpeg]`）。幸い、これらは全て
  PyPIにwheelがあり、evdevのようなビルド問題は再発しなかった。
- **検証**: 採点環境のプリインストール状態を模した環境で、素の
  `pip install -r requirements.txt`が警告・エラーなしで完了し、`evdev`/
  `pynput`が一切インストールされないこと、モデルのロード・推論、
  `validate_submission.py`の静的・動的チェック（zip展開込み）が全てPASS
  することを確認した。
- **教訓**: `requirements.txt`に書いたパッケージだけでなく、それが
  無条件に引き込む「実機テレオペ用」等の無関係な依存まで含めて、実際に
  クリーンな環境で`pip install`が通るかを検証する必要がある。ローカルの
  開発環境（このサンドボックスにはPythonヘッダーが入っている）で
  ビルドが通っても、採点環境で通るとは限らない。

## 3回目の提出失敗: HF_HOMEの`setdefault`が採点環境で効かない（2026-08-06）

vendor化した提出物（`submission_smolvla_base_2026-08-04.zip`）を提出したところ、
ポリシーサーバーの起動自体に失敗して0点になった。

```
huggingface_hub.errors.LocalEntryNotFoundError: Cannot find an appropriate cached
snapshot folder for the specified revision on the local disk and outgoing traffic
has been disabled.
```

- **提出zipにキャッシュは正しく入っていた**: 展開して確認したところ、
  `model_weights/hf_cache/hub/models--lerobot--smolvla_libero_plus/snapshots/
  7bb70aa5.../model.safetensors`（907MB）を含む425ファイルが同梱されていた。
  つまり「キャッシュが無い」のではなく「HuggingFaceがそのキャッシュを
  見ていない」のが原因。
- **真因**: `policy_server.py`が`os.environ.setdefault("HF_HOME", ...)`を
  使っていた。採点環境は参加者サーバーを`nobody`ユーザーのサンドボックスで
  起動する都合上、`HF_HOME`（および/または`HF_HUB_CACHE`）を**あらかじめ
  独自の値で設定している**。`setdefault`は既存値があると何もしないため、
  同梱キャッシュのパスは無視され、`HF_HUB_OFFLINE=1`と相まって即死した。
- **再現**: ローカルで`HF_HOME=/tmp/bogus`を設定した状態で同じ`setdefault`
  ロジックを実行し、本番と同一の`LocalEntryNotFoundError`を再現した。
- **`HF_HUB_CACHE`は`HF_HOME`より優先される**ため、`HF_HOME`だけ上書きしても
  採点環境が`HF_HUB_CACHE`を設定していた場合には効かない。両方を明示的に
  代入する必要がある。
- **対応（`my_strategy.md`方針7）**: 環境変数を上書き代入に変更し、さらに
  保険として`snapshot_download()`を経由せず同梱スナップショットのパスを
  直接指す分岐を追加した。これでHFの環境変数解決に一切依存しなくなる。
- **教訓**: 実行環境が設定済みの環境変数を`setdefault`で「尊重」すると、
  同梱リソースを使わせたい場面では真逆の結果になる。サンドボックス化された
  採点環境では、自分の意図を環境変数に頼らず、可能ならパスで直接指定する。

## 0点の真因: `n_action_steps`の既定値50（2026-08-06）

方針7の修正で初めて採点が完走した（`submission_smolvla_base_2026-08-06.zip`）
が、スコアは0.000だった。サーバーログを解析すると、**8エピソードすべてが
ぴったり300ステップで終わっていた**。`pipeline/rollout.py`でエピソードが
終わる条件は`done`（ゴール達成）か`max_steps`到達の2つだけなので
（`episode_timeout_sec`はrollout内で未使用）、これは**ゴールに一度も
到達していない**ことを意味する。1mm衝突判定以前の問題だった。

- **実装バグは無かった**: checkpointとの整合性を5点検証し、すべてシロだった。
  重み500キーが`strict=False`でも欠損0・余剰0で完全一致（`load_vlm_weights=
  False`は無害）、`observation.state`の8次元がnormalizer統計の分布と一致
  （`config.json`の`state shape:[6]`は古いメタデータで、実体の統計は8次元）、
  画像キーは preprocessor の`rename_map`（`front→camera1`, `wrist→camera2`）に
  合致、180度回転がlerobot本家の`LiberoProcessorStep`と一致、画像は
  `prepare_observation_for_inference`で`/255`済み。観測画像を目視でも確認し、
  生のrobosuite画像が上下逆で180度回転が正しい向きに直すことを確かめた。
- **切り分け**: 摂動なしの素のLIBERO（`LIBERO/`）で走らせたところ、
  10タスク中1タスクが108ステップで成功した。つまり配線は正しく、ポリシーは
  タスクを完遂できる。ただし成功率が低すぎる。
- **真因**: checkpointの`n_action_steps`が**50**だった。20Hz換算で
  **2.5秒間、一切観測を見ずにアクションチャンクを流し切る**という設定で、
  学習時256×256に対し採点環境は128×128であるため、この解像度低下で生じた
  誤差が2.5秒の開ループ中に増幅して完全に破綻していた。
- **測定**（素のlibero_object 10タスク、300ステップ上限、1エピソード）:

  | 条件 | 成功率 |
  |---|---|
  | 128px / n=50（提出時の状態） | 10% |
  | 256px / n=50 | 30% |
  | 128px / n=10 | **90%** |

  解像度そのものではなく、**低解像度 × 長い開ループ**の組み合わせが効いていた。
  128pxのままでもnを縮めれば解決する。
- **本番相当（T1 exampleタスク4種、128px）**: n=50で0.0%（8エピソード全て
  300ステップ消化）→ n=10で**70.0%**（4タスク×5エピソード）。n=5も試したが
  66.7%で頭打ちで、推論回数だけ倍になるためn=10を採用（方針8）。
- **レイテンシ**: `/act`の最大0.111秒、平均0.014秒（重い推論は10回に1回）。
  10秒制限に対して90倍の余裕がある。
- **計測上の罠**: 検証中に評価クライアントを2つ同時に同じポリシーサーバーへ
  接続してしまい、15%/20%という嘘の数字が出た。サーバー側のポリシーは単一
  インスタンスで、action chunkのキューと`/reset`が混線する。**評価は必ず
  1クライアントずつ**行うこと。
- **教訓**: VLAのcheckpointに埋め込まれた推論時ハイパーパラメータ
  （`n_action_steps`等）は学習時の環境に最適化されており、採点環境の条件
  （解像度・摂動）が違えばそのまま使うと壊れる。重みを疑う前に、まず
  「摂動なしの素の環境で動くか」を切り分けると原因の所在が一発で分かる。

## 既存LoRAの再評価: n=10でもベースを超えなかった（2026-08-06）

方針8で`n_action_steps`を50→10に直したことで、8/4時点のLoRA評価
（`~/parc_lora_workspace/parc_holdout_comparison_holdout_eval.csv`、
ベース20.0% vs LoRA17.8%）が「開ループ長のノイズに埋もれていただけ」ではないかを
確かめるため、同じholdout15ケースで測り直した。

- **測定条件**: `src/eval_holdout.py`（新規）、3エピソード/タスク、128px、
  300ステップ上限、`n_action_steps=10`。ベースとLoRAを**同じハーネス**で
  測った（8/4の数字はノートブック側の評価コードによるもので、判定条件が
  揃っていなかったため）。
- **対象LoRA**: `~/parc_lora_workspace/smolvla_parc_lora_holdout_eval_merged/`
  （40,000ステップ学習後のマージ済みモデル）。

| | 旧測定（n=50、ノートブック） | 新測定（n=10、record_rollout） |
|---|---|---|
| ベース | 20.0% | **77.8%** |
| PARC LoRA | 17.8% | **75.6%** |
| Δ | −2.2pp | **−2.2pp** |

- **絶対値は4倍近く上がったが、差は変わらなかった**。内訳は改善2・悪化2・
  変化なし11。3エピソード刻み（±33.3pp）の粒度とSmolVLAのサンプリングノイズを
  考えると、この差は誤差の範囲で、**このLoRAに測定可能な効果は無い**と見るべき。
- `bbq_sauce`系5件は両者とも100%で天井。差が出たのは`black_bowl`系3件と
  `put_the_bowl_on_the_stove_light_11`（66.7%→0.0%）だけ。
- **LoRAモデルのconfig.jsonはlerobot 0.6.0で書かれており、提出物側の0.4.4では
  `pretrained_revision`フィールドで`DecodingError`になる**。評価時は当該キーを
  除いたconfig.jsonのコピーを作って読ませた（大きいファイルはsymlinkで参照）。
  LoRAモデルを提出物に載せる場合はこの変換が必須。

## ローカル評価セットが本番の難易度を再現できていない（2026-08-06）

上の測定でベースがholdout **77.8%** を出す一方、同じ重みの本番スコアは
**0.12839**だった。この差はLoRAの±2ppより遥かに大きく、**ローカル指標が
本番の代理になっていない**ことを示している。

- 本番ログには`[evaluate] タスク用途: 3_Omni`とある。**複数摂動の合成**条件。
- 一方ローカルのholdout15ケース（`compe/t1/holdout_test_tasks.csv`）は
  `Background Textures`か`Light Conditions`の**単一カテゴリ**摂動（L1〜L5）。
  T1のexampleタスク4件も同様。
- つまり現状のローカル評価は本番より大幅に易しい。この指標で改善を判断し続けると
  「ローカルでは天井に見えるのに本番は10%台」という状態から抜け出せない。
- **次にやるべきは、合成摂動（omni相当）のローカル評価セットを作ること。**
  LoRAの追い込みはその後。

---
最終更新: 2026-08-06
