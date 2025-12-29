#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BACKEND_DIR="$ROOT_DIR/desktop/backend"
BUILD_VENV="$BACKEND_DIR/.venv-build"
PYENV_ROOT="$BACKEND_DIR/.pyenv"

REQUIRES_PYTHON=$(awk -F\" '/^requires-python/ {print $2}' "$ROOT_DIR/pyproject.toml" 2>/dev/null || true)
REQUIRED_PYTHON=${REQUIRES_PYTHON#">="}
REQUIRED_PYTHON=${REQUIRED_PYTHON%%,*}
REQUIRED_PYTHON=${REQUIRED_PYTHON:-"3.12"}
REQ_MAJOR=${REQUIRED_PYTHON%%.*}
REQ_MINOR=${REQUIRED_PYTHON#*.}
REQ_MINOR=${REQ_MINOR%%.*}

check_python_version() {
  "$1" -c "import sys; raise SystemExit(0 if sys.version_info >= (${REQ_MAJOR}, ${REQ_MINOR}) else 1)"
}

check_python_shared() {
  "$1" -c "import sysconfig; raise SystemExit(0 if sysconfig.get_config_var('Py_ENABLE_SHARED') else 1)"
}

ensure_pyenv() {
  if [[ -x "$PYENV_ROOT/bin/pyenv" ]]; then
    return 0
  fi
  if ! command -v git >/dev/null 2>&1; then
    echo "Missing git to install pyenv."
    exit 1
  fi
  git clone https://github.com/pyenv/pyenv.git "$PYENV_ROOT"
}

resolve_pyenv_version() {
  export PYENV_ROOT
  export PATH="$PYENV_ROOT/bin:$PATH"
  local prefix="$REQUIRED_PYTHON"
  local latest
  latest=$("$PYENV_ROOT/bin/pyenv" install --list | awk -v p="^\\s*${prefix}\\.[0-9]+$" '$0 ~ p {print $1}' | tail -1)
  if [[ -z "$latest" ]]; then
    latest="${prefix}.0"
  fi
  echo "$latest"
}

install_pyenv_python() {
  ensure_pyenv

  export PYENV_ROOT
  export PATH="$PYENV_ROOT/bin:$PATH"
  local version
  version=$(resolve_pyenv_version)
  local candidate="$PYENV_ROOT/versions/$version/bin/python"

  if [[ -x "$candidate" ]]; then
    echo "$candidate"
    return 0
  fi

  if ! command -v gcc >/dev/null 2>&1 || ! command -v make >/dev/null 2>&1; then
    echo "Missing build tools for compiling Python with shared libs."
    echo "Install build deps first (Debian/Ubuntu example):"
    echo "  sudo apt-get update && sudo apt-get install -y \\"
    echo "    build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev \\"
    echo "    libsqlite3-dev libffi-dev liblzma-dev tk-dev uuid-dev"
    exit 1
  fi
  if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    echo "Missing curl or wget required for downloading Python sources."
    exit 1
  fi

  PYTHON_CONFIGURE_OPTS="--enable-shared" PYTHON_BUILD_ENABLE_SHARED=1 \
    "$PYENV_ROOT/bin/pyenv" install "$version"

  if [[ ! -x "$candidate" ]]; then
    echo "Failed to install Python $version via pyenv."
    exit 1
  fi

  echo "$candidate"
}

resolve_python() {
  local candidate=""

  if [[ -n "${PYTHON:-}" ]]; then
    candidate="$PYTHON"
  fi

  if [[ -n "$candidate" && ! -x "$candidate" ]]; then
    candidate=""
  fi

  if [[ -n "$candidate" ]] && ! check_python_version "$candidate"; then
    candidate=""
  fi

  if [[ -n "$candidate" ]] && ! check_python_shared "$candidate"; then
    candidate=""
  fi

  if [[ -z "$candidate" ]] && command -v "python$REQUIRED_PYTHON" >/dev/null 2>&1; then
    candidate=$(command -v "python$REQUIRED_PYTHON")
    if ! check_python_shared "$candidate"; then
      candidate=""
    fi
  fi

  if [[ -z "$candidate" ]] && command -v python3 >/dev/null 2>&1; then
    candidate=$(command -v python3)
    if ! check_python_version "$candidate" || ! check_python_shared "$candidate"; then
      candidate=""
    fi
  fi

  if [[ -z "$candidate" ]]; then
    candidate=$(install_pyenv_python)
  fi

  echo "$candidate"
}

PYTHON_PATH=$(resolve_python)

"$PYTHON_PATH" -m venv "$BUILD_VENV"
source "$BUILD_VENV/bin/activate"

python -m pip install --upgrade pip
python -m pip install "$ROOT_DIR[desktop-build]"

python "$ROOT_DIR/manage.py" collectstatic --noinput

PYINSTALLER_PROJECT_ROOT="$ROOT_DIR" python -m PyInstaller "$BACKEND_DIR/backend.spec" \
  --distpath "$BACKEND_DIR/dist" \
  --workpath "$BACKEND_DIR/build" \
  --noconfirm \
  --clean

cd "$ROOT_DIR/desktop"
npm ci
npm run build -- --linux
