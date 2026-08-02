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

## 方針2: タスク2をholdoutし、汎化性能の検証専用に使う（2026-08-02決定）

Track1 exampleの4タスクのうち、`pick_up_the_tomato_sauce_and_place_it_in_the_
basket_table_27`（`libero_object`、難易度L5）を学習データから除外し、学習後の
汎化性能を確認するための検証専用タスクとして使う。

- **なぜこのタスクか**: 4タスクは`libero_spatial`×1、`libero_object`×2、
  `libero_goal`×1という構成（[competition_analysis.md](competition_analysis.md)
  の「Track1 exampleタスク4種、全件の内容」参照）。spatial/goalの唯一の
  タスクを除外すると、そのsuiteをまるごと学習データから消してしまい、
  「汎化に失敗した」のか「そもそもその種類の課題を一度も見ていない」のか
  区別がつかなくなる。`libero_object`だけ2つあるので、片方（タスク2）を
  保留すれば「同じタスク構造は学習済みだが、対象物体・難易度・摂動条件は
  未見」という狙い通りの汎化テストになる。
- **なぜタスク2（L5、難）でありタスク3（L2、易）でないか**: 易しい方
  （タスク3、milk）を学習に残して基本構造を学ばせ、より厳しい摂動・未見物体を
  持つタスク2（tomato sauce）で「どれだけ厳しい条件まで汎化できるか」を測る方が
  情報量が多い。
- **留保**: 4タスクしかないため、3タスクで訓練するとそもそも学習データ量が
  少なすぎる可能性がある。この保留アプローチは「動くかどうかの検証」には
  有効だが、本番の学習データ設計（もっと広いデータが必要になるはず）とは
  切り離して考える。

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
