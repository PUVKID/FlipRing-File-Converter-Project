$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath 'D:\2026\FilpRing Project').Path
$taskWork = Join-Path $taskRoot 'work\responsive-layout-20261030'
$taskStage = Join-Path $taskWork 'release-stage1'
$taskBackup = Join-Path $taskWork 'previous-release-before18'
$taskProof = Get-Content -LiteralPath (Join-Path $taskRoot 'evidence\1.8-설치파일전체대조.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $taskProof.passed) { throw '실제 설치 파일 대조가 통과하지 않았습니다.' }
if (Test-Path -LiteralPath $taskBackup) { throw '이전 보존 경로가 있어 덮어쓰지 않습니다.' }
$taskSources = @((Join-Path $taskRoot '프로그램\FlipRing'),(Join-Path $taskRoot '설치파일\FlipRing-Setup.exe'),(Join-Path $taskStage '프로그램\FlipRing'),(Join-Path $taskStage '설치파일\FlipRing-Setup.exe'))
foreach ($taskSource in $taskSources) {
    $taskResolved = (Resolve-Path -LiteralPath $taskSource).Path
    if (-not $taskResolved.StartsWith($taskRoot + '\',[System.StringComparison]::OrdinalIgnoreCase)) { throw '이동 경로가 프로젝트 밖입니다.' }
}
$taskDestination = [IO.Path]::GetFullPath($taskBackup)
if (-not $taskDestination.StartsWith($taskRoot + '\',[System.StringComparison]::OrdinalIgnoreCase)) { throw '보존 대상이 프로젝트 밖입니다.' }
New-Item -ItemType Directory -Path (Join-Path $taskBackup '프로그램'),(Join-Path $taskBackup '설치파일') | Out-Null
Move-Item -LiteralPath (Join-Path $taskRoot '프로그램\FlipRing') -Destination (Join-Path $taskBackup '프로그램\FlipRing')
Move-Item -LiteralPath (Join-Path $taskRoot '설치파일\FlipRing-Setup.exe') -Destination (Join-Path $taskBackup '설치파일\FlipRing-Setup.exe')
Copy-Item -LiteralPath (Join-Path $taskRoot 'SHA256SUMS.txt') -Destination (Join-Path $taskBackup '이전-SHA256SUMS.txt')
Move-Item -LiteralPath (Join-Path $taskStage '프로그램\FlipRing') -Destination (Join-Path $taskRoot '프로그램\FlipRing')
Move-Item -LiteralPath (Join-Path $taskStage '설치파일\FlipRing-Setup.exe') -Destination (Join-Path $taskRoot '설치파일\FlipRing-Setup.exe')
Write-Output '실제 설치 대조를 마친 새 실행·설치 파일을 같은 프로젝트 폴더에 배치했습니다. 이전 바이너리는 검증 종료 전 보존합니다.'
