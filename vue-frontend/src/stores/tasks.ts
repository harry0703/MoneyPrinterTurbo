import { defineStore } from 'pinia';
import { apiService, type ApiResponse } from '../services/api';

export interface Task {
  task_id: string;
  status: string;
  progress?: number;
  videos?: string[];
  combined_videos?: string[];
  error?: string;
  created_at?: string;
  updated_at?: string;
}

export const useTasksStore = defineStore('tasks', {
  state: () => ({
    tasks: [] as Task[],
    currentTask: null as Task | null,
    loading: false,
    error: null as string | null
  }),
  
  getters: {
    getTaskById: (state) => (taskId: string) => {
      return state.tasks.find(task => task.task_id === taskId) || null;
    },
    
    pendingTasks: (state) => {
      return state.tasks.filter(task => task.status === 'pending');
    },
    
    runningTasks: (state) => {
      return state.tasks.filter(task => task.status === 'running');
    },
    
    completedTasks: (state) => {
      return state.tasks.filter(task => task.status === 'completed');
    },
    
    failedTasks: (state) => {
      return state.tasks.filter(task => task.status === 'failed');
    }
  },
  
  actions: {
    async fetchAllTasks(page: number = 1, pageSize: number = 10) {
      this.loading = true;
      this.error = null;
      
      try {
        const response = await apiService.getAllTasks(page, pageSize);
        if (response.code === 200 && response.data) {
          this.tasks = response.data.tasks || [];
        }
      } catch (error) {
        this.error = 'Failed to fetch tasks';
        console.error('Error fetching tasks:', error);
      } finally {
        this.loading = false;
      }
    },
    
    async fetchTask(taskId: string) {
      this.loading = true;
      this.error = null;
      
      try {
        const response = await apiService.getTask(taskId);
        if (response.code === 200 && response.data) {
          const task = response.data;
          this.currentTask = task;
          
          // 更新任务列表中的对应任务
          const index = this.tasks.findIndex(t => t.task_id === taskId);
          if (index !== -1) {
            this.tasks[index] = task;
          } else {
            this.tasks.push(task);
          }
        }
      } catch (error) {
        this.error = 'Failed to fetch task';
        console.error('Error fetching task:', error);
      } finally {
        this.loading = false;
      }
    },
    
    async createTask(params: any, type: 'video' | 'subtitle' | 'audio' = 'video') {
      this.loading = true;
      this.error = null;
      
      try {
        let response: ApiResponse;
        if (type === 'video') {
          response = await apiService.createVideo(params);
        } else if (type === 'subtitle') {
          response = await apiService.createSubtitle(params);
        } else {
          response = await apiService.createAudio(params);
        }
        
        if (response.code === 200 && response.data) {
          const task = response.data;
          this.tasks.unshift(task);
          this.currentTask = task;
          return task;
        }
      } catch (error) {
        this.error = 'Failed to create task';
        console.error('Error creating task:', error);
      } finally {
        this.loading = false;
      }
      
      return null;
    },
    
    async deleteTask(taskId: string) {
      this.loading = true;
      this.error = null;
      
      try {
        const response = await apiService.deleteTask(taskId);
        if (response.code === 200) {
          this.tasks = this.tasks.filter(task => task.task_id !== taskId);
          if (this.currentTask?.task_id === taskId) {
            this.currentTask = null;
          }
          return true;
        }
      } catch (error) {
        this.error = 'Failed to delete task';
        console.error('Error deleting task:', error);
      } finally {
        this.loading = false;
      }
      
      return false;
    },
    
    updateTaskStatus(taskId: string, status: string, progress?: number) {
      const task = this.getTaskById(taskId);
      if (task) {
        task.status = status;
        if (progress !== undefined) {
          task.progress = progress;
        }
        task.updated_at = new Date().toISOString();
      }
    },
    
    clearError() {
      this.error = null;
    }
  }
});