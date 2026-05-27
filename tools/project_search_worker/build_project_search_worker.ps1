$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$source = Join-Path $PSScriptRoot "project_search_worker.cpp"
$outputDir = Join-Path $root "bin"
$output = Join-Path $outputDir "project_search_worker.exe"

New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$cl = Get-Command cl.exe -ErrorAction SilentlyContinue
if ($cl) {
    & $cl.Source /nologo /std:c++17 /EHsc /O2 /utf-8 /Fe:$output $source
    exit $LASTEXITCODE
}

$clang = Get-Command clang++.exe -ErrorAction SilentlyContinue
if ($clang) {
    & $clang.Source -std=c++17 -O2 -Wall -Wextra -o $output $source
    exit $LASTEXITCODE
}

$gpp = Get-Command g++.exe -ErrorAction SilentlyContinue
if ($gpp) {
    & $gpp.Source -std=c++17 -O2 -Wall -Wextra -o $output $source
    exit $LASTEXITCODE
}

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vswhere) {
    $vsInstall = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($vsInstall) {
        $vsDevCmd = Join-Path $vsInstall "Common7\Tools\VsDevCmd.bat"
        if (Test-Path $vsDevCmd) {
            $command = "`"$vsDevCmd`" -arch=x64 -host_arch=x64 && cl.exe /nologo /std:c++17 /EHsc /O2 /utf-8 /Fe:`"$output`" `"$source`""
            cmd.exe /c $command
            exit $LASTEXITCODE
        }
    }
}

$knownVsDevCmds = @(
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat",
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"
)
foreach ($vsDevCmd in $knownVsDevCmds) {
    if (Test-Path $vsDevCmd) {
        $command = "`"$vsDevCmd`" -arch=x64 -host_arch=x64 && cl.exe /nologo /std:c++17 /EHsc /O2 /utf-8 /Fe:`"$output`" `"$source`""
        cmd.exe /c $command
        exit $LASTEXITCODE
    }
}

throw "C++ compiler not found. Install Visual Studio Build Tools, clang++, or g++."
