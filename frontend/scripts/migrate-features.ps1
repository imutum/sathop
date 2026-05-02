$ErrorActionPreference = "Stop"
$src = (Resolve-Path "$PSScriptRoot/../src").Path
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$mapping = @{
    "BatchEventLog.vue"           = "features/batch/components"
    "BatchGranuleTable.vue"       = "features/batch/components"
    "BatchTimingCard.vue"         = "features/batch/components"
    "CreateBatchCell.vue"         = "features/batch/components"
    "CreateBatchCredentials.vue"  = "features/batch/components"
    "CreateBatchCsvModal.vue"     = "features/batch/components"
    "CreateBatchGranuleTable.vue" = "features/batch/components"
    "CreateBatchModal.vue"        = "features/batch/components"
    "GranuleEvents.vue"           = "features/batch/components"
    "LatestProgressLine.vue"      = "features/batch/components"
    "ProgressTimeline.vue"        = "features/batch/components"
    "StageTimingStrip.vue"        = "features/batch/components"
    "StateBarChart.vue"           = "features/batch/components"
    "ErrorCell.vue"               = "features/batch/components"
    "BundleFileBrowser.vue"       = "features/bundle/components"
    "BundleManifestView.vue"      = "features/bundle/components"
    "BundleSection.vue"           = "features/bundle/components"
    "UploadBundleModal.vue"       = "features/bundle/components"
    "UploadSharedModal.vue"       = "features/shared/components"
    "WorkerCard.vue"              = "features/nodes/components"
    "ReceiverCard.vue"            = "features/nodes/components"
    "NodeStat.vue"                = "features/nodes/components"
    "OnboardingCard.vue"          = "components/onboarding"
}

# Step 1: Create dirs + move files.
$dirs = $mapping.Values | Sort-Object -Unique
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Path "$src\$d" -Force | Out-Null
}
foreach ($name in $mapping.Keys) {
    $from = "$src\pages\$name"
    $to = "$src\$($mapping[$name])\$name"
    if (Test-Path $from) {
        Move-Item -Path $from -Destination $to -Force
        Write-Host "  move $name -> $($mapping[$name])"
    }
}
# createBatchTypes.ts -> features/batch/types.ts
$typesFrom = "$src\pages\createBatchTypes.ts"
$typesTo = "$src\features\batch\types.ts"
if (Test-Path $typesFrom) {
    Move-Item -Path $typesFrom -Destination $typesTo -Force
    Write-Host "  move createBatchTypes.ts -> features/batch/types.ts"
}

# Step 2: import path rewrites (literal text replace, all double-quoted forms).
$replacements = @(
    @{ Old = 'from "./BatchEventLog.vue"';           New = 'from "@/features/batch/components/BatchEventLog.vue"' }
    @{ Old = 'from "./BatchGranuleTable.vue"';       New = 'from "@/features/batch/components/BatchGranuleTable.vue"' }
    @{ Old = 'from "./BatchTimingCard.vue"';         New = 'from "@/features/batch/components/BatchTimingCard.vue"' }
    @{ Old = 'from "./CreateBatchModal.vue"';        New = 'from "@/features/batch/components/CreateBatchModal.vue"' }
    @{ Old = 'from "./BundleFileBrowser.vue"';       New = 'from "@/features/bundle/components/BundleFileBrowser.vue"' }
    @{ Old = 'from "./BundleSection.vue"';           New = 'from "@/features/bundle/components/BundleSection.vue"' }
    @{ Old = 'from "./BundleManifestView.vue"';      New = 'from "@/features/bundle/components/BundleManifestView.vue"' }
    @{ Old = 'from "./UploadBundleModal.vue"';       New = 'from "@/features/bundle/components/UploadBundleModal.vue"' }
    @{ Old = 'from "./ErrorCell.vue"';               New = 'from "@/features/batch/components/ErrorCell.vue"' }
    @{ Old = 'from "./GranuleEvents.vue"';           New = 'from "@/features/batch/components/GranuleEvents.vue"' }
    @{ Old = 'from "./LatestProgressLine.vue"';      New = 'from "@/features/batch/components/LatestProgressLine.vue"' }
    @{ Old = 'from "./ProgressTimeline.vue"';        New = 'from "@/features/batch/components/ProgressTimeline.vue"' }
    @{ Old = 'from "./StageTimingStrip.vue"';        New = 'from "@/features/batch/components/StageTimingStrip.vue"' }
    @{ Old = 'from "./StateBarChart.vue"';           New = 'from "@/features/batch/components/StateBarChart.vue"' }
    @{ Old = 'from "./NodeStat.vue"';                New = 'from "@/features/nodes/components/NodeStat.vue"' }
    @{ Old = 'from "./OnboardingCard.vue"';          New = 'from "@/components/onboarding/OnboardingCard.vue"' }
    @{ Old = 'from "./ReceiverCard.vue"';            New = 'from "@/features/nodes/components/ReceiverCard.vue"' }
    @{ Old = 'from "./UploadSharedModal.vue"';       New = 'from "@/features/shared/components/UploadSharedModal.vue"' }
    @{ Old = 'from "./WorkerCard.vue"';              New = 'from "@/features/nodes/components/WorkerCard.vue"' }
    @{ Old = 'from "./CreateBatchCell.vue"';         New = 'from "@/features/batch/components/CreateBatchCell.vue"' }
    @{ Old = 'from "./CreateBatchCredentials.vue"';  New = 'from "@/features/batch/components/CreateBatchCredentials.vue"' }
    @{ Old = 'from "./CreateBatchCsvModal.vue"';     New = 'from "@/features/batch/components/CreateBatchCsvModal.vue"' }
    @{ Old = 'from "./CreateBatchGranuleTable.vue"'; New = 'from "@/features/batch/components/CreateBatchGranuleTable.vue"' }
    # types: createBatchTypes -> @/features/batch/types
    @{ Old = 'from "./createBatchTypes"';            New = 'from "@/features/batch/types"' }
    # outward relative imports inside migrated files
    @{ Old = 'from "../api"';                        New = 'from "@/api"' }
    @{ Old = 'from "../i18n"';                       New = 'from "@/i18n"' }
    @{ Old = 'from "../credCache"';                  New = 'from "@/credCache"' }
    @{ Old = 'from "../ui/';                         New = 'from "@/ui/' }
    @{ Old = 'from "../composables/';                New = 'from "@/composables/' }
)

$files = Get-ChildItem -Path $src -Recurse -Include *.vue, *.ts
$totalChanges = 0
$changedFiles = 0
foreach ($f in $files) {
    $original = [System.IO.File]::ReadAllText($f.FullName, $utf8NoBom)
    $content = $original
    foreach ($r in $replacements) {
        $content = $content.Replace($r.Old, $r.New)
    }
    if ($content -ne $original) {
        [System.IO.File]::WriteAllText($f.FullName, $content, $utf8NoBom)
        $changedFiles++
        $diff = ($original.Length - $content.Length)
        $totalChanges++
        Write-Host "  rewrite $($f.FullName.Substring($src.Length + 1))"
    }
}

Write-Host ""
Write-Host "Files changed: $changedFiles"
