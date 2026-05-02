$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot/../src"
$files = Get-ChildItem -Path $root -Recurse -Include *.vue, *.ts

# Tailwind utility prefixes that can carry a color token.
$colorPrefix = "bg|text|border|ring|fill|stroke|outline|caret|placeholder|decoration|divide|from|via|to|shadow|accent"
# Modifier chain: hover:, focus:, dark:, group-hover:, peer-*, data-*, etc.
$modChain = "(?:[a-z][a-z0-9-]*(?:\[[^\]]+\])?:)*"

# Replacements run in this order. Long tokens (accent-soft / accent-fg) MUST
# come before short ones to avoid double-prefixing.
$replacements = @(
    @{ Pattern = "\b($modChain($colorPrefix))-accent-soft\b"; Replacement = '$1-legacy-accent-soft' }
    @{ Pattern = "\b($modChain($colorPrefix))-accent-fg\b";   Replacement = '$1-legacy-accent-fg' }
    @{ Pattern = "\b($modChain($colorPrefix))-bg\b";          Replacement = '$1-legacy-bg' }
    @{ Pattern = "\b($modChain($colorPrefix))-text\b";        Replacement = '$1-legacy-text' }
    @{ Pattern = "\b($modChain($colorPrefix))-subtle\b";      Replacement = '$1-legacy-subtle' }
    @{ Pattern = "\b($modChain($colorPrefix))-surface\b";     Replacement = '$1-legacy-surface' }
    @{ Pattern = "\b($modChain($colorPrefix))-elevated\b";    Replacement = '$1-legacy-elevated' }
    @{ Pattern = "\b($modChain($colorPrefix))-accent\b";      Replacement = '$1-legacy-accent' }
    @{ Pattern = "\b($modChain($colorPrefix))-muted\b";       Replacement = '$1-legacy-muted' }
)

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$totalChanges = 0
$changedFiles = 0

foreach ($file in $files) {
    $original = [System.IO.File]::ReadAllText($file.FullName, $utf8NoBom)
    $content = $original
    $fileChanges = 0
    foreach ($r in $replacements) {
        $matches = [regex]::Matches($content, $r.Pattern)
        $fileChanges += $matches.Count
        $content = [regex]::Replace($content, $r.Pattern, $r.Replacement)
    }
    if ($content -ne $original) {
        [System.IO.File]::WriteAllText($file.FullName, $content, $utf8NoBom)
        $changedFiles++
        $totalChanges += $fileChanges
        Write-Host "  $($file.FullName.Substring($root.Path.Length + 1))  ($fileChanges)"
    }
}

Write-Host ""
Write-Host "Renamed $totalChanges occurrences across $changedFiles files."
