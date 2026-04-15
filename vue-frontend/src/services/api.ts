import axios from 'axios';

// 创建axios实例
const api = axios.create({
  baseURL: 'http://localhost:8000', // 假设后端运行在8000端口
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json'
  }
});

// 请求拦截器
api.interceptors.request.use(
  config => {
    // 可以在这里添加认证信息
    return config;
  },
  error => {
    return Promise.reject(error);
  }
);

// 响应拦截器
api.interceptors.response.use(
  response => {
    return response.data;
  },
  error => {
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

// API接口定义
export const apiService = {
  // 视频生成相关
  createVideo: (params: any) => api.post('/videos', params),
  createSubtitle: (params: any) => api.post('/subtitle', params),
  createAudio: (params: any) => api.post('/audio', params),
  
  // 任务管理相关
  getAllTasks: (page: number = 1, pageSize: number = 10) => api.get(`/tasks?page=${page}&page_size=${pageSize}`),
  getTask: (taskId: string) => api.get(`/tasks/${taskId}`),
  deleteTask: (taskId: string) => api.delete(`/tasks/${taskId}`),
  
  // 资源管理相关
  getBgmList: () => api.get('/musics'),
  uploadBgm: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/musics', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
  },
  
  getVideoMaterials: () => api.get('/video_materials'),
  uploadVideoMaterial: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/video_materials', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
  }
};

export default api;