import { defineStore } from 'pinia';
import { apiService } from '../services/api';

export interface UploadFile {
  id: string;
  name: string;
  type: string;
  size: number;
  path?: string;
  progress: number;
  status: 'pending' | 'uploading' | 'completed' | 'failed';
  error?: string;
}

export const useUploadStore = defineStore('upload', {
  state: () => ({
    files: [] as UploadFile[],
    bgmFiles: [] as UploadFile[],
    videoMaterials: [] as UploadFile[],
    loading: false,
    error: null as string | null
  }),
  
  getters: {
    pendingFiles: (state) => {
      return state.files.filter(file => file.status === 'pending');
    },
    
    uploadingFiles: (state) => {
      return state.files.filter(file => file.status === 'uploading');
    },
    
    completedFiles: (state) => {
      return state.files.filter(file => file.status === 'completed');
    },
    
    failedFiles: (state) => {
      return state.files.filter(file => file.status === 'failed');
    }
  },
  
  actions: {
    async uploadBgm(file: File) {
      const uploadFile: UploadFile = {
        id: Date.now().toString(),
        name: file.name,
        type: file.type,
        size: file.size,
        progress: 0,
        status: 'uploading'
      };
      
      this.bgmFiles.push(uploadFile);
      
      try {
        const response = await apiService.uploadBgm(file);
        if (response.code === 200 && response.data) {
          uploadFile.status = 'completed';
          uploadFile.progress = 100;
          uploadFile.path = response.data.file;
        } else {
          uploadFile.status = 'failed';
          uploadFile.error = 'Upload failed';
        }
      } catch (error) {
        uploadFile.status = 'failed';
        uploadFile.error = 'Upload failed';
        console.error('Error uploading BGM:', error);
      }
      
      return uploadFile;
    },
    
    async uploadVideoMaterial(file: File) {
      const uploadFile: UploadFile = {
        id: Date.now().toString(),
        name: file.name,
        type: file.type,
        size: file.size,
        progress: 0,
        status: 'uploading'
      };
      
      this.videoMaterials.push(uploadFile);
      
      try {
        const response = await apiService.uploadVideoMaterial(file);
        if (response.code === 200 && response.data) {
          uploadFile.status = 'completed';
          uploadFile.progress = 100;
          uploadFile.path = response.data.file;
        } else {
          uploadFile.status = 'failed';
          uploadFile.error = 'Upload failed';
        }
      } catch (error) {
        uploadFile.status = 'failed';
        uploadFile.error = 'Upload failed';
        console.error('Error uploading video material:', error);
      }
      
      return uploadFile;
    },
    
    async fetchBgmList() {
      this.loading = true;
      this.error = null;
      
      try {
        const response = await apiService.getBgmList();
        if (response.code === 200 && response.data) {
          this.bgmFiles = response.data.files.map((file: any) => ({
            id: file.file,
            name: file.name,
            type: 'audio/mpeg',
            size: file.size,
            path: file.file,
            progress: 100,
            status: 'completed' as const
          }));
        }
      } catch (error) {
        this.error = 'Failed to fetch BGM list';
        console.error('Error fetching BGM list:', error);
      } finally {
        this.loading = false;
      }
    },
    
    async fetchVideoMaterials() {
      this.loading = true;
      this.error = null;
      
      try {
        const response = await apiService.getVideoMaterials();
        if (response.code === 200 && response.data) {
          this.videoMaterials = response.data.files.map((file: any) => ({
            id: file.file,
            name: file.name,
            type: this.getFileType(file.name),
            size: file.size,
            path: file.file,
            progress: 100,
            status: 'completed' as const
          }));
        }
      } catch (error) {
        this.error = 'Failed to fetch video materials';
        console.error('Error fetching video materials:', error);
      } finally {
        this.loading = false;
      }
    },
    
    removeFile(fileId: string) {
      this.files = this.files.filter(file => file.id !== fileId);
    },
    
    removeBgmFile(fileId: string) {
      this.bgmFiles = this.bgmFiles.filter(file => file.id !== fileId);
    },
    
    removeVideoMaterial(fileId: string) {
      this.videoMaterials = this.videoMaterials.filter(file => file.id !== fileId);
    },
    
    clearError() {
      this.error = null;
    },
    
    getFileType(filename: string): string {
      const ext = filename.split('.').pop()?.toLowerCase();
      if (ext === 'mp4') return 'video/mp4';
      if (ext === 'mov') return 'video/quicktime';
      if (ext === 'avi') return 'video/x-msvideo';
      if (ext === 'flv') return 'video/x-flv';
      if (ext === 'mkv') return 'video/x-matroska';
      if (ext === 'jpg' || ext === 'jpeg') return 'image/jpeg';
      if (ext === 'png') return 'image/png';
      return 'application/octet-stream';
    }
  }
});