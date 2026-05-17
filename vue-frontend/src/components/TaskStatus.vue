<template>
  <div class="task-status">
    <el-card :body-style="{ padding: '16px' }">
      <template #header>
        <div class="card-header">
          <span>{{ title }}</span>
          <el-button v-if="refreshable" type="primary" size="small" @click="$emit('refresh')">
            <el-icon><Refresh /></el-icon>
            {{ refreshText }}
          </el-button>
        </div>
      </template>
      
      <div v-if="loading" class="loading-container">
        <el-spinner size="40" />
        <p>{{ loadingText }}</p>
      </div>
      
      <div v-else-if="error" class="error-container">
        <el-alert
          :title="error"
          type="error"
          show-icon
          :closable="false"
        />
        <el-button type="primary" size="small" @click="$emit('refresh')">
          {{ retryText }}
        </el-button>
      </div>
      
      <div v-else-if="tasks.length === 0" class="empty-container">
        <el-empty description="{{ emptyText }}" />
      </div>
      
      <div v-else class="tasks-list">
        <el-collapse v-model="activeNames">
          <el-collapse-item v-for="task in tasks" :key="task.task_id" :title="getTaskTitle(task)" :name="task.task_id">
            <div class="task-details">
              <div class="task-info">
                <div class="info-item">
                  <span class="label">{{ statusText }}:</span>
                  <transition name="fade" mode="out-in">
                    <el-tag :key="task.status" :type="getStatusType(task.status)">{{ getStatusText(task.status) }}</el-tag>
                  </transition>
                </div>
                <div class="info-item" v-if="task.task_type">
                  <span class="label">{{ taskTypeText }}:</span>
                  <el-tag type="info">{{ getTaskTypeText(task.task_type) }}</el-tag>
                </div>
                <div class="info-item" v-if="task.progress !== undefined">
                  <span class="label">{{ progressText }}:</span>
                  <transition name="fade">
                    <el-progress :key="task.progress" :percentage="task.progress" :format="formatProgress" />
                  </transition>
                </div>
                <div class="info-item" v-if="task.created_at">
                  <span class="label">{{ createdAtText }}:</span>
                  <span>{{ formatDate(task.created_at) }}</span>
                </div>
                <div class="info-item" v-if="task.updated_at">
                  <span class="label">{{ updatedAtText }}:</span>
                  <span>{{ formatDate(task.updated_at) }}</span>
                </div>
                <div class="info-item" v-if="task.error">
                  <span class="label">{{ errorText }}:</span>
                  <span class="error-message">{{ task.error }}</span>
                </div>
              </div>
              
              <div class="task-actions">
                <!-- 下载按钮 - 仅在任务完成且有视频时显示 -->
                <transition name="fade">
                  <el-button v-if="task.status === 'completed' && task.videos && task.videos.length > 0" :key="'download-'+task.task_id" type="primary" size="small" @click="handleDownload(task.videos[0])">
                    <el-icon><Download /></el-icon>
                    {{ downloadText }}
                  </el-button>
                </transition>
                
                <!-- 取消按钮 - 仅在任务运行时显示 -->
                <transition name="fade">
                  <el-button v-if="task.status === 'running'" :key="'cancel-'+task.task_id" type="warning" size="small" @click="$emit('cancel', task.task_id)">
                    <el-icon><Close /></el-icon>
                    {{ cancelText }}
                  </el-button>
                </transition>
                
                <!-- 删除按钮 - 对所有状态的任务都显示 -->
                <el-button type="danger" size="small" @click="$emit('delete', task.task_id)">
                  <el-icon><Delete /></el-icon>
                  {{ deleteText }}
                </el-button>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { Refresh, Download, Delete, Close } from '@element-plus/icons-vue';
import { useI18nStore } from '../stores/i18n';

const i18nStore = useI18nStore();
const t = i18nStore.t;

interface Task {
  task_id: string;
  status: string;
  task_type?: string;
  progress?: number;
  videos?: string[];
  combined_videos?: string[];
  error?: string;
  created_at?: string;
  updated_at?: string;
}

interface Props {
  tasks: Task[];
  loading?: boolean;
  error?: string;
  title?: string;
  refreshable?: boolean;
  refreshText?: string;
  loadingText?: string;
  retryText?: string;
  emptyText?: string;
  statusText?: string;
  taskTypeText?: string;
  progressText?: string;
  createdAtText?: string;
  updatedAtText?: string;
  errorText?: string;
  downloadText?: string;
  deleteText?: string;
  cancelText?: string;
}

withDefaults(defineProps<Props>(), {
  tasks: () => [],
  loading: false,
  error: '',
  title: 'Task Status',
  refreshable: true,
  refreshText: 'Refresh',
  loadingText: 'Loading tasks...',
  retryText: 'Retry',
  emptyText: 'No tasks',
  statusText: 'Status',
  taskTypeText: 'Task Type',
  progressText: 'Progress',
  createdAtText: 'Created At',
  updatedAtText: 'Updated At',
  errorText: 'Error',
  downloadText: 'Download',
  deleteText: 'Delete',
  cancelText: 'Cancel'
});

const emit = defineEmits(['refresh', 'delete', 'cancel']);

const activeNames = ref<string[]>([]);

const getTaskTitle = (task: Task): string => {
  return `${t('Task')} ${task.task_id} - ${getStatusText(task.status)}`;
};

const getStatusText = (status: string): string => {
  const statusMap: Record<string, string> = {
    pending: t('Pending'),
    running: t('Running'),
    completed: t('Completed'),
    failed: t('Failed')
  };
  return statusMap[status] || status;
};

const getStatusType = (status: string): string => {
  const typeMap: Record<string, string> = {
    pending: 'info',
    running: 'warning',
    completed: 'success',
    failed: 'danger'
  };
  return typeMap[status] || 'info';
};

const getTaskTypeText = (taskType: string): string => {
  const taskTypeMap: Record<string, string> = {
    video_generation: t('Video Generation'),
    scene_integration: t('Scene Integration')
  };
  return taskTypeMap[taskType] || taskType;
};

const formatProgress = (percentage: number): string => {
  return `${percentage}%`;
};

const formatDate = (dateString: string): string => {
  const date = new Date(dateString);
  return date.toLocaleString();
};

const handleDownload = (videoUrl: string) => {
  window.open(videoUrl, '_blank');
};
</script>

<style scoped>
.task-status {
  width: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 0;
}

.error-container {
  padding: 20px 0;
}

.empty-container {
  padding: 40px 0;
}

.tasks-list {
  margin-top: 10px;
}

.task-details {
  padding: 10px 0;
}

.task-info {
  margin-bottom: 15px;
}

.info-item {
  margin-bottom: 8px;
  display: flex;
  align-items: center;
}

.label {
  font-weight: 500;
  width: 120px;
}

.error-message {
  color: #f56c6c;
  word-break: break-all;
}

.task-actions {
  display: flex;
  gap: 10px;
  margin-top: 15px;
}

/* 过渡效果 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 进度条过渡效果 */
:deep(.el-progress__bar) {
  transition: width 0.5s ease;
}

/* 标签过渡效果 */
:deep(.el-tag) {
  transition: all 0.3s ease;
}

/* 按钮过渡效果 */
:deep(.el-button) {
  transition: all 0.3s ease;
}
</style>