package services

import (
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/harry0703/moneyprinterturbo/go/internal/models"
	"github.com/harry0703/moneyprinterturbo/go/internal/utils"
)

// GenerateFinalVideos 对应 Python generate_final_videos：先拼接画面，再混音/字幕/BGM。
// AI 配乐失败只降级为无 BGM，并写入警告，不让已经生成的画面作废。
func GenerateFinalVideos(taskID string, params models.VideoParams, materials []string, audioFile, subPath string, audioDur float64, progress func(int)) (videos []string, combined []string, warnings []any, err error) {
	if len(materials) == 0 {
		return nil, nil, nil, fmt.Errorf("empty materials")
	}
	music, isMusic := VideoMusicProvider(params.BGMType)
	musicRequested := isMusic && ShouldUseBGM(params.BGMType, params.BGMVolume)
	concatMode := params.VideoConcatMode
	if params.MatchMaterialsToScript {
		concatMode = models.ConcatSequential
	} else if params.VideoCount > 1 {
		concatMode = models.ConcatRandom
	}

	count := params.VideoCount
	if count < 1 {
		count = 1
	}
	pct := 50.0
	for i := 1; i <= count; i++ {
		visual, err := combineVideos(taskID, i, params, materials, audioDur, concatMode)
		if err != nil {
			return videos, combined, warnings, err
		}
		combined = append(combined, visual)
		pct += 50 / float64(count) / 2
		if progress != nil {
			progress(int(pct))
		}

		bgmOverride := ""
		useOverride := false
		if isMusic {
			useOverride = true
			bgmOverride = ""
		}
		if musicRequested {
			out := filepath.Join(utils.TaskDir(taskID), fmt.Sprintf("%s-bgm-%d%s", params.BGMType, i, music.Suffix))
			if genErr := music.Generate(visual, out, audioDur, params.VideoMusicPromptText()); genErr != nil {
				slog.Warn("AI BGM generation failed, continue without BGM", "provider", music.DisplayName, "error", genErr)
				bgmOverride = ""
				warnings = append(warnings, models.MusicWarning(music.WarningCode, i))
			} else {
				bgmOverride = out
			}
		}

		finalPath := filepath.Join(utils.TaskDir(taskID), fmt.Sprintf("final-%d.mp4", i))
		ok, mixErr := mixFinalVideo(visual, audioFile, subPath, finalPath, params, bgmOverride, useOverride)
		if mixErr != nil {
			return videos, combined, warnings, mixErr
		}
		if isMusic && bgmOverride != "" && !ok {
			warnings = append(warnings, models.MusicWarning(music.WarningCode, i))
		}
		videos = append(videos, finalPath)
		pct += 50 / float64(count) / 2
		if progress != nil {
			progress(int(pct))
		}
	}
	return videos, combined, warnings, nil
}

func combineVideos(taskID string, index int, params models.VideoParams, materials []string, audioDur float64, mode models.VideoConcatMode) (string, error) {
	dir := utils.TaskDir(taskID)
	w, h, err := params.VideoAspect.Resolution()
	if params.VideoAspect == "" {
		w, h, err = models.AspectPortrait.Resolution()
	}
	if err != nil {
		return "", err
	}
	clipDur := params.VideoClipDuration
	if clipDur < 1 {
		clipDur = 5
	}
	need := audioDur
	if need <= 0 {
		need = float64(clipDur * len(materials))
	}
	listFile := filepath.Join(dir, fmt.Sprintf("concat-%d.txt", index))
	if err := writeConcatList(listFile, materials, clipDur, need, mode, params.VideoClipSpeed); err != nil {
		return "", err
	}
	visual := filepath.Join(dir, fmt.Sprintf("combined-%d.mp4", index))
	threads := params.NThreads
	if threads < 1 {
		threads = 2
	}
	if err := runFFmpeg(
		"-y", "-f", "concat", "-safe", "0", "-i", listFile,
		"-vf", fmt.Sprintf("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d", w, h, w, h),
		"-r", "30", "-an", "-threads", fmt.Sprintf("%d", threads), visual,
	); err != nil {
		return "", err
	}
	return visual, nil
}

func mixFinalVideo(visual, audioPath, subtitlePath, output string, params models.VideoParams, bgmOverride string, useOverride bool) (bool, error) {
	bgmFile := ""
	if useOverride {
		bgmFile = bgmOverride
	} else if ShouldUseBGM(params.BGMType, params.BGMVolume) {
		resolved, err := ResolveBGM(params.BGMType, params.BGMFile)
		if err != nil {
			slog.Warn("resolve BGM failed, continue without BGM", "error", err)
		} else {
			bgmFile = resolved
		}
	}

	args := []string{"-y", "-i", visual, "-i", audioPath}
	filter := ""
	if params.SubtitlesOn() && subtitlePath != "" {
		escaped := escapeSubtitlePath(subtitlePath)
		filter = fmt.Sprintf("subtitles='%s'", escaped)
	}
	mixedBGM := bgmFile != "" && params.BGMVolume > 0
	if mixedBGM {
		args = append(args, "-i", bgmFile)
		if filter != "" {
			args = append(args, "-vf", filter)
		}
		args = append(args,
			"-filter_complex",
			fmt.Sprintf("[1:a]volume=%.2f[a0];[2:a]volume=%.2f[a1];[a0][a1]amix=inputs=2:duration=first[a]", params.VoiceVolume, params.BGMVolume),
			"-map", "0:v", "-map", "[a]",
		)
	} else {
		if filter != "" {
			args = append(args, "-vf", filter)
		}
		args = append(args, "-filter_complex", fmt.Sprintf("[1:a]volume=%.2f[a]", params.VoiceVolume), "-map", "0:v", "-map", "[a]")
	}
	args = append(args, "-c:v", "libx264", "-shortest", output)
	if err := runFFmpeg(args...); err != nil {
		if mixedBGM {
			// 混音失败时再出一条无 BGM 成片，与 Python 保留无 BGM 产物一致。
			slog.Warn("BGM mix failed, retry without BGM", "error", err)
			return mixFinalVideo(visual, audioPath, subtitlePath, output, params, "", true)
		}
		return false, err
	}
	return mixedBGM, nil
}

func escapeSubtitlePath(path string) string {
	p := filepath.ToSlash(path)
	p = strings.ReplaceAll(p, ":", "\\:")
	p = strings.ReplaceAll(p, "'", "\\'")
	return p
}

func writeConcatList(path string, materials []string, clipDur int, need float64, mode models.VideoConcatMode, speed float64) error {
	speed = utils.NormalizeClipSpeed(speed, 1)
	effective := float64(clipDur) / speed
	if effective < 0.2 {
		effective = 0.2
	}
	var b strings.Builder
	used := 0.0
	idx := 0
	for used < need {
		src := materials[idx%len(materials)]
		fmt.Fprintf(&b, "file '%s'\n", filepath.ToSlash(src))
		fmt.Fprintf(&b, "duration %.3f\n", effective)
		used += effective
		idx++
		if mode == models.ConcatSequential && idx >= len(materials) && used < need {
			idx = 0
		}
	}
	return os.WriteFile(path, []byte(b.String()), 0o644)
}

func runFFmpeg(args ...string) error {
	cmd := exec.Command(utils.FFmpegBinary(), args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("ffmpeg: %w: %s", err, string(out))
	}
	return nil
}
