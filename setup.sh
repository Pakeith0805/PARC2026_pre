#!/usr/bin/env bash
# 自己評価キットの環境構築（本番採点イメージと同じ手順をローカルに再現する）
#
#   bash setup.sh          # このディレクトリ（キットのルート）で実行
#   source env.sh          # 以後、評価を回すシェルで毎回 source する
#
# やること:
#   1. venv 作成 + 依存インストール（本番と同じピン止めバージョン）
#   2. LIBERO-plus（評価環境）と LIBERO（base assets）の取得
#   3. LIBERO-plus への既知パッチ（__init__.py 追加 / torch.load weights_only）
#   4. タスクアセットのダウンロードと配線（HF assets.zip）
#   5. ~/.libero/config.yaml の生成（既存があれば .bak に退避）
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
ROOT="$PWD"

PY="${PYTHON:-python3.10}"
USE_UV=0
command -v uv >/dev/null 2>&1 && USE_UV=1

echo "[setup] 1/5 venv + 依存"
if [ "$USE_UV" = "1" ]; then
    echo "[setup]   uv を検出 -> uv でセットアップ（sudo / system python3.10 不要）"
    if [ ! -d venv ]; then
        uv venv --python 3.10 venv
    fi
    # shellcheck disable=SC1091
    source venv/bin/activate
    # GPU で推論する提出物を作る場合も、評価環境自体は CPU torch で足りる
    uv pip install --index-strategy unsafe-best-match \
        "torch==2.11.0+cpu" --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple
    uv pip install \
        mujoco==3.7.0 robosuite==1.4.0 numpy==1.26.4 "gym==0.25.2" bddl==3.6.0 \
        cloudpickle==3.1.2 easydict==1.13 hydra-core==1.3.2 einops==0.8.2 \
        opencv-python-headless==4.11.0.86 \
        scipy pyyaml h5py Pillow termcolor tqdm matplotlib \
        requests msgpack fastapi uvicorn huggingface_hub wand scikit-image pytest
else
    if [ ! -d venv ]; then
        "$PY" -m venv venv
    fi
    # shellcheck disable=SC1091
    source venv/bin/activate
    pip install --upgrade pip setuptools wheel -q
    # GPU で推論する提出物を作る場合も、評価環境自体は CPU torch で足りる
    pip install -q --timeout 120 --retries 10 \
        "torch==2.11.0+cpu" --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple
    pip install -q --timeout 120 \
        mujoco==3.7.0 robosuite==1.4.0 numpy==1.26.4 "gym==0.25.2" bddl==3.6.0 \
        cloudpickle==3.1.2 easydict==1.13 hydra-core==1.3.2 einops==0.8.2 \
        opencv-python-headless==4.11.0.86 \
        scipy pyyaml h5py Pillow termcolor tqdm matplotlib \
        requests msgpack fastapi uvicorn huggingface_hub wand scikit-image pytest
fi

echo "[setup] 2/5 LIBERO-plus / LIBERO の取得"
if [ ! -d LIBERO-plus ]; then
    git clone --depth 1 https://github.com/sylvestf/LIBERO-plus
fi
if [ ! -d LIBERO ]; then
    git clone --depth 1 https://github.com/Lifelong-Robot-Learning/LIBERO
fi

echo "[setup] 3/5 LIBERO-plus パッチ"
touch LIBERO-plus/libero/__init__.py LIBERO-plus/libero/libero/__init__.py
sed -i 's/torch.load(init_states_path)/torch.load(init_states_path, weights_only=False)/' \
    LIBERO-plus/libero/libero/benchmark/__init__.py || true

echo "[setup] 4/5 アセット"
ASSETS="LIBERO-plus/libero/libero/assets"
if [ "$(ls "$ASSETS"/textures 2>/dev/null | wc -l)" -lt 100 ]; then
    python -c "from huggingface_hub import hf_hub_download; hf_hub_download('Sylvest/LIBERO-plus','assets.zip',repo_type='dataset',local_dir='.tmp_assets')"
    unzip -q .tmp_assets/assets.zip -d LIBERO-plus/libero/libero
    rm -rf .tmp_assets
    # assets.zip は作者環境の深いネストパスごと展開されることがあるため対応する
    if [ "$(ls "$ASSETS"/textures 2>/dev/null | wc -l)" -lt 100 ]; then
        rm -rf "$ASSETS"
        NESTED="$(find LIBERO-plus/libero/libero -type d -path '*/assets' -name assets | grep -v '^LIBERO-plus/libero/libero/assets$' | head -1)"
        test -n "$NESTED" && ln -sfn "$(realpath "$NESTED")" "$ASSETS"
    fi
fi
test -e "$ASSETS/scenes/libero_floor_base_style.xml"
echo "[setup]   textures=$(ls "$ASSETS"/textures | wc -l)"

echo "[setup] 5/5 libero 設定"
mkdir -p "$HOME/.libero"
if [ -f "$HOME/.libero/config.yaml" ]; then
    cp "$HOME/.libero/config.yaml" "$HOME/.libero/config.yaml.bak"
    echo "[setup]   既存の ~/.libero/config.yaml を config.yaml.bak に退避しました"
fi
cat > "$HOME/.libero/config.yaml" <<EOF
benchmark_root: $ROOT/LIBERO-plus/libero/libero
bddl_files: $ROOT/LIBERO-plus/libero/libero/bddl_files
init_states: $ROOT/LIBERO-plus/libero/libero/init_files
datasets: $ROOT/LIBERO-plus/libero/libero/datasets
assets: $ROOT/LIBERO/libero/libero/assets
EOF

GL_EXPORTS=""
if [ "$USE_UV" = "1" ]; then
    # sudo が使えないローカル環境向け: libosmesa6 を apt install せず
    # 既存の Mesa EGL/DRI で headless レンダリングできるか試し、駄目なら
    # apt-get download + dpkg -x でユーザ領域にネイティブライブラリを用意する
    LOCAL_LIBS="$ROOT/.local_libs"
    NEED_LOCAL_LIBS=0
    fetch_debs() {
        mkdir -p "$LOCAL_LIBS" .tmp_deb
        (cd .tmp_deb && apt-get download "$@")
        for deb in .tmp_deb/*.deb; do dpkg-deb -x "$deb" "$LOCAL_LIBS"; done
        rm -rf .tmp_deb
    }

    echo "[setup]   GL バックエンド判定（sudo 不要な MUJOCO_GL を選定）"
    if MUJOCO_GL=egl python -c "
import mujoco
m = mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom type=\"plane\" size=\"1 1 0.1\"/></worldbody></mujoco>')
r = mujoco.Renderer(m); r.render()
" >/dev/null 2>&1; then
        echo "[setup]     MUJOCO_GL=egl で動作確認OK"
        GL_EXPORTS='export MUJOCO_GL=egl'
    else
        echo "[setup]     egl 失敗 -> libosmesa6 をユーザ領域に取得します"
        fetch_debs libosmesa6
        NEED_LOCAL_LIBS=1
        GL_EXPORTS='export MUJOCO_GL=osmesa'
    fi

    echo "[setup]   wand(MagickWand) 動作確認"
    if ! python -c "import wand.image" >/dev/null 2>&1; then
        echo "[setup]     MagickWand をユーザ領域に取得します"
        fetch_debs imagemagick-6-common libmagickcore-6.q16-7t64 libmagickwand-6.q16-7t64 \
            libfftw3-double3 liblqr-1-0 libraw23t64
        NEED_LOCAL_LIBS=1
        export LD_LIBRARY_PATH="$LOCAL_LIBS/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
        # wand は soname 無しの libMagickWand-6.Q16.so を MAGICK_HOME/lib 配下に探すが、
        # apt のランタイムパッケージには libMagickWand-6.Q16.so.7 しか入っていないため
        # wand が認識できる名前でシンボリックリンクを張る
        MAGICK_HOME_DIR="$LOCAL_LIBS/magick_home"
        mkdir -p "$MAGICK_HOME_DIR/lib"
        for f in "$LOCAL_LIBS"/usr/lib/*/libMagickWand*.so.[0-9]* "$LOCAL_LIBS"/usr/lib/*/libMagickCore*.so.[0-9]*; do
            [ -e "$f" ] || continue
            base="$(basename "$f")"
            ln -sf "$f" "$MAGICK_HOME_DIR/lib/${base%.so.*}.so"
        done
        export MAGICK_HOME="$MAGICK_HOME_DIR"
        if ! python -c "import wand.image" >/dev/null 2>&1; then
            echo "[setup]     警告: MagickWand の読み込みに失敗しました（wand を使う箇所は動かない可能性があります）"
        else
            echo "[setup]     MagickWand 読み込みOK"
        fi
    fi

    if [ "$NEED_LOCAL_LIBS" = "1" ]; then
        GL_EXPORTS="$GL_EXPORTS
export LD_LIBRARY_PATH=\"$LOCAL_LIBS/usr/lib/x86_64-linux-gnu:\${LD_LIBRARY_PATH:-}\""
    fi
    if [ -n "${MAGICK_HOME:-}" ]; then
        GL_EXPORTS="$GL_EXPORTS
export MAGICK_HOME=\"$MAGICK_HOME\""
    fi
fi

cat > env.sh <<EOF
source "$ROOT/venv/bin/activate"
export PYTHONPATH="$ROOT/LIBERO-plus:$ROOT:$ROOT/compe"
export LIBERO_ROOT="$ROOT/LIBERO-plus"
$GL_EXPORTS
EOF

echo "[setup] 動作確認（suite 登録）"
PYTHONPATH="$ROOT/LIBERO-plus:$ROOT:$ROOT/compe" \
    python -c "import libero.libero.benchmark; from compe.t1 import register_t1; register_t1(); print('suite 登録 OK')"

echo
echo "セットアップ完了。評価を回すシェルで次を実行してください:"
echo "  source env.sh"
