$ErrorActionPreference = "Stop"
$src = (Resolve-Path "$PSScriptRoot/../src").Path
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# Files with simple <Card :padded="false"> (no title/description/action slot).
$targets = @(
    "pages/Batches.vue",
    "pages/Events.vue",
    "pages/BatchDetail.vue",
    "pages/SharedFiles.vue",
    "features/nodes/components/WorkerCard.vue",
    "features/nodes/components/ReceiverCard.vue"
)

$replacements = @(
    @{ Old = 'import Card from "@/ui/Card.vue";'; New = 'import { Card } from "@/components/ui/card";' }
    @{ Old = '<Card :padded="false">';            New = '<Card>' }
    @{ Old = '<Card v-if="b" :padded="false">';   New = '<Card v-if="b">' }
)

$totalChanges = 0
foreach ($rel in $targets) {
    $path = "$src/$rel"
    $original = [System.IO.File]::ReadAllText($path, $utf8NoBom)
    $content = $original
    foreach ($r in $replacements) {
        $content = $content.Replace($r.Old, $r.New)
    }
    if ($content -ne $original) {
        [System.IO.File]::WriteAllText($path, $content, $utf8NoBom)
        $totalChanges++
        Write-Host "  rewrite $rel"
    }
}
Write-Host "Files changed: $totalChanges"
