#!/bin/bash
# IS計算サーバーでsmolvla_parc_lora.ipynbを非対話実行するsbatchスクリプト。
#
# 前提:
# - リポジトリを ~/Projects/PARC2026_pre にclone済み、.venv_trainを構築済み
#   （examples/smolvla_parc_lora_requirements_freeze.txt / lerobot_local_patch.diff 参照）
# - smolvla_parc_lora_config.yaml の mode を full_submission にしてある
#   （holdout_evalのままだとrobosuite/MuJoCo一式のセットアップが走る）
# - HF_HOME/HF_LEROBOT_HOME 配下にモデル・データセットのキャッシュを用意済み
#
# 投入例（a100/pro_6000パーティション、num_workers=8にCPUが足りる構成を選ぶこと。
# a100_1g/a100_3gはCPU数不足＋inter/lowQoS限定のため本番学習には非推奨）:
#   sbatch -J parc_train -p pro_6000 --gres=gpu:pro_6000:1 --qos=low \
#     --cpus-per-task=16 --time=2-00:00:00 examples/is_server_train.sbatch
#
# 注意: lowQoSは中断されうるが、現状のnotebookは最終ステップでしか
# チェックポイントを保存しない（--save_freq={STEPS}）。中断されると
# それまでの進捗が失われるので、normalQoSが使えるならそちらを推奨。

#SBATCH --output=%x-%j.out
#SBATCH --open-mode=append
set -euo pipefail

echo "ジョブID: $SLURM_JOB_ID"
echo "実行ノード: $(hostname)"
echo "パーティション: $SLURM_JOB_PARTITION"
nvidia-smi -L || true

cd "$HOME/Projects/PARC2026_pre"
source .venv_train/bin/activate

export HF_HOME="$HOME/parc_lora_workspace/hf_cache"
export HF_LEROBOT_HOME="$HOME/parc_lora_workspace/lerobot_cache"
export HF_HUB_OFFLINE=1
export PARC_WORKSPACE_ROOT="$HOME/parc_lora_workspace"
export PARC_REPO_ROOT="$HOME/Projects/PARC2026_pre"
export PYTHONPATH="$HOME/lerobot_src/src:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false

jupyter nbconvert \
  --to notebook \
  --execute \
  --ExecutePreprocessor.kernel_name=parc_train \
  --ExecutePreprocessor.timeout=-1 \
  --output "smolvla_parc_lora_${SLURM_JOB_ID}.ipynb" \
  --output-dir="$HOME/parc_lora_workspace/nbconvert_out" \
  examples/smolvla_parc_lora.ipynb

echo "完了。実行済みnotebook: $HOME/parc_lora_workspace/nbconvert_out/smolvla_parc_lora_${SLURM_JOB_ID}.ipynb"
