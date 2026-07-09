param([string]$condition)

if ($condition -eq "A") {
    Copy-Item ".github\workflows\pipeline_manual.yml" ".github\workflows\pipeline.yml"
    Write-Host "Switched to Condition A - Manual"
}
elseif ($condition -eq "B") {
    Copy-Item ".github\workflows\pipeline_kiro_only.yml" ".github\workflows\pipeline.yml"
    Write-Host "Switched to Condition B - Kiro Only"
}
elseif ($condition -eq "C") {
    Copy-Item ".github\workflows\pipeline_kiro_repair.yml" ".github\workflows\pipeline.yml"
    Write-Host "Switched to Condition C - Kiro + Repair"
}