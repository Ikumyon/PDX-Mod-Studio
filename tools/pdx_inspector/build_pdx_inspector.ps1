$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$outputDir = Join-Path $root "core"
$sourceDll = Join-Path $PSScriptRoot "target\release\pdx_inspector.dll"
$outputPyd = Join-Path $outputDir "pdx_inspector.pyd"

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

Copy-Item -LiteralPath $sourceDll -Destination $outputPyd -Force
