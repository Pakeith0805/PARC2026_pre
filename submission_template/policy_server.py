"""ポリシーサーバー（提出用テンプレート）

このファイルを編集して、自分のモデルを組み込んでください。
編集が必要なのは MyPolicy クラスの中身だけです。
それ以外のコード（サーバー部分、シリアライゼーション）は変更不可です。

ローカルテスト:
    pip install -r requirements.txt
    python policy_server.py                  # サーバー起動（port 8000）

    # 別ターミナルで評価実行
    python -m pipeline --server-url http://localhost:8000 --dry-run
"""

import argparse
import os
import pathlib
from abc import ABC, abstractmethod

import msgpack
import numpy as np
import uvicorn
from fastapi import FastAPI, Request, Response


# ============================================================
# ポリシーのインターフェース定義（変更不可）
# MyPolicy が満たすべき get_action() / reset() の仕様を定める。
# ============================================================


class BasePolicy(ABC):
    """ポリシーの基底クラス。get_action() と reset() を実装してください。"""

    @abstractmethod
    def get_action(self, obs: dict[str, np.ndarray]) -> np.ndarray:
        """観測からアクションを推論する。

        Args:
            obs: 環境からの観測。以下のキーが含まれる:
                - "agentview_image": (128, 128, 3) uint8
                - "robot0_eye_in_hand_image": (128, 128, 3) uint8
                - "robot0_joint_pos": (7,) float
                - "robot0_eef_pos": (3,) float
                - "robot0_eef_quat": (4,) float
                - "robot0_gripper_qpos": (2,) float

        Returns:
            action: (7,) float32 — [dx, dy, dz, droll, dpitch, dyaw, gripper]
        """
        ...

    @abstractmethod
    def reset(self, instruction: str = "") -> None:
        """エピソード開始時に呼ばれる。内部状態をリセットしてください。

        Args:
            instruction: タスクの言語指示（例: "pick up the red mug and place it on the shelf"）
        """
        ...


# ============================================================
# ここを編集する（MyPolicy の中身だけを自分のモデルに置き換える）
# ============================================================


class MyPolicy(BasePolicy): # BasePolicyを継承
    """SmolVLA（lerobot/smolvla_libero_plus）をベースにした推論実装。

    まずは追加学習なしのベース重みで動作確認する。examples/ の LoRA 学習
    ノートブックで自分の重みを学習したら、SMOLVLA_MODEL_PATH を merge 済み
    モデルのローカルディレクトリに向ければ差し替えられる。
    """

    # 環境変数 SMOLVLA_MODEL_PATH が未設定ならベース重み（HF Hub）を使う。
    # LoRA を学習・マージした後は、そのディレクトリのパスを設定する。
    MODEL_PATH = os.environ.get("SMOLVLA_MODEL_PATH", "lerobot/smolvla_libero_plus")
    MODEL_REVISION = os.environ.get(
        "SMOLVLA_MODEL_REVISION", "7bb70aa5bc92b82c9239142775d3a173103567ff"
    )
    # 採点環境は外部通信を遮断する（README.md参照）。model_weights/hf_cache に
    # 事前ダウンロード済みのHFキャッシュを同梱しておけば、そこから完全オフラインで
    # 読み込む（src/download_model_weights.py で作成する）。同梱がなければ従来通り
    # オンラインで取得する（ローカル開発時の後方互換）。
    HF_CACHE_DIR = pathlib.Path(__file__).resolve().parent / "model_weights" / "hf_cache"
    HF_HUB_CACHE_DIR = HF_CACHE_DIR / "hub"

    # action chunk のうち何ステップを開ループで実行してから再推論するか。
    # checkpointの既定値は50だが、これは128x128の採点環境では致命的に長い
    # （50ステップ＝20Hzで2.5秒を無観測で走り切るため、チャンクが現実からずれる）。
    # ローカル実測（素のlibero_object 10タスク、128px、300ステップ上限）:
    #   n=50 → 10%、n=10 → 90%。本番相当のT1 exampleタスクでは 0% → 66.7%。
    # n=5でも66.7%で頭打ちだったため、推論回数が半分で済む10を既定とする。
    # 0を指定するとcheckpointの値をそのまま使う。
    N_ACTION_STEPS = int(os.environ.get("SMOLVLA_N_ACTION_STEPS", "10"))

    # lerobotパッケージはpipインストールしない。無条件必須依存のpynputが
    # Linuxでevdev（PyPIにwheelなし、常にソースビルドが必要）を要求し、
    # 採点環境にPythonヘッダーが無くビルドに失敗するため
    # （requirements.txtのコメント、my_strategy.md方針6参照）。
    # 代わりにソースをこのファイルと同じ階層のvendor/lerobotに同梱し、
    # sys.pathへ追加して使う。
    VENDOR_DIR = pathlib.Path(__file__).resolve().parent / "vendor"

    def __init__(self):
        import sys

        if str(self.VENDOR_DIR) not in sys.path:
            sys.path.insert(0, str(self.VENDOR_DIR))

        if self.HF_CACHE_DIR.is_dir():
            # setdefault ではなく上書きする。採点環境は HF_HOME / HF_HUB_CACHE を
            # 独自の値で設定済みで、setdefault だと同梱キャッシュが無視され、
            # かつ HF_HUB_OFFLINE=1 のため LocalEntryNotFoundError で落ちる。
            # HF_HUB_CACHE は HF_HOME より優先されるので両方明示する。
            os.environ["HF_HOME"] = str(self.HF_CACHE_DIR)
            os.environ["HF_HUB_CACHE"] = str(self.HF_HUB_CACHE_DIR)
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

        import torch
        from huggingface_hub import snapshot_download
        # lerobot 0.5+ は Python>=3.12 必須で採点環境(Python 3.10.12)では
        # pip installできないため、lerobot==0.4.4 を使う前提のimportパスにしている
        # （`from lerobot.configs import PreTrainedConfig` は0.4.4には無い）。
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.policies.factory import make_pre_post_processors
        from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

        # もしMODEL_PATHがローカルディレクトリならそのまま使う。
        # 次に同梱キャッシュ内のスナップショットを直接指す（HFの環境変数解決に
        # 依存せずオフラインで確実に解決するため）。どちらも無ければダウンロード。
        bundled_snapshot = (
            self.HF_HUB_CACHE_DIR
            / f"models--{self.MODEL_PATH.replace('/', '--')}"
            / "snapshots"
            / self.MODEL_REVISION
        )
        if os.path.isdir(self.MODEL_PATH):
            model_dir = self.MODEL_PATH
        elif bundled_snapshot.is_dir():
            model_dir = str(bundled_snapshot)
        else:
            model_dir = snapshot_download(
                repo_id=self.MODEL_PATH,
                revision=self.MODEL_REVISION,
                token=False,
                allow_patterns=[
                    "config.json",
                    "model.safetensors",
                    "train_config.json",
                    "policy_preprocessor.json",
                    "policy_preprocessor*.safetensors",
                    "policy_postprocessor.json",
                    "policy_postprocessor*.safetensors",
                ],
            )

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        # configを読み込み
        config = PreTrainedConfig.from_pretrained(model_dir)
        config.device = str(self.device)
        # VLM の初期重みを別途HFから読み直させない（すぐ後で checkpoint 全体の
        # state_dict をロードするので二度手間になり、起動タイムアウト(120秒)を
        # 圧迫する。examples/ のノートブックも merge 後の推論ではこれを false にしている）。
        config.load_vlm_weights = False
        if self.N_ACTION_STEPS:
            config.n_action_steps = self.N_ACTION_STEPS

        # ロード・デバイスへの転送・推論モードに
        self.policy = SmolVLAPolicy.from_pretrained(model_dir, config=config, strict=False)
        self.policy.to(self.device)
        self.policy.eval()

        # 観測データをモデル入力形式に、出力をactionに変換。前処理はデバイスに、後処理はCPUに固定。こうすることで、オーバーヘッドが減るらしい。
        self.preprocessor, self.postprocessor = make_pre_post_processors(
            policy_cfg=config,
            pretrained_path=model_dir,
            preprocessor_overrides={"device_processor": {"device": str(self.device)}},
            postprocessor_overrides={"device_processor": {"device": "cpu"}},
        )

        # 現在のタスク言語指示を処理するインスタンス変数を初期化(reset()で更新)
        self.instruction = ""

    def get_action(self, obs: dict[str, np.ndarray]) -> np.ndarray:
        import torch
        from lerobot.policies.utils import prepare_observation_for_inference

        # 環境から渡されたカメラ映像を学習データの向きに合わせる
        raw_obs = {
            # 学習データ（HuggingFaceVLA/libero 由来）と向きを揃えるため180度回転させる。
            "observation.images.front": np.ascontiguousarray(obs["agentview_image"][::-1, ::-1, :]),
            "observation.images.wrist": np.ascontiguousarray(
                obs["robot0_eye_in_hand_image"][::-1, ::-1, :]
            ),
            "observation.state": np.concatenate(
                [
                    obs["robot0_eef_pos"].astype(np.float32),
                    _quat_to_axis_angle(obs["robot0_eef_quat"]),
                    obs["robot0_gripper_qpos"].astype(np.float32),
                ]
            ).astype(np.float32),
        }

        # 推論モードにして、バッチ化→前処理→アクション選択→後処理
        with torch.inference_mode():
            batch = prepare_observation_for_inference(raw_obs, self.device, task=self.instruction)
            batch = self.preprocessor(batch)
            action = self.policy.select_action(batch)
            action = self.postprocessor(action)

        # 7次元actionベクトルを返す
        return action[0].detach().cpu().numpy().astype(np.float32)

    def reset(self, instruction: str = "") -> None:
        # instruction にはタスクの言語指示が渡される
        self.instruction = instruction
        # action chunking 用の内部キューをクリアする
        self.policy.reset()


def _quat_to_axis_angle(quat: np.ndarray) -> np.ndarray:
    """xyzw 順の quaternion を axis-angle (3,) に変換する。

    LeRobot の LiberoProcessorStep._quat2axisangle と同じ変換を numpy で再現。
    """
    x, y, z, w = (float(v) for v in quat)
    w = max(-1.0, min(1.0, w))
    den = (1.0 - w * w) ** 0.5
    if den < 1e-10:
        return np.zeros(3, dtype=np.float32)
    angle = 2.0 * np.arccos(w)
    axis = np.array([x, y, z], dtype=np.float64) / den
    return (axis * angle).astype(np.float32)


# ============================================================
# 以下は変更不可
# ============================================================


def deserialize_obs(data: bytes) -> dict[str, np.ndarray]:
    unpacked = msgpack.unpackb(data, raw=False)
    obs = {}
    for key, val in unpacked.items():
        arr = np.frombuffer(val["data"], dtype=np.dtype(val["dtype"]))
        obs[key] = arr.reshape(val["shape"]).copy()
    return obs


def serialize_action(action: np.ndarray) -> bytes:
    return msgpack.packb(
        {"data": action.astype(np.float32).tobytes()},
        use_bin_type=True,
    )


app = FastAPI(title="VLA Policy Server")
_policy: BasePolicy | None = None


def set_policy(policy: BasePolicy) -> None:
    global _policy
    _policy = policy


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/reset")
async def reset_policy(request: Request):
    body = await request.body()
    instruction = ""
    if body:
        import json
        data = json.loads(body)
        instruction = data.get("instruction", "")
    _policy.reset(instruction=instruction)
    return {"status": "ok"}


@app.post("/act")
async def act(request: Request):
    body = await request.body()
    obs = deserialize_obs(body)
    action = _policy.get_action(obs)
    return Response(
        content=serialize_action(action),
        media_type="application/x-msgpack",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    set_policy(MyPolicy())
    print(f"Policy server starting on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
