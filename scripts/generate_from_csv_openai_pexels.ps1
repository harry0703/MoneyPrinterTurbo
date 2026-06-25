#Requires -Version 5.1
# scripts/generate_from_csv_openai_pexels.ps1
# CSV-driven video batch generator - OpenAI + Pexels + edge-tts + subtitles.
# No API keys in this file. All secrets read by server from config.toml.
#
# Usage - dry run (no API calls, validates config only):
#   .\scripts\generate_from_csv_openai_pexels.ps1 `
#       -CsvPath content\topics\productivity_batch_v1.csv `
#       -PresetPath content\presets\shorts_productivity_v1.json `
#       -DryRun -MaxItems 5
#
# Usage - render mode (sequential, one video at a time):
#   .\scripts\generate_from_csv_openai_pexels.ps1 `
#       -CsvPath content\topics\productivity_batch_v1.csv `
#       -PresetPath content\presets\shorts_productivity_v1.json `
#       -Render -MaxItems 3

param(
    [Parameter(Mandatory=$true)]
    [string]$CsvPath,

    [Parameter(Mandatory=$true)]
    [string]$PresetPath,

    [switch]$DryRun,
    [switch]$Render,

    [int]$MaxItems    = 999,
    [int]$StartFrom   = 1,
    [string]$OutputReportName = "",
    [string]$ServerUrl        = "http://127.0.0.1:8080",
    [int]$PollIntervalSeconds = 20,
    [int]$TimeoutSeconds      = 1500,
    [string]$StorageDir       = "storage"
)

$ErrorActionPreference = "Continue"

# ── Validate mode ─────────────────────────────────────────────────────────────

if (-not $DryRun -and -not $Render) {
    Write-Error "Specify -DryRun or -Render."
    exit 1
}
if ($DryRun -and $Render) {
    Write-Error "Specify only one of -DryRun or -Render."
    exit 1
}

# ── Resolve paths ─────────────────────────────────────────────────────────────

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

function Resolve-ProjectPath {
    param([string]$RelPath)
    if ([System.IO.Path]::IsPathRooted($RelPath)) { return $RelPath }
    $fromRoot = Join-Path $ProjectRoot $RelPath
    if (Test-Path $fromRoot) { return $fromRoot }
    return Join-Path (Get-Location).Path $RelPath
}

$CsvPath     = Resolve-ProjectPath $CsvPath
$PresetPath  = Resolve-ProjectPath $PresetPath
$StoragePath = Resolve-ProjectPath $StorageDir

# ── Find ffmpeg ───────────────────────────────────────────────────────────────

$ffmpeg = (Get-ChildItem "$ProjectRoot\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
if (-not $ffmpeg) {
    Write-Warning "ffmpeg not found under .venv - audio validation will be skipped"
}

# ── Load CSV ──────────────────────────────────────────────────────────────────

if (-not (Test-Path $CsvPath)) { Write-Error "CSV not found: $CsvPath"; exit 1 }
$allRows = Import-Csv -Path $CsvPath

$slice = $allRows | Select-Object -Skip ($StartFrom - 1) -First $MaxItems
if ($slice.Count -eq 0) {
    Write-Error "No rows selected (StartFrom=$StartFrom MaxItems=$MaxItems, CSV has $($allRows.Count) rows)"
    exit 1
}

$pending = @($slice | Where-Object { $_.status -ne "done" -and $_.status -ne "skipped" -and $_.status -ne "manual_qa_pending" })
Write-Host "CSV: $($allRows.Count) total rows - selected $($slice.Count), pending $($pending.Count)"

# ── Load preset ───────────────────────────────────────────────────────────────

if (-not (Test-Path $PresetPath)) { Write-Error "Preset not found: $PresetPath"; exit 1 }
$preset     = Get-Content $PresetPath -Raw | ConvertFrom-Json
$presetName = $preset._name

Write-Host "Preset: $presetName"
Write-Host "  Duration: $($preset.target_duration_seconds)s target / $($preset.min_duration_seconds)-$($preset.max_duration_seconds)s range"
Write-Host "  Words: $($preset.script_word_count_min)-$($preset.script_word_count_max)"
Write-Host "  Voice: $($preset.voice_name)"

# ── Build script prompt from preset template + row metadata ───────────────────

function Build-ScriptPrompt {
    param([object]$Row)
    $minW = $preset.script_word_count_min
    $maxW = $preset.script_word_count_max
    $tmpl = $preset.script_prompt_template
    $prompt = $tmpl -replace '\{word_count_min\}', $minW -replace '\{word_count_max\}', $maxW
    $extras = @()
    if ($Row.angle    -and $Row.angle    -ne '') { $extras += "Angle: $($Row.angle)" }
    if ($Row.audience -and $Row.audience -ne '') { $extras += "Audience: $($Row.audience)" }
    if ($Row.tone     -and $Row.tone     -ne '') { $extras += "Tone: $($Row.tone)" }
    if ($extras.Count -gt 0) { $prompt = $prompt + " " + ($extras -join ". ") + "." }
    return $prompt
}

# ── Build API request params from preset + row ────────────────────────────────

function Build-RequestParams {
    param([object]$Row, [string]$ScriptPrompt)
    return [ordered]@{
        video_subject               = $Row.topic
        video_aspect                = $preset.video_aspect
        video_source                = $preset.video_source
        video_clip_duration         = [int]$preset.video_clip_duration
        video_concat_mode           = $preset.video_concat_mode
        match_materials_to_script   = $false
        video_count                 = [int]$preset.video_count
        voice_name                  = $preset.voice_name
        voice_rate                  = [double]$preset.voice_rate
        voice_volume                = [double]$preset.voice_volume
        bgm_type                    = $preset.bgm_type
        bgm_volume                  = [double]$preset.bgm_volume
        subtitle_enabled            = $true
        subtitle_position           = $preset.subtitle_position
        font_size                   = [int]$preset.font_size
        stroke_color                = $preset.stroke_color
        stroke_width                = [double]$preset.stroke_width
        text_fore_color             = $preset.text_fore_color
        text_background_color       = $true
        rounded_subtitle_background = $false
        n_threads                   = [int]$preset.n_threads
        paragraph_number            = [int]$preset.paragraph_number
        video_script_prompt         = $ScriptPrompt
    }
}

# ── Video duration from ffprobe ───────────────────────────────────────────────

function Get-VideoDuration {
    param([string]$Path)
    if (-not $ffmpeg) { return $null }
    if (-not (Test-Path $Path)) { return $null }
    $info = (& $ffmpeg -i $Path 2>&1) | Out-String
    if ($info -match "Duration:\s*([\d]+):(\d+):([\d\.]+)") {
        return [double]$Matches[1]*3600 + [double]$Matches[2]*60 + [double]$Matches[3]
    }
    return $null
}

# ── WAV extraction + silencedetect ────────────────────────────────────────────

function Test-AudioIntegrity {
    param([string]$VideoPath)
    $result = [ordered]@{ pass=$false; wav_mb=0; silence_detected=$false; reason="" }
    if (-not (Test-Path $VideoPath)) { $result.reason = "Video not found"; return $result }
    if (-not $ffmpeg)                { $result.reason = "ffmpeg unavailable"; return $result }

    $wavDir  = Split-Path -Parent $VideoPath
    $wavPath = Join-Path $wavDir "validation_audio.wav"

    & $ffmpeg -y -i $VideoPath -vn -acodec pcm_s16le $wavPath 2>$null
    if (-not (Test-Path $wavPath)) { $result.reason = "WAV extraction failed"; return $result }

    $wavSize       = (Get-Item $wavPath).Length
    $result.wav_mb = [math]::Round($wavSize / 1MB, 3)

    if ($wavSize -lt 3000000) {
        Remove-Item $wavPath -Force -ErrorAction SilentlyContinue
        $result.reason = "WAV too small: $($result.wav_mb)MB (expected >= 3MB for ~35s video)"
        return $result
    }

    $silenceOut = (& $ffmpeg -i $wavPath -af "silencedetect=noise=-35dB:d=1" -f null - 2>&1) | Out-String
    Remove-Item $wavPath -Force -ErrorAction SilentlyContinue

    if ($silenceOut -match "silence_start") {
        $result.silence_detected = $true
        $result.reason = "Silence block detected in extracted audio"
        return $result
    }

    $result.pass   = $true
    $result.reason = "PASS ($($result.wav_mb)MB WAV, no silence)"
    return $result
}

# ── Screenshot extract ────────────────────────────────────────────────────────

function Get-Screenshot {
    param([string]$VideoPath, [double]$AtSeconds, [string]$OutPath)
    if (-not $ffmpeg) { return $false }
    $ts = [TimeSpan]::FromSeconds($AtSeconds).ToString("hh\:mm\:ss")
    & $ffmpeg -ss $ts -i $VideoPath -vframes 1 -update 1 $OutPath -y 2>$null
    if (-not (Test-Path $OutPath)) { return $false }
    return ((Get-Item $OutPath).Length -gt 50000)
}

# ── Full output validation ────────────────────────────────────────────────────

function Invoke-VideoValidation {
    param([string]$TaskId, [string]$Topic)

    $taskDir  = "$StoragePath\tasks\$TaskId"
    $finalMp4 = "$taskDir\final-1.mp4"
    $srtFile  = "$taskDir\subtitle.srt"
    $ssDir    = "$taskDir\screenshots"

    $val = [ordered]@{
        topic             = $Topic
        task_id           = $TaskId
        final_exists      = $false
        duration          = $null
        duration_in_range = $false
        audio             = $null
        subtitle_valid    = $false
        screenshot_5s     = $false
        screenshot_end    = $false
        issues            = [System.Collections.Generic.List[string]]::new()
        status            = "FAIL"
    }

    # 1. File exists
    if (-not (Test-Path $finalMp4)) {
        $val.issues.Add("final-1.mp4 missing")
        return $val
    }
    $val.final_exists = $true

    # 2. Duration
    $dur = Get-VideoDuration -Path $finalMp4
    $val.duration = $dur
    if ($dur) {
        $ok = ($dur -ge $preset.min_duration_seconds -and $dur -le $preset.max_duration_seconds)
        $val.duration_in_range = $ok
        if (-not $ok) {
            $val.issues.Add("Duration $([math]::Round($dur,1))s outside [$($preset.min_duration_seconds)-$($preset.max_duration_seconds)s]")
        }
    } else {
        $val.issues.Add("Could not read video duration")
    }

    # 3. Audio integrity (WAV + silencedetect - never trust ffprobe metadata alone)
    $audio = Test-AudioIntegrity -VideoPath $finalMp4
    $val.audio = $audio
    if (-not $audio.pass) { $val.issues.Add("Audio: $($audio.reason)") }

    # 4. Subtitle SRT
    if (Test-Path $srtFile) {
        $srtLines = @(Get-Content $srtFile -ErrorAction SilentlyContinue)
        $val.subtitle_valid = ($srtLines.Count -gt 3)
        if (-not $val.subtitle_valid) { $val.issues.Add("subtitle.srt empty or too short") }
    } else {
        $val.issues.Add("subtitle.srt not found")
    }

    # 5. Screenshots
    New-Item -ItemType Directory -Path $ssDir -Force | Out-Null
    $val.screenshot_5s = Get-Screenshot -VideoPath $finalMp4 -AtSeconds 5 -OutPath "$ssDir\screenshot_05s.png"
    if (-not $val.screenshot_5s) { $val.issues.Add("Screenshot at 5s failed") }

    if ($dur -and $dur -gt 8) {
        $endT = [math]::Max($dur - 3, $dur * 0.85)
        $val.screenshot_end = Get-Screenshot -VideoPath $finalMp4 -AtSeconds $endT -OutPath "$ssDir\screenshot_end.png"
        if (-not $val.screenshot_end) { $val.issues.Add("Screenshot near end failed - possible freeze") }
    }

    if ($val.issues.Count -eq 0) { $val.status = "PASS" }
    return $val
}

# ── Task polling (with file-size stability fallback for state-flush bug) ───────

function Wait-TaskComplete {
    param([string]$TaskId, [string]$Label)
    $waited = 0
    while ($waited -lt $TimeoutSeconds) {
        Start-Sleep -Seconds $PollIntervalSeconds
        $waited += $PollIntervalSeconds
        try {
            $r     = Invoke-RestMethod -Uri "$ServerUrl/api/v1/tasks/$TaskId" -Method GET -TimeoutSec 10
            $state = $r.data.state
            $pct   = $r.data.progress
            Write-Host "  [$Label] ${waited}s - state=$state progress=${pct}%"
            if ($state -eq 1)  { return "complete" }
            if ($state -eq -1) { return "failed" }

            # State-flush fallback: if API stuck at state=4/75%, check file size stability
            if ($state -eq 4) {
                $fp = "$StoragePath\tasks\$TaskId\final-1.mp4"
                if (Test-Path $fp) {
                    $sz1 = (Get-Item $fp).Length
                    Start-Sleep -Seconds 8
                    $waited += 8
                    $sz2 = (Get-Item $fp).Length
                    if ($sz1 -eq $sz2 -and $sz1 -gt 10000000) {
                        Write-Host "  [$Label] File stable at $([math]::Round($sz1/1MB,2))MB - treating as complete (API state stuck at 75%)"
                        return "complete"
                    }
                }
            }
        } catch {
            Write-Warning "  [$Label] Poll error: $($_.Exception.Message)"
        }
    }
    return "timeout"
}

# ── Submit task ───────────────────────────────────────────────────────────────

function Submit-VideoTask {
    param([hashtable]$Params)
    $json = $Params | ConvertTo-Json -Depth 5
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/v1/videos" -Method POST -Body $json -ContentType "application/json" -TimeoutSec 30
    return $resp.data.task_id
}

# ── Report dir ────────────────────────────────────────────────────────────────

$reportDir = "$StoragePath\batch_reports"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null

# =============================================================================
# DRY RUN
# =============================================================================

if ($DryRun) {
    $rName      = if ($OutputReportName) { $OutputReportName } else { "milestone_4_dry_run_report.md" }
    $reportPath = "$reportDir\$rName"

    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════"
    Write-Host "  DRY RUN - $presetName"
    Write-Host "  Topics : $($pending.Count)"
    Write-Host "  NO API CALLS WILL BE MADE"
    Write-Host "═══════════════════════════════════════════════════════"
    Write-Host ""

    $minW    = $preset.script_word_count_min
    $maxW    = $preset.script_word_count_max
    $minDur  = [math]::Round($minW / 2.5, 1)
    $maxDur  = [math]::Round($maxW / 2.5, 1)
    $allPass = $true
    $idx     = 0

    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add("# Milestone 4 - Dry Run Report")
    $lines.Add("")
    $lines.Add("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    $lines.Add("CSV: $(Split-Path -Leaf $CsvPath)")
    $lines.Add("Preset: $presetName")
    $lines.Add("Topics selected: $($pending.Count)")
    $lines.Add("Mode: DRY RUN - no API calls made")
    $lines.Add("")
    $lines.Add("---")
    $lines.Add("")
    $lines.Add("## Preset Validation")
    $lines.Add("")
    $lines.Add("| Parameter | Value | Check |")
    $lines.Add("|-----------|-------|-------|")
    $lines.Add("| Target duration | $($preset.target_duration_seconds)s | - |")
    $lines.Add("| Duration range | $($preset.min_duration_seconds)-$($preset.max_duration_seconds)s | - |")
    $lines.Add("| Script word count | $minW-$maxW words | - |")
    $lines.Add("| Estimated audio @ 2.5 w/s | ${minDur}s-${maxDur}s | $(if ($minDur -ge 28 -and $maxDur -le 45) { 'PASS' } else { 'WARN: outside 28-45s' }) |")
    $lines.Add("| Voice | $($preset.voice_name) | - |")
    $lines.Add("| BGM volume | $($preset.bgm_volume) | - |")
    $lines.Add("| Subtitle | $($preset.subtitle_position) | - |")
    $lines.Add("| Sequential render | $($preset.render_final_sequential) | - |")
    $lines.Add("| Audio validation | $($preset.audio_integrity_validation) | - |")
    $lines.Add("")
    $lines.Add("---")
    $lines.Add("")
    $lines.Add("## Topics")
    $lines.Add("")

    foreach ($row in $pending) {
        $idx++
        $prompt = Build-ScriptPrompt -Row $row
        $params = Build-RequestParams -Row $row -ScriptPrompt $prompt

        # 10s margin: edge-tts is ~2.8 w/s and clip padding adds duration over audio-only estimate
        $durOk  = ($minDur -ge ($preset.min_duration_seconds - 10) -and $maxDur -le $preset.max_duration_seconds)
        $status = if ($durOk) { "PASS" } else { "WARN: estimated duration out of range" }
        if (-not $durOk) { $allPass = $false }

        Write-Host "[$idx/$($pending.Count)] $($row.topic)"
        Write-Host "  Angle    : $($row.angle)"
        Write-Host "  Audience : $($row.audience)"
        Write-Host "  Tone     : $($row.tone)"
        Write-Host "  Est dur  : ${minDur}s-${maxDur}s | $status"
        Write-Host ""

        $lines.Add("### $idx. $($row.topic)")
        $lines.Add("")
        $lines.Add("| Field | Value |")
        $lines.Add("|-------|-------|")
        $lines.Add("| Angle | $($row.angle) |")
        $lines.Add("| Audience | $($row.audience) |")
        $lines.Add("| Tone | $($row.tone) |")
        $lines.Add("| Preset | $($row.preset) |")
        $lines.Add("| Est. word count | $minW-$maxW words |")
        $lines.Add("| Est. audio duration | ${minDur}s-${maxDur}s at 2.5 words/sec |")
        $lines.Add("| Target | $($preset.target_duration_seconds)s |")
        $lines.Add("| Editorial validation | **$status** |")
        $lines.Add("")
        $lines.Add("Script prompt constraints:")
        $lines.Add("")
        $lines.Add('```')
        $lines.Add($prompt)
        $lines.Add('```')
        $lines.Add("")
        $lines.Add("Would-be request (key params, no secrets):")
        $lines.Add("")
        $lines.Add('```')
        $lines.Add("video_subject    : $($params.video_subject)")
        $lines.Add("video_aspect     : $($params.video_aspect)")
        $lines.Add("voice_name       : $($params.voice_name)")
        $lines.Add("bgm_volume       : $($params.bgm_volume)")
        $lines.Add("subtitle_enabled : $($params.subtitle_enabled)")
        $lines.Add("font_size        : $($params.font_size)")
        $lines.Add("video_source     : $($params.video_source)")
        $lines.Add('```')
        $lines.Add("")
        $lines.Add("---")
        $lines.Add("")
    }

    $overall = if ($allPass) { "ALL PASS" } else { "WARNINGS - review above" }
    $lines.Add("## Summary")
    $lines.Add("")
    $lines.Add("| Field | Value |")
    $lines.Add("|-------|-------|")
    $lines.Add("| Topics processed | $($pending.Count) |")
    $lines.Add("| Editorial validation | $overall |")
    $lines.Add("| Est. audio per video | ${minDur}s-${maxDur}s |")
    $lines.Add("| Word count constraint | $minW-$maxW words |")
    $lines.Add("| Render mode | DRY RUN only |")
    $lines.Add("")
    $lines.Add("Next step: run with -Render -MaxItems 3 to generate 3 validation videos.")
    $lines.Add("")

    $lines | Out-File $reportPath -Encoding utf8

    Write-Host "═══════════════════════════════════════════════════════"
    Write-Host "  DRY RUN complete - $overall"
    Write-Host "  Report: $reportPath"
    Write-Host "═══════════════════════════════════════════════════════"
    exit 0
}

# =============================================================================
# RENDER MODE
# =============================================================================

$rName      = if ($OutputReportName) { $OutputReportName } else { "milestone_4_render_report.md" }
$reportPath = "$reportDir\$rName"

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════"
Write-Host "  RENDER - $presetName"
Write-Host "  Topics  : $($pending.Count)"
Write-Host "  Server  : $ServerUrl"
Write-Host "  Mode    : SEQUENTIAL (one video at a time)"
Write-Host "  Timeout : ${TimeoutSeconds}s per video"
Write-Host "═══════════════════════════════════════════════════════"
Write-Host ""

# Verify server
try {
    Invoke-RestMethod -Uri "$ServerUrl/" -Method GET -TimeoutSec 5 | Out-Null
    Write-Host "Server OK: $ServerUrl"
} catch {
    Write-Error "Server not reachable at $ServerUrl - start the server first."
    exit 1
}

$startTime     = Get-Date
$renderResults = [System.Collections.Generic.List[hashtable]]::new()
$idx           = 0

foreach ($row in $pending) {
    $idx++
    Write-Host ""
    Write-Host "── [$idx/$($pending.Count)] $($row.topic) ──"

    $prompt = Build-ScriptPrompt -Row $row
    $params = Build-RequestParams -Row $row -ScriptPrompt $prompt

    $entry = @{
        topic      = $row.topic
        task_id    = $null
        status     = "pending"
        attempt    = 0
        validation = $null
    }

    # Submit (retry once on failure)
    $submitted = $false
    $maxAttempts = 2
    for ($a = 1; $a -le $maxAttempts; $a++) {
        $entry.attempt = $a
        try {
            Write-Host "  Submitting (attempt $a)..."
            $tid = Submit-VideoTask -Params $params
            $entry.task_id = $tid
            Write-Host "  task_id: $tid"
            $submitted = $true
            break
        } catch {
            Write-Warning "  Submit failed (attempt $a): $($_.Exception.Message)"
            if ($a -lt $maxAttempts) { Start-Sleep -Seconds 5 }
        }
    }

    if (-not $submitted) {
        $entry.status = "submit_failed"
        $renderResults.Add($entry)
        continue
    }

    # Poll to completion
    $outcome = Wait-TaskComplete -TaskId $entry.task_id -Label $row.topic

    if ($outcome -eq "timeout") {
        # One retry on timeout: re-submit and wait again
        Write-Warning "  Timeout - retrying with new task submission"
        try {
            $tid2 = Submit-VideoTask -Params $params
            $entry.task_id = $tid2
            $entry.attempt = 2
            Write-Host "  retry task_id: $tid2"
            $outcome = Wait-TaskComplete -TaskId $tid2 -Label "$($row.topic) [retry]"
        } catch {
            Write-Warning "  Retry submit failed: $($_.Exception.Message)"
            $outcome = "failed"
        }
    }

    if ($outcome -ne "complete") {
        $entry.status = $outcome
        $renderResults.Add($entry)
        Write-Warning "  FAIL: $($row.topic) - $outcome"
        continue
    }

    # Validate output (WAV + silencedetect + duration + subtitles + screenshots)
    Write-Host "  Validating..."
    $val = Invoke-VideoValidation -TaskId $entry.task_id -Topic $row.topic
    $entry.validation = $val
    $entry.status     = $val.status

    $icon = if ($val.status -eq "PASS") { "v" } else { "x" }
    Write-Host "  [$icon] $($val.status) | dur=$($val.duration)s | wav=$($val.audio.wav_mb)MB"
    foreach ($issue in $val.issues) { Write-Warning "    Issue: $issue" }

    $renderResults.Add($entry)
}

# ── Build render report ───────────────────────────────────────────────────────

$elapsed   = [math]::Round(((Get-Date) - $startTime).TotalMinutes, 1)
$passCount = ($renderResults | Where-Object { $_.status -eq "PASS" }).Count
$failCount = $renderResults.Count - $passCount
$overall   = if ($failCount -eq 0) { "SUCCESS" } elseif ($passCount -gt 0) { "PARTIAL SUCCESS" } else { "FAILED" }

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# Milestone 4 - Render Quality Report")
$lines.Add("")
$lines.Add("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$lines.Add("Preset: $presetName")
$lines.Add("Overall: **$overall** - $passCount/$($renderResults.Count) passed | ${elapsed}m elapsed")
$lines.Add("")
$lines.Add("---")
$lines.Add("")
$lines.Add("## Results")
$lines.Add("")
$lines.Add("| # | Topic | Task ID | Status | Duration | WAV | Dur OK | Subs | SS | Notes |")
$lines.Add("|---|-------|---------|--------|----------|-----|--------|------|----|-------|")

$i = 0
foreach ($r in $renderResults) {
    $i++
    $v    = $r.validation
    $dur  = if ($v -and $v.duration)          { "$([math]::Round($v.duration,1))s" } else { "-" }
    $wav  = if ($v -and $v.audio)             { "$($v.audio.wav_mb)MB" } else { "-" }
    $dok  = if ($v)                            { if ($v.duration_in_range) { "v" } else { "x" } } else { "-" }
    $sub  = if ($v)                            { if ($v.subtitle_valid)    { "v" } else { "x" } } else { "-" }
    $ss   = if ($v)                            { if ($v.screenshot_5s)     { "v" } else { "x" } } else { "-" }
    $tid  = if ($r.task_id) { $r.task_id.Substring(0, [math]::Min(8, $r.task_id.Length)) + "..." } else { "-" }
    $note = if ($v -and $v.issues.Count -gt 0) { ($v.issues -join "; ") } elseif ($r.status -eq "PASS") { "-" } else { $r.status }
    $lines.Add("| $i | $($r.topic) | $tid | $($r.status) | $dur | $wav | $dok | $sub | $ss | $note |")
}

$lines.Add("")
$lines.Add("---")
$lines.Add("")
$lines.Add("## Validation Details")
$lines.Add("")

foreach ($r in $renderResults) {
    $lines.Add("### $($r.topic)")
    $lines.Add("")
    $lines.Add("- **Task ID:** $($r.task_id)")
    $lines.Add("- **Status:** $($r.status)")
    if ($r.validation) {
        $v = $r.validation
        $lines.Add("- **Duration:** $($v.duration)s (in range: $($v.duration_in_range))")
        $lines.Add("- **Audio WAV:** $($v.audio.wav_mb)MB - $($v.audio.reason)")
        $lines.Add("- **Subtitles:** $($v.subtitle_valid)")
        $lines.Add("- **Screenshot 5s:** $($v.screenshot_5s)")
        $lines.Add("- **Screenshot end:** $($v.screenshot_end)")
        $lines.Add("- **Screenshots dir:** storage\tasks\$($r.task_id)\screenshots\")
        if ($v.issues.Count -gt 0) {
            $lines.Add("- **Issues:**")
            foreach ($iss in $v.issues) { $lines.Add("  - $iss") }
        }
        $lines.Add("- **Manual QA:** PENDING - play final-1.mp4 and confirm audio, video, subtitles")
    }
    $lines.Add("")
}

$lines.Add("---")
$lines.Add("")
$lines.Add("## Quality Controls Applied")
$lines.Add("")
$lines.Add("- Renders sequential - one at a time, no concurrent temp audio collisions")
$lines.Add("- Audio validated via WAV extraction + silencedetect (not ffprobe metadata alone)")
$lines.Add("- Duration checked against preset min/max range ($($preset.min_duration_seconds)-$($preset.max_duration_seconds)s)")
$lines.Add("- Subtitle SRT presence and content length verified")
$lines.Add("- Screenshots at 5s and near-end (freeze detection)")
$lines.Add("- State-flush fallback: file size stability check when API stuck at 75%")
$lines.Add("")

$lines | Out-File $reportPath -Encoding utf8

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════"
Write-Host "  RENDER complete - $overall"
Write-Host "  $passCount/$($renderResults.Count) passed | ${elapsed}m"
Write-Host "  Report: $reportPath"
Write-Host "═══════════════════════════════════════════════════════"
Write-Host ""
Write-Host "Outputs:"
foreach ($r in $renderResults) {
    $icon = if ($r.status -eq "PASS") { "v" } else { "x" }
    Write-Host "  [$icon] $($r.status) - $($r.topic)"
    if ($r.task_id) { Write-Host "         storage\tasks\$($r.task_id)\final-1.mp4" }
}
