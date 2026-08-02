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

---
最終更新: 2026-08-02
