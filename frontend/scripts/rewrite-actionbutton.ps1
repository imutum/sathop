$ErrorActionPreference = "Stop"
$src = (Resolve-Path "$PSScriptRoot/../src").Path
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# Files that import ActionButton (covers all 11 + ConfirmDialog).
$targets = @(
    "ui/ConfirmDialog.vue",
    "pages/BatchDetail.vue",
    "pages/SharedFiles.vue",
    "pages/Batches.vue",
    "components/onboarding/OnboardingCard.vue",
    "pages/Bundles.vue",
    "features/bundle/components/BundleManifestView.vue",
    "features/batch/components/BatchGranuleTable.vue",
    "features/batch/components/CreateBatchCsvModal.vue",
    "features/batch/components/CreateBatchModal.vue",
    "features/bundle/components/UploadBundleModal.vue",
    "features/shared/components/UploadSharedModal.vue"
)

# All tone="X" / variant="Y" literals in this codebase belong to ActionButton
# (verified by grep — Badge / Stat use :tone= dynamic, never tone="primary"
# style). Safe to do flat literal replacement.
$replacements = @(
    @{ Old = 'tone="primary"';  New = 'variant="default"' }
    @{ Old = 'tone="default"';  New = 'variant="outline"' }
    @{ Old = 'tone="danger"';   New = 'variant="destructive"' }
    @{ Old = 'tone="ghost"';    New = 'variant="ghost"' }
    @{ Old = 'tone="outline"';  New = 'variant="outline"' }
    @{ Old = '<ActionButton';   New = '<Button' }
    @{ Old = '</ActionButton>'; New = '</Button>' }
    # ConfirmDialog uses a relative import (sibling under ui/).
    @{ Old = 'import ActionButton from "./ActionButton.vue";'; New = 'import { Button } from "@/components/ui/button";' }
    @{ Old = 'import ActionButton from "@/ui/ActionButton.vue";'; New = 'import { Button } from "@/components/ui/button";' }
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
