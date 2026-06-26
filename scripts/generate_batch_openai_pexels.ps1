# scripts/generate_batch_openai_pexels.ps1
# Batch video generation: OpenAI (script + terms) + Pexels (footage) + edge-tts + subtitles
# No secrets. API keys are read by the server from config.toml.
#
# Usage:
#   .\scripts\generate_batch_openai_pexels.ps1
#   .\scripts\generate_batch_openai_pexels.ps1 -Topics "Topic A","Topic B"
#   .\scripts\generate_batch_openai_pexels.ps1 -ServerUrl "http://127.0.0.1:8080" -PollIntervalSeconds 20

param(
    [string[]]$Topics = @(
        "The Power of Consistency",
        "Why Motivation Is Overrated",
        "How to Focus in a Distracted World",
        "Small Habits That Compound Over Time",
        "How AI Can Help You Work Smarter"
    ),
    [string]$ServerUrl     = "http://127.0.0.1:8080",
    [int]$PollIntervalSeconds = 20,
    [int]$TimeoutSeconds      = 1200,
    [string]$ReportDir        = "storage\batch_reports"
)

$ErrorActionPreference = "Continue"

# Script-length constraint injected as "Additional User Requirements" into the LLM prompt.
# Targeting 75-90 words so TTS audio lands at 35-42 seconds at natural pace.
$ScriptConstraint = @"
Write exactly 75 to 90 words total. No more.
Start with a strong hook sentence that grabs attention immediately.
Use short, punchy sentences throughout.
Sound like a confident voiceover narrator, not an essay.
No motivational clichés ("believe in yourself", "chase your dreams", etc.).
No filler openers ("In today's world", "Have you ever wondered").
No markdown, no titles, no formatting. Plain narration text only.
"@

$BaseParams = [ordered]@{
    video_aspect              = "9:16"
    video_source              = "pexels"
    video_clip_duration       = 5
    video_concat_mode         = "random"
    match_materials_to_script = $false
    video_count               = 1
    voice_name                = "en-US-AndrewNeural"
    voice_rate                = 1.0
    voice_volume              = 1.0
    bgm_type                  = "random"
    bgm_volume                = 0.12
    subtitle_enabled          = $true
    subtitle_position         = "bottom"
    font_size                 = 60
    stroke_color              = "#000000"
    stroke_width              = 1.5
    text_fore_color           = "#FFFFFF"
    text_background_color     = $true
    rounded_subtitle_background = $false
    n_threads                 = 2
    paragraph_number          = 1
    video_script_prompt       = $ScriptConstraint
}

# ── Validation ───────────────────────────────────────────────────────────────

function Test-VideoOutput {
    param([string]$TaskDir, [string]$FfmpegPath)
    $result = [ordered]@{
        valid          = $false
        final_exists   = $false
        video_duration = $null
        audio_duration = $null
        duration_gap   = $null
        subtitle_end   = $null
        screenshot_ok  = $false
        issues         = @()
    }

    $finalMp4 = "$TaskDir\final-1.mp4"
    $audioMp3 = "$TaskDir\audio.mp3"
    $srtFile  = "$TaskDir\subtitle.srt"
    $ssFile   = "$TaskDir\validation_ss.png"

    # 1. File exists
    if (-not (Test-Path $finalMp4)) { $result.issues += "final-1.mp4 missing"; return $result }
    $result.final_exists = $true

    # 2. Video and audio stream durations
    $raw = (& $FfmpegPath -i $finalMp4 2>&1) | Out-String
    if ($raw -match "Duration:\s*([\d:\.]+)") {
        $ts = $Matches[1]; $parts = $ts -split '[:.]'
        $result.video_duration = [double]$parts[0]*3600 + [double]$parts[1]*60 + [double]$parts[2] + [double]("0." + $parts[3])
    }
    if (Test-Path $audioMp3) {
        $rawMp3 = (& $FfmpegPath -i $audioMp3 2>&1) | Out-String
        if ($rawMp3 -match "Duration:\s*([\d:\.]+)") {
            $ts = $Matches[1]; $parts = $ts -split '[:.]'
            $result.audio_duration = [double]$parts[0]*3600 + [double]$parts[1]*60 + [double]$parts[2] + [double]("0." + $parts[3])
        }
    }

    # 3. Duration gap check (audio vs video must be within 1 second)
    if ($result.video_duration -and $result.audio_duration) {
        $result.duration_gap = [math]::Round($result.video_duration - $result.audio_duration, 3)
        if ([math]::Abs($result.duration_gap) -gt 1.0) {
            $result.issues += "DURATION_MISMATCH: video=$($result.video_duration)s audio=$($result.audio_duration)s gap=$($result.duration_gap)s"
        }
    }

    # 4. Subtitle end timestamp check
    if (Test-Path $srtFile) {
        $lastTs = (Get-Content $srtFile | Where-Object { $_ -match '\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}' } | Select-Object -Last 1)
        if ($lastTs -match '--> (\d{2}):(\d{2}):(\d{2}),(\d{3})') {
            $result.subtitle_end = [double]$Matches[1]*3600 + [double]$Matches[2]*60 + [double]$Matches[3] + [double]$Matches[4]/1000
            if ($result.video_duration -and ($result.subtitle_end - $result.video_duration) -gt 1.0) {
                $result.issues += "SUBTITLE_OVERFLOW: subtitle ends $($result.subtitle_end)s but video is $($result.video_duration)s"
            }
        }
    }

    # 5. Screenshot extractable (confirms real decodable frames, not placeholder)
    & $FfmpegPath -ss 00:00:05 -i $finalMp4 -vframes 1 -update 1 $ssFile -y 2>$null
    if (Test-Path $ssFile) {
        $sz = (Get-Item $ssFile).Length
        if ($sz -gt 50000) { $result.screenshot_ok = $true }
        else { $result.issues += "SCREENSHOT_TOO_SMALL: $sz bytes (possible placeholder)" }
        Remove-Item $ssFile -Force -ErrorAction SilentlyContinue
    } else {
        $result.issues += "SCREENSHOT_FAILED: could not extract frame at 5s"
    }

    $result.valid = ($result.issues.Count -eq 0)
    return $result
}

# ── Helpers ───────────────────────────────────────────────────────────────────

function Get-VideoInfo {
    param([string]$Path)
    $ffmpeg = (Get-ChildItem "$PSScriptRoot\..\\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
    if (-not $ffmpeg) { return $null }
    $info = & $ffmpeg -i $Path 2>&1 | Out-String
    $dur = if ($info -match 'Duration:\s*([\d:\.]+)') { $Matches[1] } else { "unknown" }
    return $dur
}

function Submit-VideoTask {
    param([string]$Topic)
    $body = [ordered]@{}
    foreach ($k in $BaseParams.Keys) { $body[$k] = $BaseParams[$k] }
    $body["video_subject"] = $Topic
    $json = $body | ConvertTo-Json -Depth 5
    $resp = Invoke-RestMethod -Uri "$ServerUrl/api/v1/videos" -Method POST `
        -Body $json -ContentType "application/json" -TimeoutSec 30
    return $resp.data.task_id
}

function Wait-VideoTask {
    param([string]$TaskId, [string]$Label)
    $waited = 0
    while ($waited -lt $TimeoutSeconds) {
        Start-Sleep -Seconds $PollIntervalSeconds
        $waited += $PollIntervalSeconds
        $r = Invoke-RestMethod -Uri "$ServerUrl/api/v1/tasks/$TaskId" -Method GET -TimeoutSec 10
        $state = $r.data.state; $pct = $r.data.progress
        Write-Host "  [$Label] ${waited}s — state=$state progress=${pct}%"
        if ($state -eq 1)  { return "complete" }
        if ($state -eq -1) { return "failed" }
    }
    return "timeout"
}

# ── Main ─────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "════════════════════════════════════════════════════"
Write-Host "  MoneyPrinterTurbo — Batch Generator"
Write-Host "  Topics : $($Topics.Count)"
Write-Host "  Server : $ServerUrl"
Write-Host "  Target : 35-45 seconds per video"
Write-Host "════════════════════════════════════════════════════"
Write-Host ""

$startTime = Get-Date
$results   = [System.Collections.Generic.List[hashtable]]::new()

# Phase 1 — Submit all tasks
Write-Host "── Phase 1: Submitting $($Topics.Count) tasks ──"
foreach ($topic in $Topics) {
    $entry = @{
        topic     = $topic
        task_id   = $null
        status    = "pending"
        duration  = $null
        video_path = $null
        error     = $null
        attempt   = 0
    }
    try {
        Write-Host "  Submitting: $topic"
        $entry.task_id = Submit-VideoTask -Topic $topic
        $entry.status  = "submitted"
        $entry.attempt = 1
        Write-Host "  → task_id: $($entry.task_id)"
    } catch {
        $entry.status = "submit_failed"
        $entry.error  = $_.Exception.Message
        Write-Warning "  FAILED to submit '$topic': $($entry.error)"
    }
    $results.Add($entry)
    Start-Sleep -Seconds 2
}

Write-Host ""

# Phase 2 — Poll all submitted tasks
Write-Host "── Phase 2: Polling tasks until complete ──"
$submitted = $results | Where-Object { $_.status -eq "submitted" }
Write-Host "  Monitoring $($submitted.Count) tasks (timeout ${TimeoutSeconds}s each)"

foreach ($entry in $submitted) {
    Write-Host ""
    Write-Host "  Waiting for: $($entry.topic)"
    $outcome = Wait-VideoTask -TaskId $entry.task_id -Label $entry.topic

    if ($outcome -eq "complete") {
        $entry.status = "complete"
        $taskDir = "storage\tasks\$($entry.task_id)"
        $vidPath = "$taskDir\final-1.mp4"
        if (Test-Path $vidPath) {
            $entry.video_path = $vidPath
            $entry.duration   = Get-VideoInfo -Path $vidPath
        } else {
            $entry.status = "complete_no_file"
        }
        Write-Host "  ✓ DONE — $($entry.video_path) [$($entry.duration)]"
    } elseif ($outcome -eq "failed") {
        # Retry once
        if ($entry.attempt -lt 2) {
            Write-Warning "  Task failed — retrying once for: $($entry.topic)"
            try {
                $entry.task_id = Submit-VideoTask -Topic $entry.topic
                $entry.attempt = 2
                $entry.status  = "submitted"
                $outcome2 = Wait-VideoTask -TaskId $entry.task_id -Label "$($entry.topic) [retry]"
                if ($outcome2 -eq "complete") {
                    $entry.status = "complete"
                    $taskDir = "storage\tasks\$($entry.task_id)"
                    $vidPath = "$taskDir\final-1.mp4"
                    if (Test-Path $vidPath) {
                        $entry.video_path = $vidPath
                        $entry.duration   = Get-VideoInfo -Path $vidPath
                    }
                    Write-Host "  ✓ RETRY OK — $($entry.video_path)"
                } else {
                    $entry.status = "failed"
                    Write-Warning "  ✗ Retry also failed for: $($entry.topic)"
                }
            } catch {
                $entry.status = "failed"
                $entry.error  = $_.Exception.Message
            }
        } else {
            $entry.status = "failed"
            Write-Warning "  ✗ FAILED: $($entry.topic)"
        }
    } else {
        $entry.status = "timeout"
        Write-Warning "  ✗ TIMEOUT: $($entry.topic)"
    }
}

# Phase 3 — Save summary
$elapsed     = [math]::Round(((Get-Date) - $startTime).TotalMinutes, 1)
$successCount = ($results | Where-Object { $_.status -eq "complete" }).Count
$failedCount  = ($results | Where-Object { $_.status -ne "complete" }).Count

New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null
$reportDate = (Get-Date).ToString("yyyy-MM-dd_HHmm")
$reportPath = "$ReportDir\batch_$reportDate.json"

$summary = @{
    generated_at   = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    server         = $ServerUrl
    total          = $results.Count
    succeeded      = $successCount
    failed         = $failedCount
    elapsed_minutes = $elapsed
    videos         = $results | ForEach-Object {
        @{
            topic      = $_.topic
            task_id    = $_.task_id
            status     = $_.status
            duration   = $_.duration
            video_path = $_.video_path
            attempts   = $_.attempt
        }
    }
}

$summary | ConvertTo-Json -Depth 5 | Out-File $reportPath -Encoding utf8
Write-Host ""
Write-Host "════════════════════════════════════════════════════"
Write-Host "  Batch complete — $successCount/$($results.Count) succeeded in ${elapsed}m"
Write-Host "  Report: $reportPath"
Write-Host "════════════════════════════════════════════════════"

# Phase 4 — Print final paths
Write-Host ""
Write-Host "── Final Outputs ──"
foreach ($r in $results) {
    $icon = if ($r.status -eq "complete") { "✓" } else { "✗" }
    Write-Host "  $icon [$($r.status)] $($r.topic)"
    if ($r.video_path) { Write-Host "      → $($r.video_path) [$($r.duration)]" }
    if ($r.error)      { Write-Host "      ! $($r.error)" }
}
