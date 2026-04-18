import axios from 'axios';

const API_BASE_URL = 'http://127.0.0.1:8081/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 300000,
  headers: {
    'Content-Type': 'application/json'
  }
});

export interface VersionResponse {
  name: string;
  version: string;
  code: number;
  message: string;
}

export interface ApiResponse {
  status: number;
  message: string;
  data?: any;
}

export interface VideoScriptRequest {
  video_subject: string;
  video_language: string | null;
  paragraph_number: number;
}

export interface VideoScriptResponse {
  video_script: string;
}

export interface VideoTermsRequest {
  video_subject: string;
  video_script: string;
  amount: number;
}

export interface VideoTermsResponse {
  video_terms: string[];
}

export interface ParseScriptRequest {
  video_script: string;
  language: string | null;
}

export interface Scene {
  id: string;
  duration: number;
  visual_requirement: string;
  keywords: string;
  script: string;
  introVideo?: string;
  introVideoDuration?: number;
}

export interface ParseScriptResponse {
  status: string;
  scenes: Scene[];
  evaluation?: any;
}

export const apiService = {
  // Task related
  getAllTasks: async (page: number = 1, pageSize: number = 10): Promise<ApiResponse> => {
    const response = await api.get('/tasks', { params: { page, page_size: pageSize } });
    return response.data;
  },
  
  getTask: async (taskId: string): Promise<ApiResponse> => {
    const response = await api.get(`/tasks/${taskId}`);
    return response.data;
  },
  
  createVideo: async (params: any): Promise<ApiResponse> => {
    console.log('createVideo params:', params);
    const response = await api.post('/videos', params);
    console.log('createVideo response:', response.data);
    return response.data;
  },
  
  createSubtitle: async (params: any): Promise<ApiResponse> => {
    const response = await api.post('/subtitle', params);
    return response.data;
  },
  
  createAudio: async (params: any): Promise<ApiResponse> => {
    const response = await api.post('/audio', params);
    return response.data;
  },
  
  deleteTask: async (taskId: string): Promise<ApiResponse> => {
    const response = await api.delete(`/tasks/${taskId}`);
    return response.data;
  },
  
  cancelTask: async (taskId: string): Promise<ApiResponse> => {
    const response = await api.post(`/tasks/${taskId}/cancel`);
    return response.data;
  },
  
  // Settings related
  getVersion: async (): Promise<VersionResponse> => {
    // /version is directly under root, not under /api/v1
    const response = await axios.get('http://localhost:8081/version');
    return response.data;
  },

  getVoices: async (ttsServer: string, forceRefresh: boolean = false): Promise<ApiResponse> => {
    const response = await api.get('/voices', { params: { tts_server: ttsServer, force_refresh: forceRefresh } });
    return response.data;
  },

  getConfig: async (): Promise<ApiResponse> => {
    const response = await api.get('/config');
    return response.data;
  },

  updateConfig: async (cfg: any): Promise<ApiResponse> => {
    const response = await api.put('/config', cfg);
    return response.data;
  },

  previewAudio: async (params: {
    text: string;
    voice_name: string;
    voice_rate: number;
    voice_volume: number;
    voice_emotion?: string;
  }): Promise<Blob> => {
    const response = await api.post('/audio/preview', params, {
      responseType: 'blob'
    });
    return response.data;
  },
  
  // Upload related
  uploadBgm: async (file: File): Promise<ApiResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await api.post('/upload/bgm', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
    return response.data;
  },
  
  uploadVideoMaterial: async (file: File): Promise<ApiResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await api.post('/upload/video', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
    return response.data;
  },
  
  getBgmList: async (): Promise<ApiResponse> => {
    const response = await api.get('/upload/bgm');
    return response.data;
  },
  
  getVideoMaterials: async (): Promise<ApiResponse> => {
    const response = await api.get('/upload/video');
    return response.data;
  },
  
  // Logs related
  getLogs: async (params: any): Promise<ApiResponse> => {
    const response = await api.get('/logs', { params });
    // Return the raw response data
    return response.data;
  }
};

export const generateVideoScript = async (request: VideoScriptRequest): Promise<VideoScriptResponse> => {
  try {
    const response = await api.post('/scripts', request);
    return response.data.data;
  } catch (error) {
    console.error('Error generating video script:', error);
    throw error;
  }
};

export const generateVideoTerms = async (request: VideoTermsRequest): Promise<VideoTermsResponse> => {
  try {
    const response = await api.post('/terms', request);
    return response.data.data;
  } catch (error) {
    console.error('Error generating video terms:', error);
    throw error;
  }
};

export const parseVideoScript = async (request: ParseScriptRequest): Promise<ParseScriptResponse> => {
  try {
    const response = await api.post('/parse-script', request);
    return response.data.data;
  } catch (error) {
    console.error('Error parsing video script:', error);
    throw error;
  }
};

export default api;