// Package state 对应 app/services/state.py：进程内任务状态存储。
package state

import (
	"sync"

	"github.com/harry0703/moneyprinterturbo/go/internal/models"
)

// Store 进程内任务状态表。Go 版暂不接 Redis，API 与 CLI 共用同一结构。
type Store struct {
	mu    sync.RWMutex
	tasks map[string]*models.TaskRecord
}

// New 创建空的内存任务仓库。
func New() *Store {
	return &Store{tasks: map[string]*models.TaskRecord{}}
}

// Update 写入状态与进度，并用 patch 合并对外字段。
func (s *Store) Update(taskID string, state int, progress int, patch *models.TaskRecord) *models.TaskRecord {
	if progress > 100 {
		progress = 100
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	rec := s.tasks[taskID]
	if rec == nil {
		rec = &models.TaskRecord{TaskID: taskID}
		s.tasks[taskID] = rec
	}
	rec.State = state
	rec.Progress = progress
	if patch != nil {
		merge(rec, patch)
	}
	return copyRecord(rec)
}

// Get 返回任务快照；不存在时返回 nil。
func (s *Store) Get(taskID string) *models.TaskRecord {
	s.mu.RLock()
	defer s.mu.RUnlock()
	rec := s.tasks[taskID]
	if rec == nil {
		return nil
	}
	return copyRecord(rec)
}

// Patch 仅合并字段，不改状态码；任务不存在时返回 false。
func (s *Store) Patch(taskID string, patch *models.TaskRecord) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	rec := s.tasks[taskID]
	if rec == nil {
		return false
	}
	merge(rec, patch)
	return true
}

// Delete 从内存表移除任务记录。
func (s *Store) Delete(taskID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.tasks, taskID)
}

// List 分页列出任务。
func (s *Store) List(page, pageSize int) ([]models.TaskRecord, int) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 10
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	all := make([]models.TaskRecord, 0, len(s.tasks))
	for _, rec := range s.tasks {
		all = append(all, *copyRecord(rec))
	}
	total := len(all)
	start := (page - 1) * pageSize
	if start >= total {
		return []models.TaskRecord{}, total
	}
	end := start + pageSize
	if end > total {
		end = total
	}
	return all[start:end], total
}

func merge(dst, src *models.TaskRecord) {
	if src.FailedStage != "" {
		dst.FailedStage = src.FailedStage
	}
	if src.Error != "" {
		dst.Error = src.Error
	}
	if src.Script != "" {
		dst.Script = src.Script
	}
	if src.Terms != nil {
		dst.Terms = src.Terms
	}
	if src.AudioFile != "" {
		dst.AudioFile = src.AudioFile
	}
	if src.SubtitlePath != "" {
		dst.SubtitlePath = src.SubtitlePath
	}
	if src.Materials != nil {
		dst.Materials = src.Materials
	}
	if src.Videos != nil {
		dst.Videos = src.Videos
	}
	if src.CombinedVideos != nil {
		dst.CombinedVideos = src.CombinedVideos
	}
	if src.CrossPostState != "" {
		dst.CrossPostState = src.CrossPostState
	}
	if src.CrossPostError != "" {
		dst.CrossPostError = src.CrossPostError
	}
	if src.Warnings != nil {
		dst.Warnings = src.Warnings
	}
	if src.LoomLoomRunID != "" {
		dst.LoomLoomRunID = src.LoomLoomRunID
	}
}

func copyRecord(rec *models.TaskRecord) *models.TaskRecord {
	dup := *rec
	return &dup
}
