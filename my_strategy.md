# 開発方針ノート（私の意思決定記録）

このファイルは、PARC2026予選・本選に向けて自分が実際に下した方針・意思決定を
記録する。競技資料の解釈や技術的な調査結果は [competition_analysis.md](competition_analysis.md)
に記録しており、このファイルはそれとは別に「何を選んだか、なぜそう選んだか」
だけを追う。Claudeの推論・仮説で、まだ自分が採用を決めていないものは
`competition_analysis.md`側に置く（例: 学習データ拡張の戦略仮説）。

---

## 方針1: 単一モデルでTrack1〜3すべてに対応する（2026-08-02決定）

Track1〜3ごとにモデルを訓練し直すのは手間が大きいため、単一のモデルで全Track
に対応できるようにする。

- **根拠**: 競技のコンテスト課題名が「VLAモデルが駆使する汎化性能の3段階評価」
  であり、1つのモデルの汎化能力をTrack1→2→3で測る設計だと考えられる
  （詳細な根拠は`competition_analysis.md`の「Track1〜3は同一モデルで評価される
  と考えられる」参照）。競技側の想定にも沿っている。
- **含意**: 学習データやLoRAの組み方をTrack1（単一タスク＋外乱ロバスト性）だけに
  最適化しすぎると、Track2（複数タスク組み合わせ）・Track3（未知タスク＋効率・
  安全性）で汎化せず落ちるリスクがある。予選対応で終わらせず、instructionの
  多様性やタスク構成の広さを意識したデータ設計を早めに意識しておく。

## 方針2: 3スイート（spatial/object/goal）それぞれで基本タスクを1つholdoutし、
汎化性能の検証専用に使う（2026-08-02決定、同日中に対象タスクを再検討）

`libero_spatial`・`libero_object`・`libero_goal`それぞれで、元の10基本タスクの
うち9つを学習に使い、残り1つを丸ごと学習データから除外して、学習後の汎化性能を
確認するための検証専用タスクとして使う。

- **なぜ基本タスク単位でholdoutするか**: `task_classification.json`
  （LIBERO-plusのベンチマーク定義）を調べたところ、難易度（L1〜L5）は基本タスク
  ではなく個々の摂動バリアントに紐づく属性で、どの基本タスクを選んでも
  L1〜L5がまんべんなく存在することを確認した。よって「どの基本タスクを
  holdoutするか」と「その中でどの難易度をテストケースにするか」は独立に決め
  られる。基本タスクごとholdoutすることで、「同じタスク構造は学習済みだが
  当該タスクの摂動条件は未見」という狙い通りの汎化テストになる。
- **holdoutする基本タスク（各suiteから1つ、計3つ）**:
  - `libero_spatial`: `pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_
    cabinet_and_place_it_on_the_plate`
  - `libero_object`: `pick_up_the_bbq_sauce_and_place_it_in_the_basket`
    （**2026-08-02当日中に`tomato_sauce`から変更**。理由は下記）
  - `libero_goal`: `put_the_bowl_on_the_stove`
  - spatial・goalの2つは`compe/t1/T1_TASKS.csv`のTrack1 example（4タスク）に
    含まれる基本タスクと同じものを選んだ。既にL3/L4の代表バリアントの情報が
    手元にあり、他の資料との対応が付けやすいため。
- **なぜ`libero_object`だけ`tomato_sauce`ではなく`bbq_sauce`にしたか**: 当初は
  Track1 exampleに出てくる`tomato_sauce`（L5）をholdout候補にしていたが、
  `task_classification.json`のBackground Textures/Light Conditionsカテゴリの
  バリアントを検証したところ、`tomato_sauce`はL1に相当する変体（`_tb_6`という
  命名）に対応する`.pruned_init`ファイルがローカルに存在せず、Light Conditions
  側もL1〜L3自体が存在しないため、L1〜L5を揃えられないことが判明した。
  `libero_object`の残り8基本タスクのうち7つ（`bbq_sauce`含む）はL1〜L5すべてで
  実ファイルが確認できたため、`tomato_sauce`から`bbq_sauce`に変更した。
  （`milk`はTrack1 exampleのタスク3として引き続き学習データに残す方針は変更なし。
  易しいタスクで基本構造を学ばせる狙いのため。）
- **具体的なテストケース（15件、L1〜L5×3suite）**: 摂動カテゴリは
  Background TexturesとLight Conditionsのみを使用（後述の方針2-1参照）。
  一覧は`compe/t1/holdout_test_tasks.csv`に保存済み。
- **留保**: 実際の本番学習では9基本タスク×学習エピソード数で足りるかは未検証。
  この方式は「動くかどうか・汎化を測れるか」の検証用であり、本番の学習データ
  設計（もっと広いデータが必要になるはず）とは切り離して考える。

## 方針2-1: テストケースの摂動カテゴリはBackground Textures/Light Conditions
に限定する（2026-08-02決定）

方針2のholdoutタスクから難易度L1〜L5のテストケースを選ぶ際、摂動カテゴリは
LIBERO-plusが持つ7種類（Background Textures / Light Conditions / Camera
Viewpoints / Robot Initial States / Sensor Noise / Objects Layout / Language
Instructions）のうち、Background TexturesとLight Conditionsの2つだけに限定した。

- **技術的な理由**: `compe/t1/register.py`の初期状態ファイル読み込み
  （`_SUFFIX_RE = re.compile(r"_light_[^.]*|_table_\d+")`）は、`_table_N`と
  `_light_N`という接尾辞だけを取り除いて元タスクの`.pruned_init`を探す仕組み。
  実際にリポジトリを確認したところ、Camera Viewpoints・Robot Initial States・
  Sensor Noiseの3カテゴリは対応する`.bddl`/`.pruned_init`ファイルがローカルに
  一切存在せず、Objects Layoutは別ディレクトリ（`init_files/libero_newobj/`）
  に依存していた。**Language Instructionsも当初はregexの拡張だけで対応できる
  と見ていたが、実際に改造を試みたところ、`task_classification.json`が難易度
  ラベルを付与している変体名（`_language_N_view_0_0_100_0_0_initstate_0`の
  ような接尾辞付き）に対応する`.bddl`自体が3スイートとも1件も存在しないことが
  判明し、regexの修正だけでは解決しないと分かった**（接尾辞なしの
  `_language_N.bddl`は実在するが、そちらは難易度が付与されていない）。詳細な
  調査記録は[competition_analysis.md](competition_analysis.md)の「LIBERO-plusの
  摂動カテゴリ別・ローカル資産カバレッジ」参照。Background TexturesとLight
  Conditionsの2つだけが現状の`register.py`のまま確実に動く。
- **Language Instructionsが本番採点で使われているか**: **不明**。
  `compe/t1/T1_TASKS.csv`（本番と同形式・同難易度帯とされる練習問題4件）は
  Background TexturesとLight Conditionsしか使っておらず、Language
  Instructionsへの言及はどの手元資料にもない。ただしLIBERO-plus本体の
  正式な7カテゴリの1つではあるため、本番の非公開タスクセットで使われて
  いない証拠にもならない。判断材料が手元にない、というのが正直なところ。
- **`register.py`を書き換えて対応カテゴリを増やすのはルール的にどうか**:
  配布された競技ルール文書（`PARC2026開発コンペティション_予選`資料）を
  確認したが、`compe/t1/register.py`のような練習用ローカルツールの改変を
  直接禁止する記述は見当たらなかった。同資料の禁止事項は主に「評価環境への
  外部アクセス」「scene ID/task ID/評価seed等をキーにした行動テーブルによる
  ズル」「評価環境専用のガードレールに抵触するコード」など、**提出する
  policyの本番評価時の挙動**に関するものであり、`compe/t1/`はTrack1の
  example taskをローカル登録するための練習ツールであって提出物
  （`submission_template/`）には含まれない。そのため書き換えても提出ルール
  には抵触しなさそうだが、これはルール文書からの推測であり、「練習ツールの
  改変は自由」と明記されているわけではない。**不明点が残ることは承知の上で
  現状はBG/Light限定のまま進める**判断とした（regexの拡張は今回は行っていない）。

## 方針3: ベースモデルにSmolVLA（`lerobot/smolvla_libero_plus`）を採用し、まず追加学習なしで動作確認する（2026-08-02決定）

`submission_template/policy_server.py`の`MyPolicy`を、SmolVLAをベースにした推論
実装に置き換えた。LoRA追加学習はまだ行わず、まずベース重みのままで
policy_server↔pipelineのエンドツーエンド疎通を確認する段取りにする。

- **なぜSmolVLAか**: モデル規模・VRAM・10秒推論タイムアウトの組み合わせから
  「SmolVLA級（数億パラメータ）の軽量VLAが現実的」という分析結果
  （`competition_analysis.md`の「ベースモデル選定にかかる制約」参照）を受けて
  採用した。`examples/`のLoRA学習ノートブックも同じ`lerobot/smolvla_libero_plus`
  を前提にしており、後続のLoRA学習ともそのまま接続できる。
- **なぜ先にベース重みで動かすか**: LoRA学習・評価・提出物への組み込みを一度に
  やると、どこで問題が起きたか切り分けにくい。まずベース重みで
  「policy_serverとして正しく動くか（起動する・推論が返る・タイムアウトに
  収まるか）」を確認してから、LoRA学習に進む方が安全と判断した。
- **切り替え方法**: `SMOLVLA_MODEL_PATH`環境変数でモデルの参照先を切り替えられる
  実装にした。`examples/`のノートブックでLoRAを学習・マージした後は、同じコードの
  まま出力先ディレクトリを指すだけで差し替えられる。
- **前処理・後処理は自前実装しない方針にした**: 正規化統計・トークナイズ・
  画像リサイズは、チェックポイント同梱の`policy_preprocessor.json`/
  `policy_postprocessor.json`を`lerobot`の`make_pre_post_processors`でそのまま
  読み込んで使う設計にした。手書きすると正規化統計の再現ミス等で事故りやすい
  ため。自前で書いたのはLIBERO環境固有の画像flipと状態ベクトル構築（8次元）
  の部分のみ（詳細は`competition_analysis.md`の該当セクション参照）。
- **実機確認済み（2026-08-02）**: 開発機`askr5090`は`nvidia-smi`が版不一致で
  動かないため一見GPUが使えないように見えたが、`libcuda.so`直叩きで実計算は
  正常と判明。既存の評価ハーネス用`venv`とは別の専用venv
  （`.local_libs/verify/venv_smolvla/`、`.gitignore`済みで安全）を用意し、
  `MyPolicy`を実際にロードしてダミー観測で推論まで通した。起動51.7秒・推論
  最大0.33秒でどちらもタイムアウト制約に十分収まり、修正不要で一発で通った
  （詳細は`competition_analysis.md`の該当セクション参照）。次はLoRA追加学習に
  進める段階。

## 方針4: 採点環境オフライン疑惑への対応として、モデル重みをzipに同梱する（2026-08-02決定）

`policy_server.py`の`MyPolicy`がデフォルトでHugging Face Hubからモデルを
ダウンロードする実装だったが、README.mdに「採点環境は外部通信を遮断する」と
明記されており、本番でモデルロードに失敗する疑いがあった
（`competition_analysis.md`および`overview.md`参照）。対話で疑いを共有し、
「そうしよう」で対応を決定。

- **やったこと**: `src/download_model_weights.py`を新設し、`MyPolicy`を実際に
  ネットワークありで一度動かして、触れたファイル一式（SmolVLA本体＋
  `HuggingFaceTB/SmolVLM2-500M-Video-Instruct`のトークナイザ）を
  `submission_template/model_weights/hf_cache/`にHFキャッシュとして保存する
  方式にした。`policy_server.py`側は、このディレクトリがあれば
  `HF_HUB_OFFLINE=1`で完全オフライン起動に自動的に切り替わるよう変更した
  （無ければ従来通りオンライン取得、ローカル開発の後方互換は維持）。
- **なぜ「必要なファイルを手で列挙」ではなく「実際に動かして集める」方式に
  したか**: `load_vlm_weights=False`にしていても`AutoProcessor.from_pretrained()`
  がトークナイザを別途ロードする等、静的にコードを読むだけでは見落としそうな
  依存があった（実際`smolvlm_with_expert.py`のソースを読んで確認した）。
  実行時に触れたものを丸ごとキャッシュする方が確実。
- **symlinkの罠**: 既定のHFキャッシュ形式（`blobs/`実体を`snapshots/`から
  symlink参照）のままだと、`validate_submission.py`の`zip.slip_symlink`
  チェックに引っかかって提出zipとして拒否される。`HF_HUB_DISABLE_SYMLINKS=1`
  で実ファイル展開にして回避した。
- **検証**: `submission_template/`をzip化し（`zip -rq -X`）、
  `validate_submission.py`の静的チェック・動的チェック（zip展開→サーバー起動
  →`/health`→`/reset`→`/act`）両方でPASS（errors=0）を確認済み。zip自体の
  サイズは約686MB（20GB制限に対して十分小さい）。
- **含意**: 今はベース重み（LoRA未実施）をこの方式で同梱している。LoRAで
  マージ済みモデルを作った後は、`SMOLVLA_MODEL_PATH`をそのローカルディレクトリ
  に向けて同じ`download_model_weights.py`的な手順（または直接ファイル配置）で
  同梱し直す必要がある。

---
最終更新: 2026-08-02
