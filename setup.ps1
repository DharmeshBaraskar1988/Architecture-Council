# One-step setup for the AI Architecture Council on Windows (PowerShell 5.1 or 7).
# Safe to run again: it never overwrites .env or files you already have (unless -Force).
#
#   .\setup.ps1                      # everything
#   .\setup.ps1 -SkipFrontend        # backend only
#   .\setup.ps1 -SkipEditorFiles     # leave .vscode, .github and Makefile alone
#   .\setup.ps1 -Force               # also replace existing .vscode, workflow and Makefile copies
#
# If scripts are blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$SkipEditorFiles,
    [switch]$SkipTests,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    $text" -ForegroundColor Green }
function Warn($text) { Write-Host "    $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "    $text" -ForegroundColor Red; exit 1 }

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments, [string]$Where)
    Push-Location $Where
    try {
        & $Exe @Arguments
        if ($LASTEXITCODE -ne 0) { Fail "'$Exe $($Arguments -join ' ')' failed (exit $LASTEXITCODE)" }
    } finally { Pop-Location }
}

# 1. Tools ------------------------------------------------------------------
Step 'Checking Python (3.10 or newer)'
$python = $null
foreach ($candidate in @('py', 'python')) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $args3 = @()
        if ($candidate -eq 'py') { $args3 = @('-3') }
        # No quotes inside the Python code: PowerShell 5.1 strips embedded double quotes from native
        # arguments. Stderr is tolerated so a broken candidate (e.g. the Store stub) is skipped, not fatal.
        $version = $null
        try {
            $ErrorActionPreference = 'Continue'
            $version = & $candidate @args3 -c 'import sys; v = sys.version_info; print(v.major, v.minor)' 2>$null
        } catch { $version = $null } finally { $ErrorActionPreference = 'Stop' }
        if ($LASTEXITCODE -eq 0 -and $version) {
            $version = ($version | Select-Object -First 1).Trim() -replace ' ', '.'
            $parts = $version.Split('.')
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) {
                $python = @{ Exe = $candidate; Args = $args3; Version = $version.Trim() }
                break
            }
        }
    }
}
if (-not $python) { Fail 'Python 3.10+ not found. Install it from https://www.python.org/downloads/ and tick "Add to PATH".' }
Ok "Python $($python.Version)"

if (-not $SkipFrontend) {
    Step 'Checking Node.js (20.9 or newer, for Next.js)'
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Fail 'Node.js not found. Install the LTS from https://nodejs.org/ or run with -SkipFrontend.'
    }
    $nodeVersion = (& node --version).TrimStart('v')
    $nodeParts = $nodeVersion.Split('.')
    if ([int]$nodeParts[0] -lt 20 -or ([int]$nodeParts[0] -eq 20 -and [int]$nodeParts[1] -lt 9)) {
        Fail "Node.js $nodeVersion is too old; Next.js 16 needs 20.9 or newer."
    }
    Ok "Node.js $nodeVersion"
}

# 2. Backend ----------------------------------------------------------------
Step 'Backend virtual environment (backend\.venv)'
if (Test-Path $venvPython) {
    Ok 'Already exists'
} else {
    Invoke-Checked $python.Exe ($python.Args + @('-m', 'venv', '.venv')) $backend
    Ok 'Created'
}

Step 'Installing the backend (pip install -e ".[dev]")'
Invoke-Checked $venvPython @('-m', 'pip', 'install', '--upgrade', '--quiet', 'pip') $backend
Invoke-Checked $venvPython @('-m', 'pip', 'install', '--quiet', '-e', '.[dev]') $backend
Ok 'Installed; the `council` command is in backend\.venv\Scripts'

# 3. .env ---------------------------------------------------------------------
Step 'Environment file (.env)'
$envFile = Join-Path $root '.env'
if (Test-Path $envFile) {
    Ok '.env already exists; left unchanged'
} else {
    Copy-Item (Join-Path $root '.env.example') $envFile
    Warn 'Created .env from .env.example: add keys for at least two providers'
}
$providerKeys = @('ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'GROQ_API_KEY', 'OLLAMA_API_KEY')
$setKeys = @(Get-Content $envFile | Where-Object { $_ -match '^\s*([A-Z_]+)\s*=\s*\S' } |
    ForEach-Object { $Matches[1] } | Where-Object { $providerKeys -contains $_ })
if ($setKeys.Count -ge 2) {
    Ok "Provider keys set: $($setKeys -join ', ')"
} else {
    Warn "Only $($setKeys.Count) provider key(s) set; ``council run`` needs at least two. Tests and validate work without any."
}
if (Get-Content $envFile | Where-Object { $_ -match '^\s*COUNCIL_MOCK_LLM\s*=\s*1' }) {
    Warn 'COUNCIL_MOCK_LLM=1 in .env: real runs will use mock responses. Set it to 0 for live runs.'
}

# 4. Editor, CI and Makefile copies -----------------------------------------------
if (-not $SkipEditorFiles) {
    Step 'VS Code, GitHub workflow and Makefile (from setup\)'
    $copies = @()
    foreach ($file in Get-ChildItem (Join-Path $root 'setup\vscode') -Filter *.json) {
        $copies += , @($file.FullName, (Join-Path $root ".vscode\$($file.Name)"))
    }
    $copies += , @((Join-Path $root 'setup\github\tests.yml.txt'), (Join-Path $root '.github\workflows\tests.yml'))
    $copies += , @((Join-Path $root 'setup\Makefile.txt'), (Join-Path $root 'Makefile'))
    foreach ($pair in $copies) {
        $source, $target = $pair
        $relative = $target.Substring($root.Length + 1)
        if ((Test-Path $target) -and -not $Force) {
            Ok "$relative exists; kept (use -Force to replace)"
            continue
        }
        New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
        Copy-Item $source $target -Force
        Ok "Copied $relative"
    }
}

# 5. Frontend -------------------------------------------------------------------
if (-not $SkipFrontend) {
    Step 'Installing the viewer and council room (frontend, npm install)'
    Invoke-Checked 'npm' @('install', '--no-fund', '--no-audit') $frontend
    Ok 'Installed'
}

# 6. Checks -----------------------------------------------------------------------
if (-not $SkipTests) {
    Step 'Running the tests (no keys or network needed)'
    Invoke-Checked $venvPython @('-m', 'pytest', '-q') $backend
    Step 'Validating the framework and solution catalogs'
    Invoke-Checked $venvPython @('-m', 'app.cli', 'validate') $backend
}

Step 'Done. Next steps (from the council folder; no venv activation needed):'
Write-Host @"
    .\council crawl               # fetch the evidence pages (no model calls)
    .\council verify              # live production gate
    .\council run --prd data\samples\prds\s1_financial_briefing.md --review skip
    .\start                       # viewer and council room at http://localhost:3000
"@
