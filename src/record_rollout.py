"""ポリシーサーバーをLIBERO環境で実際に動かし、成功率と動画を記録するツール。

pipeline/rollout.py の _run_episode と同じロジック（init_stateの当て方、
collisionによる成功判定）を踏襲しつつ、agentview_image を毎ステップ記録して
動画化する点だけを追加している。pipeline/ 本体は一切変更しない（読み取り専用
で部品を再利用するだけ）。

前提: 評価対象のポリシーは submission_template/policy_server.py と同じ
HTTPインターフェース（/health, /reset, /act）で別プロセスとして起動しておく。
使い方は README.md 参照。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def save_video(frames: list[np.ndarray], path: Path, fps: int) -> None:
    # cv2.VideoWriterの既定コーデック(mp4v = MPEG-4 Part 2)はブラウザの<video>タグで
    # 再生できないため、imageio-ffmpeg経由でH.264(avc1)で書き出す。
    import imageio.v2 as imageio

    writer = imageio.get_writer(
        str(path),
        format="FFMPEG",
        fps=fps,
        codec="libx264",
        pixelformat="yuv420p",
        macro_block_size=1,
    )
    for frame in frames:
        writer.append_data(frame)
    writer.close()


def run_episode(
    env,
    policy,
    task_info,
    init_state: np.ndarray,
    episode_id: int,
    seed: int,
    scoring_config: dict,
    obj_of_interest: set[str],
    max_steps: int,
    record: bool,
) -> tuple[bool, int, list[np.ndarray]]:
    cc = scoring_config.get("collision", {})
    collision_enabled = bool(cc.get("enabled", True))
    collision_threshold = float(cc.get("threshold_m", 0.001))

    env.reset()
    env.sim.set_state_from_flattened(init_state)
    env.sim.forward()

    action_dim = env.robots[0].action_dim
    dummy_action = np.zeros(action_dim)
    for _ in range(10):
        obs, _, _, _ = env.step(dummy_action)

    object_init_pos: dict[str, np.ndarray] = {}
    if collision_enabled:
        object_init_pos = {
            k[:-4]: np.asarray(obs[k]).copy()
            for k in obs
            if k.endswith("_pos")
            and not k.startswith("robot0")
            and not k.endswith("_to_robot0_eef_pos")
            and k[:-4] not in obj_of_interest
        }
    object_max_disp: dict[str, float] = {}

    frames: list[np.ndarray] = []
    if record:
        # LeRobotのLiberoEnv.render()と同じ向き（180度回転）で見やすくする
        frames.append(obs["agentview_image"][::-1, ::-1])

    policy.reset(instruction=task_info.language, seed=seed)
    done = False
    total_steps = 0

    for step in range(max_steps):
        action = policy.get_action(obs)
        obs, reward, done, info = env.step(action)

        if record:
            frames.append(obs["agentview_image"][::-1, ::-1])

        for name, p0 in object_init_pos.items():
            cur = obs.get(name + "_pos")
            if cur is not None:
                d = float(np.sum(np.abs(np.asarray(cur) - p0)))
                if d > object_max_disp.get(name, 0.0):
                    object_max_disp[name] = d

        total_steps = step + 1
        if done:
            break

    collided = any(d > collision_threshold for d in object_max_disp.values())
    success = bool(done) and not collided
    return success, total_steps, frames


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "ポリシーサーバーをLIBERO環境で動かし、成功率と動画(mp4)を記録する。"
            "実行前にポリシーサーバー(policy_server.py互換)を別プロセスで起動しておくこと。"
        )
    )
    parser.add_argument(
        "--server-url",
        default="http://localhost:8000",
        help="ポリシーサーバーのURL（デフォルト: policy_server.pyのデフォルトポート）",
    )
    parser.add_argument(
        "--benchmark",
        default="libero_t1",
        help="評価するLIBEROベンチマーク名（デフォルト: compe/t1のexampleタスク一式）",
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=None,
        metavar="TASK_ID",
        help="タスクIDを指定して絞り込む（省略時はベンチマーク内の全タスク）",
    )
    parser.add_argument("--episodes", type=int, default=3, help="タスクあたりの実行エピソード数")
    parser.add_argument(
        "--record-episodes",
        type=int,
        default=1,
        help="先頭何エピソード分を録画するか（残りは成功率の集計だけ行う）",
    )
    parser.add_argument("--max-steps", type=int, default=300, help="エピソードあたりの最大ステップ数")
    parser.add_argument(
        "--camera-size",
        type=int,
        default=256,
        help="レンダリング解像度（正方形、片辺のpx）。本番の採点は128固定だが、"
        "動画確認用には256程度が見やすい",
    )
    parser.add_argument("--fps", type=int, default=20, help="出力動画のfps（control_freqに合わせる）")
    parser.add_argument("--seed", type=int, default=42, help="エピソード初期化の基準シード")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_REPO_ROOT / "results" / "rollout_videos",
        help="動画・結果の出力先ディレクトリ",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # EvalConfigのcamera_height/widthはimport時に環境変数から決まる（dataclassの
    # デフォルト値評価がモジュールロード時に走るため）。CLI引数を反映させるには
    # pipeline系のimportより前に環境変数をセットする必要がある。
    os.environ["LIBERO_EVAL_CAMERA"] = str(args.camera_size)

    from pipeline.config import EvalConfig, PerturbationConfig
    from pipeline.environment import EnvironmentManager
    from pipeline.remote_policy import RemotePolicyClient
    from pipeline.total_score import load_scoring_config

    config = EvalConfig(
        n_eval_episodes=args.episodes,
        max_steps_per_episode=args.max_steps,
        benchmark_name=args.benchmark,
        seed=args.seed,
    )
    print(f"camera resolution: {config.camera_height}x{config.camera_width}")
    print(f"MUJOCO_GL={os.environ.get('MUJOCO_GL', '(未設定)')}")

    env_manager = EnvironmentManager(config)
    task_infos = env_manager.get_task_infos(args.benchmark)
    if args.tasks:
        task_infos = [t for t in task_infos if t.name in args.tasks]
        if not task_infos:
            available = [t.name for t in env_manager.get_task_infos(args.benchmark)]
            raise SystemExit(
                f"--tasks で指定したタスクが見つかりません。利用可能なタスク:\n"
                + "\n".join(f"  {n}" for n in available)
            )

    scoring_config = load_scoring_config()

    client = RemotePolicyClient(server_url=args.server_url, timeout_sec=10.0)
    client.wait_for_server()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    for task_info in task_infos:
        print(f"\n=== task: {task_info.name} ===")
        print(f"instruction: {task_info.language}")
        env = env_manager.create_env(task_info)
        obj_of_interest = env_manager.get_obj_of_interest(task_info)
        init_states = env_manager.get_perturbed_init_states(
            task_info, PerturbationConfig(), args.episodes
        )
        successes = []
        try:
            for ep in range(args.episodes):
                record = ep < args.record_episodes
                t0 = time.time()
                success, steps, frames = run_episode(
                    env,
                    client,
                    task_info,
                    init_states[ep],
                    ep,
                    args.seed + ep,
                    scoring_config,
                    obj_of_interest,
                    args.max_steps,
                    record,
                )
                dt = time.time() - t0
                successes.append(success)
                print(f"  ep{ep}: success={success} steps={steps} elapsed={dt:.1f}s")
                if record and frames:
                    tag = "success" if success else "fail"
                    video_path = out_dir / f"{task_info.name}_ep{ep}_{tag}.mp4"
                    save_video(frames, video_path, fps=args.fps)
                    print(f"    -> saved {video_path} ({len(frames)} frames)")
        finally:
            env.close()
        rate = sum(successes) / len(successes) if successes else 0.0
        summary.append((task_info.name, rate, len(successes)))

    print("\n=== SUMMARY ===")
    for name, rate, n in summary:
        print(f"{name}: {rate:.1%} ({n} episodes)")
    if summary:
        # pipeline/scorer.py と同じ「タスク平均」で総合スコアを出す
        overall = sum(r for _, r, _ in summary) / len(summary)
        print(f"overall (task平均): {overall:.1%}")


if __name__ == "__main__":
    main()
