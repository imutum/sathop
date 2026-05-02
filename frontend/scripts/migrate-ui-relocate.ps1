# Phase 4 final: relocate ui/ files to their semantic homes.
# - components/ : business-agnostic composites (EmptyState, PageHeader, Stat, etc.)
# - features/nodes/components/ : node-specific (NodeLifecycleActions)
# - lib/ : pure utility modules (format)
# Stays in ui/ : shadcn-vue extensions (Modal, TextInput, SelectInput,
# TextareaInput, ConfirmDialog).

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Resolve-Path "$PSScriptRoot\..\src"

$moves = @(
    @{ From = "$root\ui\EmptyState.vue";          To = "$root\components\EmptyState.vue" }
    @{ From = "$root\ui\PageHeader.vue";          To = "$root\components\PageHeader.vue" }
    @{ From = "$root\ui\Field.vue";               To = "$root\components\Field.vue" }
    @{ From = "$root\ui\FieldLabel.vue";          To = "$root\components\FieldLabel.vue" }
    @{ From = "$root\ui\Stat.vue";                To = "$root\components\Stat.vue" }
    @{ From = "$root\ui\ProgressBar.vue";         To = "$root\components\ProgressBar.vue" }
    @{ From = "$root\ui\Segmented.vue";           To = "$root\components\Segmented.vue" }
    @{ From = "$root\ui\FilePicker.vue";          To = "$root\components\FilePicker.vue" }
    @{ From = "$root\ui\CopyButton.vue";          To = "$root\components\CopyButton.vue" }
    @{ From = "$root\ui\Icon.ts";                 To = "$root\components\Icon.ts" }
    @{ From = "$root\ui\NodeLifecycleActions.vue"; To = "$root\features\nodes\components\NodeLifecycleActions.vue" }
    @{ From = "$root\ui\format.ts";               To = "$root\lib\format.ts" }
)

foreach ($m in $moves) {
    if (Test-Path $m.From) {
        $destDir = Split-Path -Parent $m.To
        if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Force -Path $destDir | Out-Null }
        Move-Item -Force -Path $m.From -Destination $m.To
        Write-Host "moved: $($m.From) -> $($m.To)"
    }
}

# Import path rewrites. Run against every .vue and .ts file under src/.
$rewrites = @(
    @{ Old = '@/ui/EmptyState.vue';           New = '@/components/EmptyState.vue' }
    @{ Old = '@/ui/PageHeader.vue';           New = '@/components/PageHeader.vue' }
    @{ Old = '@/ui/Field.vue';                New = '@/components/Field.vue' }
    @{ Old = '@/ui/FieldLabel.vue';           New = '@/components/FieldLabel.vue' }
    @{ Old = '@/ui/Stat.vue';                 New = '@/components/Stat.vue' }
    @{ Old = '@/ui/ProgressBar.vue';          New = '@/components/ProgressBar.vue' }
    @{ Old = '@/ui/Segmented.vue';            New = '@/components/Segmented.vue' }
    @{ Old = '@/ui/FilePicker.vue';           New = '@/components/FilePicker.vue' }
    @{ Old = '@/ui/CopyButton.vue';           New = '@/components/CopyButton.vue' }
    @{ Old = '@/ui/Icon';                     New = '@/components/Icon' }
    @{ Old = '@/ui/NodeLifecycleActions.vue'; New = '@/features/nodes/components/NodeLifecycleActions.vue' }
    @{ Old = '@/ui/format';                   New = '@/lib/format' }
)

$utf8 = New-Object System.Text.UTF8Encoding($false)
$files = Get-ChildItem -Recurse -Path $root -Include *.vue, *.ts | Where-Object { -not $_.PSIsContainer }
$touched = 0
foreach ($f in $files) {
    $orig = [System.IO.File]::ReadAllText($f.FullName, $utf8)
    $next = $orig
    foreach ($r in $rewrites) {
        $next = $next.Replace($r.Old, $r.New)
    }
    if ($next -ne $orig) {
        [System.IO.File]::WriteAllText($f.FullName, $next, $utf8)
        Write-Host "rewrote imports: $($f.FullName)"
        $touched++
    }
}

# After move, FilePicker (now at components/) used `./format` relative — but
# format is now under lib/. Rewrite that single relative import.
$filePickerPath = "$root\components\FilePicker.vue"
if (Test-Path $filePickerPath) {
    $orig = [System.IO.File]::ReadAllText($filePickerPath, $utf8)
    $next = $orig.Replace('./format', '@/lib/format')
    if ($next -ne $orig) {
        [System.IO.File]::WriteAllText($filePickerPath, $next, $utf8)
        Write-Host "rewrote FilePicker.vue ./format -> @/lib/format"
        $touched++
    }
}

Write-Host "`nDone. Moved $($moves.Count) files, rewrote imports in $touched files."
