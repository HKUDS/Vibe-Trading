param(
    [switch]$SkipRegistrySemgrep
)

# Optional local/security acceptance gate.
# Reproducible Python tooling can be installed with:
#   python -m pip install -e ".[security]"
# gitleaks/trufflehog remain optional external binaries under .tmp\tools.

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

$Semgrep = Join-Path $RepoRoot ".venv\Scripts\semgrep.exe"
$Bandit = Join-Path $RepoRoot ".venv\Scripts\bandit.exe"
$PipAudit = Join-Path $RepoRoot ".venv\Scripts\pip-audit.exe"
$Mypy = Join-Path $RepoRoot ".venv\Scripts\mypy.exe"
$Pyright = Join-Path $RepoRoot ".venv\Scripts\pyright.exe"
$Safety = Join-Path $RepoRoot ".venv\Scripts\safety.exe"
$CycloneDx = Join-Path $RepoRoot ".venv\Scripts\cyclonedx-py.exe"
$Gitleaks = Join-Path $RepoRoot ".tmp\tools\gitleaks\gitleaks.exe"
$Trufflehog = Join-Path $RepoRoot ".tmp\tools\trufflehog\trufflehog.exe"

function Invoke-AgsStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Host "==> $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "AGS P0 acceptance step failed: $Name"
    }
}

function Require-Tool {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Name is required. Install it in .venv before running AGS P0 acceptance."
    }
}

New-Item -ItemType Directory -Force -Path ".tmp\semgrep-config", ".tmp\semgrep-cache" | Out-Null
$env:XDG_CONFIG_HOME = (Resolve-Path ".tmp\semgrep-config").Path
$env:XDG_CACHE_HOME = (Resolve-Path ".tmp\semgrep-cache").Path
$env:SEMGREP_LOG_FILE = Join-Path $env:XDG_CONFIG_HOME "semgrep.log"
$env:SEMGREP_SETTINGS_FILE = Join-Path $env:XDG_CONFIG_HOME "settings.yml"
$env:SEMGREP_METRICS = "off"

Require-Tool -Path $Semgrep -Name "semgrep"
Require-Tool -Path $Bandit -Name "bandit"
Require-Tool -Path $PipAudit -Name "pip-audit"
Require-Tool -Path $Mypy -Name "mypy"
Require-Tool -Path $Pyright -Name "pyright"
Require-Tool -Path $Safety -Name "safety"
Require-Tool -Path $CycloneDx -Name "cyclonedx-py"

Invoke-AgsStep "git diff whitespace check" {
    git diff --check
}

Invoke-AgsStep "compile AGS Python modules" {
    & $Python -m compileall -q agent/src/alpha_foundry agent/src/alpha_quality agent/src/research_ledger agent/cli
}

Invoke-AgsStep "focused AGS pytest matrix" {
    & $Python -m pytest `
        agent/tests/security/test_ags_static_semgrep_rules.py `
        agent/tests/security/test_ags_artifact_path_safety.py `
        agent/tests/alpha_foundry/dsl/test_adversarial_payloads.py `
        agent/tests/alpha_quality/test_property_invariants.py `
        agent/tests/research_ledger/test_property_hash_chain.py `
        agent/tests/alpha_quality/test_golden_master_scorecard.py `
        agent/tests/contracts/test_ags_architecture_invariants.py `
        agent/tests/security/test_alpha_genesis_api_injection_extreme.py `
        agent/tests/security/test_alpha_genesis_secret_leakage_extreme.py `
        agent/tests/performance/test_ags_acceptance_budget.py `
        -q --tb=short
}

Invoke-AgsStep "mypy strict AGS dataflow check" {
    $env:MYPYPATH = "agent"
    & $Mypy --strict --ignore-missing-imports `
        agent/src/alpha_foundry agent/src/alpha_quality agent/src/research_ledger agent/cli/alpha_genesis.py
}

Invoke-AgsStep "pyright AGS dataflow check" {
    & $Pyright agent/src/alpha_foundry agent/src/alpha_quality agent/src/research_ledger agent/cli/alpha_genesis.py
}

Invoke-AgsStep "custom AGS Semgrep bypass rules" {
    & $Semgrep scan --config security\semgrep\ags-python-injection.yml `
        agent/src/alpha_foundry agent/src/alpha_quality agent/src/research_ledger
}

if (-not $SkipRegistrySemgrep) {
    Invoke-AgsStep "Semgrep registry python and secrets rules" {
        & $Semgrep scan --config p/python --config p/secrets `
            agent/src/alpha_foundry agent/src/alpha_quality agent/src/research_ledger agent/cli
    }
}

Invoke-AgsStep "Bandit AGS recursive scan" {
    & $Bandit -q -r agent/src/alpha_foundry agent/src/alpha_quality agent/src/research_ledger agent/cli/alpha_genesis.py
}

Invoke-AgsStep "pip-audit dependency vulnerability scan" {
    & $PipAudit
}

Invoke-AgsStep "Safety dependency vulnerability scan" {
    & $Safety --disable-optional-telemetry check --full-report
}

Invoke-AgsStep "CycloneDX SBOM generation" {
    $sbom = Join-Path $RepoRoot ".tmp\ags-sbom.cdx.json"
    & $CycloneDx environment .\.venv -o $sbom
    if (-not (Test-Path -LiteralPath $sbom)) {
        throw "CycloneDX did not produce $sbom"
    }
}

if (Test-Path -LiteralPath $Gitleaks) {
    Invoke-AgsStep "gitleaks production AGS secret scan" {
        & $Gitleaks detect --no-git --no-banner --redact --source agent/src/alpha_foundry --exit-code 1
        & $Gitleaks detect --no-git --no-banner --redact --source agent/src/alpha_quality --exit-code 1
        & $Gitleaks detect --no-git --no-banner --redact --source agent/src/research_ledger --exit-code 1
        & $Gitleaks detect --no-git --no-banner --redact --source agent/src/api/alpha_genesis_routes.py --exit-code 1
        & $Gitleaks detect --no-git --no-banner --redact --source agent/cli/alpha_genesis.py --exit-code 1
    }
} else {
    Write-Warning "gitleaks binary not found at $Gitleaks; skipping optional external secret scanner."
}

if (Test-Path -LiteralPath $Trufflehog) {
    Invoke-AgsStep "trufflehog production AGS secret scan" {
        & $Trufflehog filesystem --no-update --fail --no-color --results=verified,unknown `
            --directory=agent/src/alpha_foundry `
            --directory=agent/src/alpha_quality `
            --directory=agent/src/research_ledger `
            --directory=agent/src/api `
            --directory=agent/cli/alpha_genesis.py
    }
} else {
    Write-Warning "trufflehog binary not found at $Trufflehog; skipping optional external secret scanner."
}

Write-Host "AGS P0 acceptance passed."
