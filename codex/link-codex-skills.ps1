param(
  [string]$SkillsSource = (Join-Path $PSScriptRoot "skills"),
  [string]$CodexSkills = (Join-Path $env:USERPROFILE ".codex\skills")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $SkillsSource)) {
  throw "Skills source not found: $SkillsSource"
}

$codexHome = Split-Path -Parent $CodexSkills
New-Item -ItemType Directory -Force -Path $codexHome | Out-Null

if (Test-Path -LiteralPath $CodexSkills) {
  $item = Get-Item -LiteralPath $CodexSkills
  if ($item.LinkType -eq "Junction" -and $item.Target -contains $SkillsSource) {
    Write-Output "Already linked: $CodexSkills -> $SkillsSource"
    exit 0
  }

  $systemSource = Join-Path $SkillsSource ".system"
  $systemExisting = Join-Path $CodexSkills ".system"
  if ((-not (Test-Path -LiteralPath $systemSource)) -and (Test-Path -LiteralPath $systemExisting)) {
    Copy-Item -LiteralPath $systemExisting -Destination $systemSource -Recurse -Force
    Write-Output "Copied existing .system skills into: $systemSource"
  }

  $backup = "$CodexSkills.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
  Rename-Item -LiteralPath $CodexSkills -NewName (Split-Path -Leaf $backup)
  Write-Output "Backed up existing skills to: $backup"
}

New-Item -ItemType Junction -Path $CodexSkills -Target $SkillsSource | Out-Null
Write-Output "Linked: $CodexSkills -> $SkillsSource"
Write-Output "Restart Codex to pick up skills from the linked directory."
