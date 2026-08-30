// Package queue 对应 app/controllers/manager：并发预占 + 有上限等待队列。
package queue

import (
	"errors"
	"log/slog"
	"sync"
)

// ErrQueueFull 等待队列已满，对应 HTTP 429。
var ErrQueueFull = errors.New("task queue is full, please try again later")

type job struct {
	fn func()
}

// Manager 限制同时执行的任务数，超出部分进入有上限等待队列。
type Manager struct {
	maxConcurrent int
	maxQueued     int
	current       int
	mu            sync.Mutex
	pending       []job
}

// New 创建任务队列；并发与排队上限至少为 1。
func New(maxConcurrent, maxQueued int) *Manager {
	if maxConcurrent < 1 {
		maxConcurrent = 1
	}
	if maxQueued < 1 {
		maxQueued = 100
	}
	return &Manager{maxConcurrent: maxConcurrent, maxQueued: maxQueued}
}

// Add 立即执行或入队；队列满时返回 ErrQueueFull。
func (m *Manager) Add(fn func()) error {
	m.mu.Lock()
	if m.current < m.maxConcurrent {
		m.current++
		m.mu.Unlock()
		go m.run(fn)
		return nil
	}
	if len(m.pending) >= m.maxQueued {
		m.mu.Unlock()
		slog.Warn("reject task because queue is full", "queue_size", len(m.pending))
		return ErrQueueFull
	}
	m.pending = append(m.pending, job{fn: fn})
	m.mu.Unlock()
	return nil
}

func (m *Manager) run(fn func()) {
	defer m.done()
	fn()
}

func (m *Manager) done() {
	m.mu.Lock()
	m.current--
	var next job
	hasNext := false
	if m.current < m.maxConcurrent && len(m.pending) > 0 {
		next = m.pending[0]
		m.pending = m.pending[1:]
		m.current++
		hasNext = true
	}
	m.mu.Unlock()
	if hasNext {
		go m.run(next.fn)
	}
}
