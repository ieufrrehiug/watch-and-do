$ErrorActionPreference = 'Stop'
$index = 0
if ($args.Count -gt 0 -and $args[0] -eq '--data') { $index = 2 }
elseif ($args.Count -gt 0 -and $args[0] -like '--data=*') { $index = 1 }
$command = if ($index -lt $args.Count) { $args[$index] }
if ($command -like 'community-*') {
    & python -X utf8 (Join-Path $PSScriptRoot 'community_memory.py') @args
} elseif ($command -eq 'find-captures' -or ($command -eq 'capture' -and
    ($args -match '^--(tools|task-type|basis|check)(=|$)'))) {
    & python -X utf8 (Join-Path $PSScriptRoot 'experience.py') @args
} elseif ($command -like 'scene-*') {
    & python -X utf8 (Join-Path $PSScriptRoot 'scene_memory.py') @args
} else {
    $runtime = $env:WATCH_AND_DO_RUNTIME
    $configPath = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.config/watch-and-do/runtime-root.txt'
    if (-not $runtime -and (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        $runtime = (Get-Content -LiteralPath $configPath -Encoding UTF8 -Raw).Trim()
        if (-not [IO.Path]::IsPathRooted($runtime)) { throw "Expected an absolute runtime directory in $configPath" }
    }
    if ($runtime) {
        $entryPath = Join-Path $runtime 'experience.py'
        if (-not (Test-Path -LiteralPath $entryPath -PathType Leaf)) { throw "Configured recipe runtime missing at $runtime" }
        & python -X utf8 (Join-Path $PSScriptRoot 'memory_paths.py') $entryPath @args
    } else {
        & python -X utf8 (Join-Path $PSScriptRoot 'experience.py') @args
    }
}
exit $LASTEXITCODE
