import axios from 'axios';

// API响应类型
export interface ApiResponse {
  code: number;
  data: any;
  message?: string;
}

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
    return response;
  },
  error => {
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

// API接口定义
export const apiService = {
  // 视频生成相关
  createVideo: (params: any) => api.post<ApiResponse>('/videos', params).then(res => res.data),
  createSubtitle: (params: any) => api.post<ApiResponse>('/subtitle', params).then(res => res.data),
  createAudio: (params: any) => api.post<ApiResponse>('/audio', params).then(res => res.data),
  
  // 任务管理相关
  getAllTasks: (page: number = 1, pageSize: number = 10) => api.get<ApiResponse>(`/tasks?page=${page}&page_size=${pageSize}`).then(res => res.data),
  getTask: (taskId: string) => api.get<ApiResponse>(`/tasks/${taskId}`).then(res => res.data),
  deleteTask: (taskId: string) => api.delete<ApiResponse>(`/tasks/${taskId}`).then(res => res.data),
  
  // 资源管理相关
  getBgmList: () => api.get<ApiResponse>('/musics').then(res => res.data),
  uploadBgm: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<ApiResponse>('/musics', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    }).then(res => res.data);
  },
  
  getVideoMaterials: () => api.get<ApiResponse>('/video_materials').then(res => res.data),
  uploadVideoMaterial: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<ApiResponse>('/video_materials', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    }).then(res => res.data);
  }
};

export default api;