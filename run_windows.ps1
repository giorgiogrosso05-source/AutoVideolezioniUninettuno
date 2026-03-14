$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
  Write-Host "uv non trovato: provo a installarlo automaticamente"
  try {
    irm https://astral.sh/uv/install.ps1 | iex
  } catch {
    Write-Host "Installazione uv fallita, continuo con Python di sistema."
  }
  $env:Path = "$env:USERPROFILE\\.cargo\\bin;$env:USERPROFILE\\.local\\bin;$env:Path"
  $uv = Get-Command uv -ErrorAction SilentlyContinue
}

if ($uv) {
  Write-Host "Uso uv: creo venv con Python 3.11"
  uv python install 3.11
  uv venv --python 3.11 .venv
  .\.venv\Scripts\Activate.ps1
} else {
  $py = $null
  if (Get-Command py -ErrorAction SilentlyContinue) {
    # Prefer 3.11, fallback to 3.12 if 3.11 not available.
    try {
      & py -3.11 -c "import sys" | Out-Null
      $py = @("py", "-3.11")
    } catch {
      try {
        & py -3.12 -c "import sys" | Out-Null
        $py = @("py", "-3.12")
      } catch {
        $py = $null
      }
    }
  } elseif (Get-Command python3.11 -ErrorAction SilentlyContinue) {
    $py = @("python3.11")
  } elseif (Get-Command python3.12 -ErrorAction SilentlyContinue) {
    $py = @("python3.12")
  } elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $py = @("python")
  }

  if (-not $py) {
    throw "Python non trovato. Installa Python 3.11 o 3.12 e riprova."
  }

  Write-Host "Uso interprete: $($py -join ' ')"
  $pyVer = & $py -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
  if ($pyVer -ne "3.11" -and $pyVer -ne "3.12") {
    throw "Versione Python non supportata: $pyVer. Installa Python 3.11 o 3.12 e riprova."
  }
  & $py -m venv .venv
  .\.venv\Scripts\Activate.ps1
}

$venvPy = ".\\.venv\\Scripts\\python.exe"
if (!(Test-Path $venvPy)) {
  throw "Python della venv non trovato: $venvPy"
}

& $venvPy -m ensurepip --upgrade
& $venvPy -m pip install -r requirements.txt

$chromeCandidates = @(
  "$env:ProgramFiles\\Google\\Chrome\\Application\\chrome.exe",
  "$env:ProgramFiles(x86)\\Google\\Chrome\\Application\\chrome.exe",
  "$env:LocalAppData\\Google\\Chrome\\Application\\chrome.exe",
  "$env:ProgramFiles\\Chromium\\Application\\chrome.exe",
  "$env:ProgramFiles(x86)\\Chromium\\Application\\chrome.exe"
)
$hasSystemBrowser = $false
foreach ($c in $chromeCandidates) {
  if ($c -and (Test-Path $c)) {
    $hasSystemBrowser = $true
    break
  }
}

if ($hasSystemBrowser) {
  Write-Host "Browser di sistema rilevato: salto download browser Playwright"
} else {
  & $venvPy -m playwright install
}

& $venvPy main.py
