$ErrorActionPreference = 'Stop'
$index = 0
if ($args.Count -gt 0 -and $args[0] -eq '--data') { $index = 2 }
elseif ($args.Count -gt 0 -and $args[0] -like '--data=*') { $index = 1 }
if ($index -lt $args.Count -and $args[$index] -like 'community-*') {
    & python -X utf8 (Join-Path $PSScriptRoot 'community_memory.py') @args
} else {
    & python -X utf8 (Join-Path $PSScriptRoot 'scene_memory.py') @args
}
exit $LASTEXITCODE
