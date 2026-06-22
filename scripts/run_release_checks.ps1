param(
    [string]$BlenderPath = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
    [switch]$RunLiveOpenAI
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$RuffPath = Join-Path $ProjectRoot ".venv\Scripts\ruff.exe"
$MypyPath = Join-Path $ProjectRoot ".venv\Scripts\mypy.exe"
$ArchivePath = Join-Path $ProjectRoot "dist\blender_ai_assistant-0.1.4.zip"
$ProfilePath = Join-Path $ProjectRoot ".test-profile-release-$PID"

function Invoke-Checked {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Host "`n== $Label =="
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath $BlenderPath -PathType Leaf)) {
    throw "Blender executable not found: $BlenderPath"
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Development environment not found: $PythonPath"
}
if (Test-Path -LiteralPath $ProfilePath) {
    throw "Temporary profile already exists: $ProfilePath"
}

Push-Location $ProjectRoot
try {
    Invoke-Checked "Dependency check" $PythonPath @("-m", "pip", "check")
    Invoke-Checked "Python tests" $PythonPath @("-m", "pytest")
    Invoke-Checked "Ruff" $RuffPath @("check", ".")
    Invoke-Checked "Mypy" $MypyPath @("extension", "tests")

    Invoke-Checked "Blender integration tests" $BlenderPath @(
        "--background", "--factory-startup", "--python-exit-code", "1",
        "--python", "tests/run_blender_tests.py"
    )
    Invoke-Checked "Controlled execution tests" $BlenderPath @(
        "--background", "--factory-startup", "--python-exit-code", "1",
        "--python", "tests/run_execution_tests.py"
    )
    Invoke-Checked "Sample scene tests" $BlenderPath @(
        "--background", "--factory-startup", "--python-exit-code", "1",
        "--python", "tests/run_sample_scene_tests.py"
    )

    if ($RunLiveOpenAI) {
        if (-not $env:OPENAI_API_KEY) {
            throw "OPENAI_API_KEY must be set in the operating-system environment."
        }
        $env:RUN_LIVE_OPENAI_TESTS = "1"
        Invoke-Checked "Live OpenAI smoke test" $PythonPath @(
            "-m", "pytest", "-m", "live_openai", "tests/live/test_openai_live.py"
        )
    }

    Invoke-Checked "Source manifest validation" $BlenderPath @(
        "--command", "extension", "validate", ".\extension"
    )
    Invoke-Checked "Extension build" $BlenderPath @(
        "--command", "extension", "build", "--source-dir", ".\extension",
        "--output-dir", ".\dist"
    )
    Invoke-Checked "Archive validation" $BlenderPath @(
        "--command", "extension", "validate", $ArchivePath
    )
    Invoke-Checked "Archive content verification" $PythonPath @(
        "tests/verify_release_package.py", $ArchivePath
    )

    $ConfigPath = Join-Path $ProfilePath "config"
    $ScriptsPath = Join-Path $ProfilePath "scripts"
    $DatafilesPath = Join-Path $ProfilePath "datafiles"
    $RepositoryPath = Join-Path $ProfilePath "repo"
    New-Item -ItemType Directory -Path @(
        $ConfigPath, $ScriptsPath, $DatafilesPath, $RepositoryPath
    ) -Force | Out-Null
    $env:BLENDER_USER_CONFIG = $ConfigPath
    $env:BLENDER_USER_SCRIPTS = $ScriptsPath
    $env:BLENDER_USER_DATAFILES = $DatafilesPath

    Invoke-Checked "Isolated repository setup" $BlenderPath @(
        "--command", "extension", "repo-add", "release_test", "--name",
        "Release Test", "--directory", $RepositoryPath, "--clear-all"
    )
    Invoke-Checked "Isolated archive install" $BlenderPath @(
        "--command", "extension", "install-file", "-r", "release_test", "-e", $ArchivePath
    )
    Invoke-Checked "Installed extension test" $BlenderPath @(
        "--background", "--python-exit-code", "1",
        "--python", "tests/run_installed_extension_tests.py"
    )

    Write-Host "`nRelease checks: PASS"
}
finally {
    Pop-Location
    $ResolvedRoot = $ProjectRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $ResolvedProfile = [System.IO.Path]::GetFullPath($ProfilePath)
    if ($ResolvedProfile.StartsWith(
        $ResolvedRoot + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -and (Test-Path -LiteralPath $ResolvedProfile)) {
        Remove-Item -LiteralPath $ResolvedProfile -Recurse -Force
    }
}
