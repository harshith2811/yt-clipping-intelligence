param(
  [string]$Path,
  [int]$HoldMs = 200
)

$stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
Write-Output "LOCKED"
[System.Threading.Thread]::Sleep($HoldMs)
$stream.Close()
Write-Output "RELEASED"
