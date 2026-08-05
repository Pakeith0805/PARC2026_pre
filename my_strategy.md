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

## 方針5: lerobotをPython 3.10で入る0.4.4に固定する（2026-08-04決定）

実際に採点環境へ提出したところ、`lerobot==0.6.0`が見つからずインストールに
失敗して0点になった（採点ログ: `Could not find a version that satisfies the
requirement lerobot==0.6.0`）。原因は採点環境がPython 3.10.12で、
`lerobot>=0.5.0`は`requires-python>=3.12`のためそもそもpip installできない
という、examples/のColabノートブック（Python 3.12前提）と本番環境のPython版
のズレだった。対応として`lerobot[smolvla]==0.4.4`（Python 3.10で入る最新版）
に切り替えることを決定。

- **なぜ0.4.4で大丈夫と判断したか**: 単にバージョンを下げただけでなく、
  実際にPython 3.10 + lerobot 0.4.4の環境を作り、`lerobot/smolvla_libero_plus`
  チェックポイントを実際にロード・推論させて動作確認した（`.local_libs/verify/
  venv_py310_check/`）。0.4.4にも`SmolVLAPolicy`・processor pipeline
  （`rename_observations_processor`等の同じレジストリ名）が既にあり、
  チェックポイントの`config.json`もそのまま読めた。`validate_submission.py`の
  静的・動的チェック（zip展開→サーバー起動→`/health`→`/reset`→`/act`）も
  この環境でPASS（errors=0）を確認済み。
- **importパスの差分**: `from lerobot.configs import PreTrainedConfig`は
  0.6.0では通るが0.4.4には無い（`lerobot.configs.policies`に置き換え）。
  `policy_server.py`はこちらに合わせて修正済み。
- **requirements.txtからtorch/huggingface_hubの明示指定を外した**: 採点環境の
  提出物用venvは`--system-site-packages`付きで作られ、書かなかったライブラリは
  プリインストール版（`torch==2.11.0+cu130`等）がそのまま使われる
  （README.mdの「採点環境」節に明記）。`lerobot==0.4.4`自体が`torch<2.11.0`を
  要求するため、この行を足すとpipがCUDA12系torchへ巻き戻すが、これは想定内の
  挙動としてREADME.mdに書かれている。
- **一次情報の出どころ**: 採点環境の正確な構成（Python版・torch版・
  `--system-site-packages`・プリインストール一覧）は、ユーザーが実際の採点
  ログと、配布環境の更新版README（採点環境節が追記された版。現在は`README.md`本体に取り込み済み）
  を共有してくれたことで判明した。以前の`overview.md`/`competition_analysis.md`
  の記述はこの情報が無い時点のものだったため、あわせて更新した。
- **含意**: 今後`examples/`のColabノートブックでLoRA学習する際も、学習は
  Python 3.12のColab環境で行って構わない（採点環境とは無関係）が、
  **マージ後の推論コード（`policy_server.py`）は必ずPython 3.10 + lerobot 0.4.4
  で動作確認してから提出すること**。ローカル検証を3.12環境だけで済ませると
  この非互換に気づけない。

## 方針6: lerobotをpipインストールせず、ソースをvendor同梱する（2026-08-04決定）

方針5でlerobotをPython 3.10対応の0.4.4に切り替えて再提出したところ、今度は
別のエラーで0点になった（`evdev`のビルド失敗、`fatal error: Python.h: No
such file or directory`）。実機検証をやり直し、「そうしよう」で対応を決定。

- **原因**: lerobotが`pynput>=1.7.7,<1.9.0`を（smolvla extraとは無関係に）
  無条件の必須依存として宣言している。`pynput`はLinuxで`evdev`を要求するが、
  `evdev`はPyPIに一度もwheelを公開したことがなく常にソースビルドが必要。
  採点環境にはPythonヘッダー（`Python.h`）が無く、ビルドが失敗する。
  0.3.x〜0.4.4のどのバージョンでも同じ依存宣言があり、バージョンを変えても
  回避できないことを確認した。
- **pynput/evdevは実際には一切使われていない**: `pynput`はゲームパッド等の
  入力デバイス制御用（lerobotの実機テレオペ機能向け）で、SmolVLAの推論に
  使う`lerobot.configs.policies` / `lerobot.policies.factory` /
  `lerobot.policies.smolvla.*`のimportチェーンには一度も出てこないことを、
  実際にpynput/evdevを削除した状態で動作確認して確かめた。
- **requirements.txt経由の回避策はすべて塞がれている**: ローカルの`.whl`を
  同梱して相対パスで参照する、`file://`で参照する、`--find-links`で
  ローカルディレクトリを指す、いずれも`validate_submission.py`の静的検査
  （`req.local_path`・`req.external_url`）で明示的に拒否される
  （「setup.pyがinstall時に実行される」ためのセキュリティ対策）。
- **対応**: `lerobot`パッケージ自体をpipインストールするのをやめ、ソース一式
  （v0.4.4のPyPI版と実質同一。非Pythonファイルの差分のみ実機で確認済み）を
  `submission_template/vendor/lerobot/`に同梱し、`policy_server.py`の
  `MyPolicy.__init__`が`sys.path`に追加してから`import`する方式にした。
  これで`pynput`はそもそも要求されなくなる。
- **vendorしたことで必要になった実際の依存**: `lerobot.policies`パッケージの
  `__init__.py`が全ポリシー種別（groot, pi0等）を無条件にimportする作りに
  なっており、`groot`経由で`lerobot.robots`/`lerobot.motors`
  （`pyserial`要求）まで芋づる式に読み込まれることが分かった。ただし
  `pyserial`・`deepdiff`・`av`・`gymnasium`・`datasets`・`diffusers`・
  `draccus`等はいずれも通常にwheelがありビルド不要だったため、これらは
  素直に`requirements.txt`に追加する方針にした（lerobotの内部構造を
  patchするより安全）。1つずつ実機（Python 3.10のクリーンなvenv）で
  importエラーを解消しては次のエラーを見る、という手順で必要な依存を
  確定させた。最終的な一覧は`requirements.txt`のコメント参照。
- **検証**: 採点環境のプリインストール状態を模した`--system-site-packages`
  相当のvenvで、素の`pip install -r requirements.txt`（pip 26.1.2）が
  警告なしで完了し、`evdev`/`pynput`が一切インストールされないこと、
  `MyPolicy`のロード・推論、`validate_submission.py`の静的・動的チェック
  （zip展開込み）が全てPASSすることを確認した。
- **含意**: LoRA学習後にモデル重みを差し替える際も、`vendor/lerobot/`は
  そのまま（コード側の変更ではないため）でよい。lerobotのバージョンを
  変える場合は`vendor/lerobot/`の中身と`requirements.txt`の両方を
  合わせて更新する必要がある。

## 方針7: HFキャッシュの場所を環境変数の`setdefault`でなく上書き＋直接指定で決める（2026-08-06決定）

方針6のvendor化で3回目の提出をしたところ、今度はポリシーサーバーの起動自体が
失敗して0点になった（`LocalEntryNotFoundError`、`submission_smolvla_base_
2026-08-04.zip`）。原因を特定して対処することにした。

- **原因**: `policy_server.py`が`os.environ.setdefault("HF_HOME", ...)`で
  同梱キャッシュを指していた。採点環境は参加者サーバーを`nobody`ユーザーの
  サンドボックスで起動する都合上、`HF_HOME`を**あらかじめ独自の値で設定して
  いる**。`setdefault`は既存値があると何もしないため同梱キャッシュが無視され、
  `HF_HUB_OFFLINE=1`と相まって即死した。提出zipにキャッシュ425ファイルは
  正しく入っていたので、「入れ忘れ」ではなく「見に行っていない」問題だった。
- **対応**:
  1. `setdefault`をやめて上書き代入にする。`HF_HUB_CACHE`は`HF_HOME`より
     優先されるため、両方を明示的に設定する（`TRANSFORMERS_OFFLINE`も）。
  2. さらに保険として、`snapshot_download()`を経由せず同梱スナップショットの
     パス（`hf_cache/hub/models--<repo>/snapshots/<revision>`）を直接指す分岐を
     追加する。これでHFの環境変数解決に一切依存しなくなる。
- **検証**: `HF_HOME`/`HF_HUB_CACHE`を偽のパスに、`HF_HUB_OFFLINE=1`にした
  状態（＝本番と同じ敵対的条件）で、提出zipを展開したものから直接ロード・
  推論できることを確認した。ロード10.5秒、1推論0.31秒。
- **結果**: この修正で**初めて採点が完走した**
  （`submission_smolvla_base_2026-08-06.zip`、起動36秒）。ただしスコアは0点で、
  それは別の原因だった（方針8）。
- **含意**: 採点環境が設定済みの環境変数を「尊重」してはいけない。同梱リソースを
  確実に使わせたい箇所は、環境変数ではなくパスで直接指定する。

## 方針8: `n_action_steps`を50から10に下げる（2026-08-06決定）

方針7で採点は完走したが0点だった。サーバーログを解析すると8エピソード
すべてがぴったり300ステップ（`max_steps`）で終わっており、`done`が一度も
立っていない＝ゴールに一度も到達していないと分かった。実装バグを5点検証して
すべてシロだったため、推論時パラメータを疑って切り分けることにした。

- **原因**: checkpointの`n_action_steps`が**50**。20Hz換算で2.5秒間、観測を
  一切見ずにアクションチャンクを流し切る設定で、学習時256×256に対し採点環境は
  128×128であるため、解像度低下で生じた誤差が開ループ中に増幅して破綻していた。
- **測定**（素のlibero_object 10タスク、128px、300ステップ上限）:
  n=50で10%、n=10で**90%**。256px/n=50でも30%しか出ず、
  **低解像度そのものより「低解像度 × 長い開ループ」の組み合わせ**が効いていた。
- **本番相当のT1 exampleタスク**（4タスク×5エピソード、128px）: 0.0% → **70.0%**。
- **n=10を採用した理由**: n=5も試したが66.7%で頭打ちで、推論回数だけ倍になる。
  n=10ならレイテンシは`/act`最大0.111秒（10秒制限に対し90倍の余裕）で済む。
- **実装**: `SMOLVLA_N_ACTION_STEPS`環境変数で上書き可能にし、既定値を10とした
  （0を指定するとcheckpointの値をそのまま使う）。
- **含意**: 重みを疑う前に「摂動なしの素のLIBEROで動くか」を切り分けると原因の
  所在が一発で分かる。この切り分けは`src/eval_vanilla_libero.py`で常時再現できる
  ようにした。LoRA学習後もこのnの値は再評価すること（学習時の解像度を採点環境と
  揃えれば、より大きなnでも成立する可能性がある）。

---
最終更新: 2026-08-06
