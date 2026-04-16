import axios from 'axios';

// API response type
export interface ApiResponse {
  code: number;
  data: any;
  message?: string;
}

// Create axios instance
const api = axios.create({
  baseURL: 'http://localhost:8000', // Assuming backend runs on port 8000
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json'
  }
});

// Request interceptor
api.interceptors.request.use(
  config => {
    // You can add authentication information here
    return config;
  },
  error => {
    return Promise.reject(error);
  }
);

// Response interceptor
api.interceptors.response.use(
  response => {
    return response;
  },
  error => {
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

// API interface definition
export const apiService = {
  // Video generation related
  createVideo: (params: any) => api.post<ApiResponse>('/videos', params).then(res => res.data),
  createSubtitle: (params: any) => api.post<ApiResponse>('/subtitle', params).then(res => res.data),
  createAudio: (params: any) => api.post<ApiResponse>('/audio', params).then(res => res.data),
  
  // Task management related
  getAllTasks: (page: number = 1, pageSize: number = 10) => api.get<ApiResponse>(`/tasks?page=${page}&page_size=${pageSize}`).then(res => res.data),
  getTask: (taskId: string) => api.get<ApiResponse>(`/tasks/${taskId}`).then(res => res.data),
  deleteTask: (taskId: string) => api.delete<ApiResponse>(`/tasks/${taskId}`).then(res => res.data),
  
  // Resource management related
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
  },
  
  // Get version information
  getVersion: () => api.get<{name: string, version: string}>('/version').then(res => res.data)
};

export default api;