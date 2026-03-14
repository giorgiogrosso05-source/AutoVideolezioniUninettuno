#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv non trovato: provo a installarlo automaticamente"
  if ! command -v curl >/dev/null 2>&1; then
    echo "curl non trovato. Installa curl o uv manualmente e riprova."
    exit 1
  fi
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
fi

if command -v uv >/dev/null 2>&1; then
  echo "Uso uv: creo venv con Python 3.11"
  uv python install 3.11
  UV_VENV_CLEAR=1 uv venv --python 3.11 .venv
  source .venv/bin/activate
else
  PY_BIN=""
  if command -v python3.11 >/dev/null 2>&1; then
    PY_BIN="python3.11"
  elif command -v python3.12 >/dev/null 2>&1; then
    PY_BIN="python3.12"
  elif command -v python3 >/dev/null 2>&1; then
    PY_BIN="python3"
  else
    echo "Python non trovato. Installa Python 3.11 o 3.12 e riprova."
    exit 1
  fi

  echo "Uso interprete: $PY_BIN"
  PY_VER="$($PY_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [ "$PY_VER" != "3.11" ] && [ "$PY_VER" != "3.12" ]; then
    echo "Versione Python non supportata: $PY_VER"
    echo "Installa Python 3.11 o 3.12 e riprova."
    exit 1
  fi
  $PY_BIN -m venv .venv
  source .venv/bin/activate
fi

VENV_PY=".venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  echo "Python della venv non trovato: $VENV_PY"
  exit 1
fi

"$VENV_PY" -m ensurepip --upgrade
"$VENV_PY" -m pip install -r requirements.txt

if command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1 || \
   command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1; then
  echo "Browser di sistema rilevato: salto download browser Playwright"
else
  if command -v pacman >/dev/null 2>&1; then
    if command -v sudo >/dev/null 2>&1; then
      echo "Chromium non trovato: provo a installarlo con pacman"
      if ! sudo pacman -S --noconfirm chromium; then
        echo "Installazione Chromium fallita (mirror o keyring). Provo a sistemare pacman..."
        sudo pacman -Syy --noconfirm || true
        sudo pacman -S --needed --noconfirm cachyos-keyring archlinux-keyring || true
        sudo rm -f /var/cache/pacman/pkg/chromium-*.pkg.tar.zst || true
        if ! sudo pacman -S --noconfirm chromium; then
          echo "Installazione Chromium fallita anche dopo il fix."
          echo "Proseguo con i browser Playwright come fallback."
        fi
      fi
    else
      echo "sudo non disponibile: installa chromium manualmente con pacman"
    fi
  fi

  if command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1 || \
     command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1; then
    echo "Browser di sistema installato: salto download browser Playwright"
  else
    "$VENV_PY" -m playwright install
  fi
fi

exec "$VENV_PY" main.py
