$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$outputDir = Join-Path $root "bin"
$sourceExe = Join-Path $PSScriptRoot "target\release\project_search_worker.exe"
$outputExe = Join-Path $outputDir "project_search_worker.exe"

New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

Push-Location $PSScriptRoot
try {
    cargo build --release
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

Copy-Item -LiteralPath $sourceExe -Destination $outputExe -Force
