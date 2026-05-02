# Phase 4 final: rename legacy-* utility classes to shadcn standard tokens.
# HSL values in index.css map 1:1 — purely cosmetic rename, no visual change.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Resolve-Path "$PSScriptRoot\..\src"

# Order matters: longer keys first so "legacy-accent" doesn't pre-eat
# "legacy-accent-fg" / "legacy-accent-soft".
$rewrites = @(
    @{ Old = 'legacy-accent-fg';   New = 'primary-foreground' }
    @{ Old = 'legacy-accent-soft'; New = 'accent' }
    @{ Old = 'legacy-accent';      New = 'primary' }
    @{ Old = 'legacy-elevated';    New = 'popover' }
    @{ Old = 'legacy-muted';       New = 'muted-foreground' }
    @{ Old = 'legacy-subtle';      New = 'muted' }
    @{ Old = 'legacy-surface';     New = 'background' }
    @{ Old = 'legacy-text';        New = 'foreground' }
    @{ Old = 'legacy-bg';          New = 'background' }
)

$utf8 = New-Object System.Text.UTF8Encoding($false)
$files = Get-ChildItem -Recurse -Path $root -Include *.vue, *.ts, *.css | Where-Object { -not $_.PSIsContainer }
$touched = 0
$totalReplaces = 0
foreach ($f in $files) {
    $orig = [System.IO.File]::ReadAllText($f.FullName, $utf8)
    $next = $orig
    foreach ($r in $rewrites) {
        $next = $next.Replace($r.Old, $r.New)
    }
    if ($next -ne $orig) {
        [System.IO.File]::WriteAllText($f.FullName, $next, $utf8)
        $touched++
        # quick count
        $diffLen = ($orig -split "`n").Count - ($next -split "`n").Count
        $totalReplaces += [Math]::Abs($diffLen)
        Write-Host "rewrote tokens: $($f.FullName)"
    }
}
Write-Host "`nDone. Touched $touched files."
