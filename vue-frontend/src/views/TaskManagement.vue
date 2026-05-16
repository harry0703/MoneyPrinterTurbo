<template>
  <div class="task-management">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">📋 {{ t('Task Management') }}</h2>
        </div>
      </template>
      
      <TaskStatus
        :tasks="tasks"
        :loading="loading"
        :error="error"
        :title="t('Task List')"
        :refreshable="true"
        :refresh-text="t('Refresh')"
        :loading-text="t('Loading tasks...')"
        :retry-text="t('Retry')"
        :empty-text="t('No tasks')"
        :status-text="t('Status')"
        :progress-text="t('Progress')"
        :created-at-text="t('Created At')"
        :updated-at-text="t('Updated At')"
        :error-text="t('Error')"
        :download-text="t('Download')"
        :delete-text="t('Delete')"
        :cancel-text="t('Cancel')"
        @refresh="refreshTasks"
        @delete="deleteTask"
        @cancel="cancelTask"
      />
      
      <div class="task-stats" v-if="tasks.length > 0">
        <el-card :body-style="{ padding: '15px' }">
          <div class="stats-header">
            <span>{{ t('Task Statistics') }}</span>
          </div>
          <div class="stats-content">
            <el-statistic :value="tasks.length" :title="t('Total Tasks')" />
            <el-statistic :value="runningTasks.length" :title="t('Running Tasks')" />
            <el-statistic :value="completedTasks.length" :title="t('Completed Tasks')" />
            <el-statistic :value="failedTasks.length" :title="t('Failed Tasks')" />
          </div>
        </el-card>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import TaskStatus from '../components/TaskStatus.vue';
import { useI18nStore } from '../stores/i18n';
import { useTasksStore } from '../stores/tasks';

const i18nStore = useI18nStore();
const tasksStore = useTasksStore();
const t = i18nStore.t;

const tasks = computed(() => tasksStore.tasks);
const loading = computed(() => tasksStore.loading);
const error = computed(() => tasksStore.error || '');

const runningTasks = computed(() => tasksStore.runningTasks);
const completedTasks = computed(() => tasksStore.completedTasks);
const failedTasks = computed(() => tasksStore.failedTasks);

const refreshInterval = ref<number | null>(null);

const refreshTasks = async () => {
  await tasksStore.fetchAllTasks();
};

const deleteTask = async (taskId: string) => {
  await tasksStore.deleteTask(taskId);
};

const cancelTask = async (taskId: string) => {
  await tasksStore.cancelTask(taskId);
  await refreshTasks();
};

onMounted(async () => {
  // Initial refresh
  await refreshTasks();
  
  // Set auto refresh interval (every 5 seconds)
  refreshInterval.value = window.setInterval(async () => {
    // 轮询时不显示 loading 状态，避免界面闪动
    await tasksStore.fetchAllTasks(1, 10, false);
  }, 5000);
});

onUnmounted(() => {
  // Clear auto refresh interval
  if (refreshInterval.value) {
    clearInterval(refreshInterval.value);
  }
});
</script>

<style scoped>
.task-management {
  width: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.title {
  margin: 0 !important;
  font-size: 1.2rem !important;
  font-weight: 600 !important;
  line-height: 1.5 !important;
}

.task-stats {
  margin-top: 30px;
}

.stats-header {
  margin-bottom: 20px;
}

.stats-content {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 20px;
}
</style>