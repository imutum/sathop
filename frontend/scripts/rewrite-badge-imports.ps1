$ErrorActionPreference = "Stop"
$src = (Resolve-Path "$PSScriptRoot/../src").Path
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$files = Get-ChildItem -Path $src -Recurse -Include *.vue, *.ts
$changed = 0
foreach ($f in $files) {
    $original = [System.IO.File]::ReadAllText($f.FullName, $utf8NoBom)
    $content = $original.Replace(
        'import Badge from "@/ui/Badge.vue";',
        'import { Badge } from "@/components/ui/badge";'
    )
    if ($content -ne $original) {
        [System.IO.File]::WriteAllText($f.FullName, $content, $utf8NoBom)
        $changed++
        Write-Host "  rewrite $($f.FullName.Substring($src.Length + 1))"
    }
}
Write-Host "Files changed: $changed"
