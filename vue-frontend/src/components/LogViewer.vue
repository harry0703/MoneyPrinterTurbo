<template>
  <div class="log-viewer">
    <el-card :body-style="{ padding: '16px' }">
      <template #header>
        <div class="card-header">
          <span>{{ title }}</span>
          <el-button type="primary" size="small" @click="clearLogs">
            <el-icon><Delete /></el-icon>
            {{ clearText }}
          </el-button>
        </div>
      </template>
      
      <div class="log-container" ref="logContainer">
        <div v-if="logs.length === 0" class="empty-logs">
          {{ emptyText }}
        </div>
        <div v-else class="logs-list">
          <div v-for="(log, index) in logs" :key="index" :class="['log-item', getLogLevelClass(log)]">
            <div class="log-time">{{ getLogTime(log) }}</div>
            <div class="log-content">{{ getLogContent(log) }}</div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue';
import { Delete } from '@element-plus/icons-vue';

interface Log {
  time?: string;
  level?: string;
  message: string;
  [key: string]: any;
}

interface Props {
  logs: Log[];
  title?: string;
  clearText?: string;
  emptyText?: string;
  autoScroll?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  logs: () => [],
  title: 'Logs',
  clearText: 'Clear',
  emptyText: 'No logs',
  autoScroll: true
});

const emit = defineEmits(['clear']);

const logContainer = ref<HTMLElement | null>(null);

const clearLogs = () => {
  emit('clear');
};

const getLogLevelClass = (log: Log): string => {
  const level = log.level?.toLowerCase() || 'info';
  return `log-level-${level}`;
};

const getLogTime = (log: Log): string => {
  if (log.time) {
    return log.time;
  }
  return new Date().toLocaleTimeString();
};

const getLogContent = (log: Log): string => {
  return log.message;
};

watch(
  () => props.logs.length,
  async () => {
    if (props.autoScroll) {
      await nextTick();
      scrollToBottom();
    }
  }
);

const scrollToBottom = () => {
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight;
  }
};
</script>

<style scoped>
.log-viewer {
  width: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.log-container {
  max-height: 400px;
  overflow-y: auto;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  padding: 10px;
  background-color: #f9f9f9;
}

.empty-logs {
  text-align: center;
  color: #909399;
  padding: 20px;
}

.logs-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.log-item {
  display: flex;
  padding: 5px 0;
  border-bottom: 1px solid #f0f0f0;
}

.log-time {
  width: 120px;
  font-size: 12px;
  color: #909399;
  margin-right: 10px;
  flex-shrink: 0;
}

.log-content {
  flex: 1;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-level-info {
  color: #606266;
}

.log-level-success {
  color: #67c23a;
}

.log-level-warning {
  color: #e6a23c;
}

.log-level-error {
  color: #f56c6c;
}

.log-level-debug {
  color: #909399;
}
</style>