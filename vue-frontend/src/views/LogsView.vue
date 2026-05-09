<template>
  <div class="logs-view">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">📝 {{ t('Running Logs') }}</h2>
        </div>
      </template>
      
      <div class="logs-filter">
        <div class="filter-row">
          <el-select v-model="selectedTaskId" :placeholder="t('Select Task')" class="task-select">
            <el-option :label="t('All Tasks')" value="" />
            <el-option
              v-for="task in tasks"
              :key="task.task_id"
              :label="task.task_id"
              :value="task.task_id"
            />
          </el-select>

          <el-select v-model="selectedLogLevel" :placeholder="t('Log Level')" class="level-select">
            <el-option :label="t('All Levels')" value="" />
            <el-option label="INFO" value="info" />
            <el-option label="WARNING" value="warning" />
            <el-option label="ERROR" value="error" />
          </el-select>

          <el-button type="primary" size="small" @click="refreshLogs">
            <el-icon><Refresh /></el-icon>
            {{ t('Refresh') }}
          </el-button>

          <el-button :type="autoRefresh ? 'success' : 'default'" size="small" @click="toggleAutoRefresh">
            {{ autoRefresh ? t('Auto Refresh On') : t('Auto Refresh Off') }}
          </el-button>

          <el-tag :type="wsStatus.type" size="small" class="ws-status">
            {{ wsStatus.text }}
          </el-tag>
        </div>
        <div class="log-count">
          Total logs: {{ totalLogs }}
        </div>
      </div>
      
      <div class="logs-container" ref="logsContainerRef">
        <div 
          v-for="(log, index) in filteredLogs" 
          :key="index" 
          :class="['log-item', `log-level-${log.level?.toLowerCase() || 'info'}`]"
        >
          <div class="log-time">{{ formatTime(log.timestamp) }}</div>
          <div class="log-level">{{ log.level || 'INFO' }}</div>
          <div class="log-task" v-if="log.task_id">Task #{{ log.task_id }}</div>
          <div class="log-message">{{ log.message }}</div>
        </div>
        
        <div v-if="filteredLogs.length === 0" class="no-logs">
          {{ t('No logs found') }}
        </div>
      </div>
      
      <div class="logs-pagination" v-if="totalPages > 1">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          :total="totalLogs"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { Refresh } from '@element-plus/icons-vue';
import { useI18nStore } from '../stores/i18n';
import { useTasksStore } from '../stores/tasks';
import { apiService } from '../services/api';

const i18nStore = useI18nStore();
const tasksStore = useTasksStore();
const t = i18nStore.t;

const selectedTaskId = ref('');
const selectedLogLevel = ref('');
const currentPage = ref(1);
const pageSize = ref(50);
const totalLogs = ref(0);
const totalPages = computed(() => Math.ceil(filteredLogs.value.length / pageSize.value));
const autoRefresh = ref(true);
const refreshInterval = ref<number | null>(null);

interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
  task_id?: string;
}

const logs = ref<LogEntry[]>([]);
const logsContainerRef = ref<HTMLElement | null>(null);
const ws = ref<WebSocket | null>(null);
const isWebSocketConnected = ref(false);

const wsStatus = ref({
  text: 'Disconnected',
  type: 'danger'
});



const tasks = computed(() => tasksStore.tasks);

const filteredLogs = computed(() => {
  let result = [...logs.value];

  // Sort logs by timestamp (newest first)
  result.sort((a, b) => {
    const dateA = new Date(a.timestamp).getTime();
    const dateB = new Date(b.timestamp).getTime();
    return dateB - dateA;
  });

  if (selectedTaskId.value) {
    result = result.filter(log => log.task_id === selectedTaskId.value);
  }

  if (selectedLogLevel.value) {
    result = result.filter(log => log.level?.toLowerCase() === selectedLogLevel.value);
  }

  const start = (currentPage.value - 1) * pageSize.value;
  const end = start + pageSize.value;
  return result.slice(start, end);
});

const formatTime = (timestamp: string) => {
  const date = new Date(timestamp);
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  });
};

const fetchLogs = async () => {
  try {
    const response = await apiService.getLogs({
      level: selectedLogLevel.value || undefined,
      task_id: selectedTaskId.value || undefined,
      limit: 1000,
      offset: 0
    });
    console.log('Logs response:', response);
    
    if (response.status === 200) {
      const responseData = response.data as { logs: LogEntry[], total: number } | undefined;
      if (responseData && responseData.logs) {
        console.log('Logs data:', responseData);
        logs.value = responseData.logs || [];
        console.log('Logs array:', logs.value);
        totalLogs.value = responseData.total || 0;
        console.log('Total logs:', totalLogs.value);
        
        scrollToBottom();
      }
    }
  } catch (error) {
    console.error('Failed to fetch logs:', error);
  }
};

const scrollToBottom = () => {
  setTimeout(() => {
    if (logsContainerRef.value) {
      logsContainerRef.value.scrollTop = logsContainerRef.value.scrollHeight;
    }
  }, 100);
};

const connectWebSocket = () => {
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${wsProtocol}//localhost:8000/api/v1/logs/ws`;
  
  console.log('[WS] Attempting to connect to:', wsUrl);
  
  if (ws.value) {
    try {
      ws.value.close();
    } catch (e) {
      console.log('[WS] Error closing existing WebSocket:', e);
    }
  }
  
  ws.value = new WebSocket(wsUrl);
  
  ws.value.onopen = () => {
    console.log('[WS] Connected successfully');
    isWebSocketConnected.value = true;
    wsStatus.value = {
      text: 'Connected',
      type: 'success'
    };
  };
  
  ws.value.onmessage = (event) => {
    try {
      console.log('[WS] Raw message received:', event.data);
      const newLog: LogEntry = JSON.parse(event.data);
      console.log('[WS] Parsed log:', newLog);
      
      logs.value.unshift(newLog);
      totalLogs.value++;
      console.log('[WS] Log added to array, total:', logs.value.length);
      
      scrollToBottom();
    } catch (error) {
      console.error('[WS] Error parsing message:', error);
    }
  };
  
  ws.value.onclose = (event) => {
    console.log('[WS] Disconnected - Code:', event.code, 'Reason:', event.reason);
    isWebSocketConnected.value = false;
    wsStatus.value = {
      text: 'Disconnected',
      type: 'danger'
    };
    
    if (event.code !== 1000) {
      console.log('[WS] Reconnecting in 3 seconds...');
      setTimeout(connectWebSocket, 3000);
    }
  };
  
  ws.value.onerror = (event) => {
    console.error('[WS] Error event:', event);
    wsStatus.value = {
      text: 'Error',
      type: 'danger'
    };
  };
};

const refreshLogs = () => {
  fetchLogs();
};

const handleSizeChange = (size: number) => {
  pageSize.value = size;
  currentPage.value = 1;
};

const handleCurrentChange = (page: number) => {
  currentPage.value = page;
};

const toggleAutoRefresh = () => {
  autoRefresh.value = !autoRefresh.value;
  if (autoRefresh.value) {
    startAutoRefresh();
  } else {
    stopAutoRefresh();
  }
};

const startAutoRefresh = () => {
  if (refreshInterval.value) {
    clearInterval(refreshInterval.value);
  }
  refreshInterval.value = window.setInterval(() => {
    fetchLogs();
  }, 3000);
};

const stopAutoRefresh = () => {
  if (refreshInterval.value) {
    clearInterval(refreshInterval.value);
    refreshInterval.value = null;
  }
};

onMounted(async () => {
  await tasksStore.fetchAllTasks();
  await fetchLogs();
  startAutoRefresh();
  connectWebSocket();
});

onUnmounted(() => {
  stopAutoRefresh();
  // Close WebSocket connection
  if (ws.value) {
    ws.value.close();
  }
});
</script>

<style scoped>
.logs-view {
  padding: 20px 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.title {
  margin: 0;
  font-size: 1.2rem;
  font-weight: 600;
}

.logs-filter {
  margin-bottom: 20px;
}

.filter-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.log-count {
  font-size: 12px;
  color: #666;
  margin-top: 5px;
}

.task-select {
  min-width: 250px;
}

.level-select {
  min-width: 120px;
}

.ws-status {
  margin-left: 10px;
  padding: 2px 8px;
}

.logs-container {
  border: 1px solid #e8e8e8;
  border-radius: 4px;
  padding: 10px;
  max-height: 400px;
  overflow-y: auto;
  background-color: #fafafa;
  font-family: monospace;
  font-size: 13px;
  line-height: 1.5;
}

.log-item {
  display: flex;
  margin-bottom: 8px;
  padding: 5px 10px;
  border-radius: 3px;
  background-color: white;
  border-left: 4px solid #d9d9d9;
}

.log-time {
  min-width: 150px;
  color: #999;
  margin-right: 15px;
}

.log-level {
  min-width: 80px;
  font-weight: 600;
  margin-right: 15px;
}

.log-task {
  min-width: 100px;
  color: #666;
  margin-right: 15px;
}

.log-message {
  flex: 1;
  word-break: break-all;
}

.log-level-info {
  border-left-color: #52c41a;
}

.log-level-warning {
  border-left-color: #faad14;
}

.log-level-error {
  border-left-color: #f5222d;
}

.no-logs {
  text-align: center;
  padding: 40px;
  color: #999;
}

.logs-pagination {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}
</style>