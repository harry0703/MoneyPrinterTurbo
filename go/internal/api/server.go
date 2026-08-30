// Package api 对应 app/asgi.py 与 controllers/v1：FastAPI 路由的 Go 实现。
package api

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/harry0703/moneyprinterturbo/go/internal/auth"
	"github.com/harry0703/moneyprinterturbo/go/internal/config"
	"github.com/harry0703/moneyprinterturbo/go/internal/models"
	"github.com/harry0703/moneyprinterturbo/go/internal/queue"
	"github.com/harry0703/moneyprinterturbo/go/internal/services"
	"github.com/harry0703/moneyprinterturbo/go/internal/state"
	"github.com/harry0703/moneyprinterturbo/go/internal/utils"
)

// Server 聚合配置、任务状态、并发队列和共享流水线。
type Server struct {
	cfg      *config.Config
	state    *state.Store
	queue    *queue.Manager
	pipeline *services.Pipeline
}

// New 构造 API 服务。
func New(cfg *config.Config) *Server {
	st := state.New()
	return &Server{
		cfg:      cfg,
		state:    st,
		queue:    queue.New(cfg.AppInt("max_concurrent_tasks", 5), cfg.AppInt("max_queued_tasks", 100)),
		pipeline: services.NewPipeline(st),
	}
}

// Handler 注册与 Python FastAPI 对齐的路由。
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /ping", s.ping)
	mux.HandleFunc("POST /api/v1/scripts", s.withAuth(s.scripts))
	mux.HandleFunc("POST /api/v1/terms", s.withAuth(s.terms))
	mux.HandleFunc("POST /api/v1/social-metadata", s.withAuth(s.social))
	mux.HandleFunc("POST /api/v1/videos", s.withAuth(s.createVideo))
	mux.HandleFunc("POST /api/v1/subtitle", s.withAuth(s.createSubtitle))
	mux.HandleFunc("POST /api/v1/audio", s.withAuth(s.createAudio))
	mux.HandleFunc("GET /api/v1/tasks", s.withAuth(s.listTasks))
	mux.HandleFunc("GET /api/v1/tasks/{task_id}", s.withAuth(s.getTask))
	mux.HandleFunc("DELETE /api/v1/tasks/{task_id}", s.withAuth(s.deleteTask))
	mux.HandleFunc("GET /api/v1/musics", s.withAuth(s.listBGM))
	mux.HandleFunc("GET /api/v1/video_materials", s.withAuth(s.listMaterials))
	mux.Handle("/tasks/", s.withAuthHandler(http.StripPrefix("/tasks/", http.FileServer(http.Dir(utils.TaskDir(""))))))
	public := utils.PublicDir()
	if _, err := os.Stat(public); err == nil {
		mux.Handle("/", http.FileServer(http.Dir(public)))
	}
	return withCORS(mux)
}

// withAuth 校验 API Key 后再进入业务处理。
func (s *Server) withAuth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if err := auth.VerifyToken(r); err != nil {
			writeJSON(w, err.StatusCode, utils.Response(err.StatusCode, nil, err.Message))
			return
		}
		next(w, r)
	}
}

func (s *Server) withAuthHandler(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			next.ServeHTTP(w, r)
			return
		}
		if err := auth.VerifyToken(r); err != nil {
			writeJSON(w, err.StatusCode, utils.Response(err.StatusCode, nil, err.Message))
			return
		}
		next.ServeHTTP(w, r)
	})
}

// ping 健康检查，对应 Python GET /ping。
func (s *Server) ping(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/plain")
	_, _ = w.Write([]byte("pong"))
}

// scripts 仅生成文案，不入任务队列。
func (s *Server) scripts(w http.ResponseWriter, r *http.Request) {
	var body models.ScriptRequest
	if err := decodeJSON(r, &body); err != nil {
		writeJSON(w, 400, utils.Response(400, nil, err.Error()))
		return
	}
	if body.ParagraphNumber == 0 {
		body.ParagraphNumber = 1
	}
	script, err := services.GenerateScript(body.VideoSubject, body.VideoLanguage, body.ParagraphNumber, body.VideoScriptPrompt, body.CustomSystemPrompt)
	if err != nil {
		writeJSON(w, 500, utils.Response(500, nil, err.Error()))
		return
	}
	writeJSON(w, 200, utils.Response(200, map[string]any{"video_script": script}, ""))
}

// terms 仅生成素材关键词。
func (s *Server) terms(w http.ResponseWriter, r *http.Request) {
	var body models.TermsRequest
	if err := decodeJSON(r, &body); err != nil {
		writeJSON(w, 400, utils.Response(400, nil, err.Error()))
		return
	}
	if body.Amount == 0 {
		body.Amount = 5
	}
	terms, err := services.GenerateTerms(body.VideoSubject, body.VideoScript, body.Amount, body.MatchMaterialsToScript)
	if err != nil {
		writeJSON(w, 500, utils.Response(500, nil, err.Error()))
		return
	}
	writeJSON(w, 200, utils.Response(200, map[string]any{"video_terms": terms}, ""))
}

// social 生成短视频发布标题、简介和标签。
func (s *Server) social(w http.ResponseWriter, r *http.Request) {
	var body models.SocialMetadataRequest
	if err := decodeJSON(r, &body); err != nil {
		writeJSON(w, 400, utils.Response(400, nil, err.Error()))
		return
	}
	data, err := services.GenerateSocialMetadata(body.VideoSubject, body.VideoScript, body.Language, body.Platform)
	if err != nil {
		writeJSON(w, 500, utils.Response(500, nil, err.Error()))
		return
	}
	writeJSON(w, 200, utils.Response(200, data, ""))
}

func (s *Server) createVideo(w http.ResponseWriter, r *http.Request) {
	s.createTask(w, r, "video")
}

func (s *Server) createSubtitle(w http.ResponseWriter, r *http.Request) {
	s.createTask(w, r, "subtitle")
}

func (s *Server) createAudio(w http.ResponseWriter, r *http.Request) {
	s.createTask(w, r, "audio")
}

// createTask 入队执行流水线；stopAt 控制停在哪一阶段。
func (s *Server) createTask(w http.ResponseWriter, r *http.Request, stopAt string) {
	params := models.DefaultVideoParams()
	if err := decodeJSON(r, &params); err != nil {
		writeJSON(w, 400, utils.Response(400, nil, err.Error()))
		return
	}
	if strings.TrimSpace(params.VideoSubject) == "" && strings.TrimSpace(params.VideoScript) == "" {
		writeJSON(w, 400, utils.Response(400, nil, "one of video_subject or video_script is required"))
		return
	}
	taskID := utils.NewUUID(false)
	s.state.Update(taskID, models.TaskStateProcessing, 0, nil)
	err := s.queue.Add(func() {
		s.pipeline.Start(taskID, params, models.StartOptions{StopAt: stopAt})
	})
	if err != nil {
		s.state.Delete(taskID)
		if err == queue.ErrQueueFull {
			writeJSON(w, 429, utils.Response(429, nil, err.Error()))
			return
		}
		writeJSON(w, 500, utils.Response(500, nil, err.Error()))
		return
	}
	slog.Info("Task created", "task_id", taskID)
	writeJSON(w, 200, utils.Response(200, map[string]any{
		"task_id":    taskID,
		"request_id": auth.TaskIDFromRequest(r),
		"params":     params,
	}, ""))
}

// listTasks 分页列出内存中的任务。
func (s *Server) listTasks(w http.ResponseWriter, r *http.Request) {
	page, _ := strconv.Atoi(r.URL.Query().Get("page"))
	size, _ := strconv.Atoi(r.URL.Query().Get("page_size"))
	if page < 1 {
		page = 1
	}
	if size < 1 {
		size = 10
	}
	tasks, total := s.state.List(page, size)
	writeJSON(w, 200, utils.Response(200, map[string]any{
		"tasks":     tasks,
		"total":     total,
		"page":      page,
		"page_size": size,
	}, ""))
}

// getTask 查询单个任务状态与产物路径。
func (s *Server) getTask(w http.ResponseWriter, r *http.Request) {
	taskID := r.PathValue("task_id")
	rec := s.state.Get(taskID)
	if rec == nil {
		writeJSON(w, 404, utils.Response(404, nil, "task not found"))
		return
	}
	writeJSON(w, 200, utils.Response(200, rec, ""))
}

// deleteTask 删除空闲任务及其磁盘产物；生成或发布中禁止删除。
func (s *Server) deleteTask(w http.ResponseWriter, r *http.Request) {
	taskID := r.PathValue("task_id")
	rec := s.state.Get(taskID)
	if rec == nil {
		writeJSON(w, 404, utils.Response(404, nil, "task not found"))
		return
	}
	if rec.IsBusy() {
		writeJSON(w, 409, utils.Response(409, nil, "task is still running"))
		return
	}
	_ = os.RemoveAll(filepath.Join(utils.TaskDir(""), taskID))
	s.state.Delete(taskID)
	writeJSON(w, 200, utils.Response(200, nil, ""))
}

// listBGM 列出可用本地背景音乐。
func (s *Server) listBGM(w http.ResponseWriter, r *http.Request) {
	files := services.ListBGMFiles()
	items := make([]map[string]any, 0, len(files))
	for _, f := range files {
		info, err := os.Stat(f)
		if err != nil {
			continue
		}
		items = append(items, map[string]any{
			"name": filepath.Base(f),
			"size": info.Size(),
			"file": filepath.Base(f),
		})
	}
	writeJSON(w, 200, utils.Response(200, map[string]any{"files": items}, ""))
}

// listMaterials 列出 storage/local_videos 下的本地素材。
func (s *Server) listMaterials(w http.ResponseWriter, r *http.Request) {
	dir := utils.StorageDir("local_videos", true)
	entries, _ := os.ReadDir(dir)
	items := []map[string]any{}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		items = append(items, map[string]any{
			"name": e.Name(),
			"size": info.Size(),
			"file": e.Name(),
		})
	}
	writeJSON(w, 200, utils.Response(200, map[string]any{"files": items}, ""))
}

// decodeJSON 解析请求体；空 body 视为合法的默认参数。
func decodeJSON(r *http.Request, dest any) error {
	defer r.Body.Close()
	data, err := io.ReadAll(r.Body)
	if err != nil {
		return err
	}
	if len(data) == 0 {
		return nil
	}
	return json.Unmarshal(data, dest)
}

// writeJSON 写出统一 JSON 响应。
func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// withCORS 允许浏览器跨域调用 API。
func withCORS(next http.Handler) http.Handler {
	origins := os.Getenv("CORS_ALLOWED_ORIGINS")
	allow := "*"
	if origins != "" {
		allow = strings.Split(origins, ",")[0]
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", allow)
		w.Header().Set("Access-Control-Allow-Headers", "*")
		w.Header().Set("Access-Control-Allow-Methods", "*")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}
