<template>
  <div class="scene-integration">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">🎬 {{ t('Scene Integration') }}</h2>
        </div>
      </template>
      
      <div class="integration-content">
        <!-- Input Type Selection -->
        <div class="form-item">
          <label class="form-label">{{ t('Input Type') }}</label>
          <el-radio-group v-model="inputType">
            <el-radio label="taskId">{{ t('Task ID') }}</el-radio>
            <el-radio label="directory">{{ t('Task Directory') }}</el-radio>
          </el-radio-group>
        </div>
        
        <!-- Task Input -->
        <div class="form-item">
          <label class="form-label" v-if="inputType === 'taskId'">{{ t('Task ID') }}</label>
          <label class="form-label" v-else>{{ t('Task Directory') }}</label>
          <el-input
            v-model="taskInput"
            :placeholder="inputType === 'taskId' ? t('Enter task ID to recover integration') : t('Enter task directory path')"
            class="form-input"
          />
          <div v-if="inputType === 'directory'" class="tip">{{ t('Please enter the full path to the task directory') }}</div>
        </div>
        
        <!-- Scan Button -->
        <div class="form-item">
          <el-button type="primary" class="form-button" @click="scanTask">{{ t('Scan') }}</el-button>
        </div>
        
        <!-- Scan Results -->
        <div v-if="taskFiles" class="scan-results">
          <h3 class="section-title">{{ t('Detected Files') }}</h3>
          
          <div class="file-status">
            <el-alert
              v-if="taskFiles.sceneVideos > 0"
              type="success"
              :title="`✅ ${t('Scene Videos')}: ${taskFiles.sceneVideos} ${t('items')}`"
              :closable="false"
            />
            <el-alert
              v-else
              type="error"
              :title="t('No valid scene videos found in task directory')"
              :closable="false"
            />
            
            <el-alert
              :type="taskFiles.sceneAudio > 0 ? 'success' : 'warning'"
              :title="taskFiles.sceneAudio > 0 ? `✅ ${t('Scene Audio')}: ${taskFiles.sceneAudio} ${t('items')}` : '⚠️ ' + t('No scene audio found')"
              :closable="false"
            />
            
            <el-alert
              :type="taskFiles.subtitle ? 'success' : 'warning'"
              :title="taskFiles.subtitle ? `✅ ${t('Subtitle File')}: 1 ${t('items')}` : '⚠️ ' + t('No subtitle file found')"
              :closable="false"
            />
          </div>
          
          <!-- Scene Range Selection -->
          <div v-if="taskFiles.sceneVideos > 0" class="scene-range">
            <h3 class="section-title">{{ t('Scene Range Selection') }}</h3>
            <div class="range-selectors">
              <div class="form-item">
                <label class="form-label">{{ t('Start Scene') }}</label>
                <el-select v-model="startScene" class="form-select">
                  <el-option
                    v-for="i in taskFiles.sceneVideos"
                    :key="i"
                    :label="i"
                    :value="i"
                  />
                </el-select>
              </div>
              <div class="form-item">
                <label class="form-label">{{ t('End Scene') }}</label>
                <el-select v-model="endScene" class="form-select">
                  <el-option
                    v-for="i in taskFiles.sceneVideos"
                    :key="i"
                    :label="i"
                    :value="i"
                    :disabled="i < startScene"
                  />
                </el-select>
              </div>
            </div>
          </div>
          
          <!-- Start Integration Button -->
          <div v-if="taskFiles.sceneVideos > 0" class="form-item">
            <el-button
              type="primary"
              class="form-button"
              @click="startIntegration"
              :disabled="isRunning"
            >
              {{ isRunning ? t('Integrating...') : t('Start Integration') }}
            </el-button>
          </div>
          
          <!-- Progress Bar -->
          <div v-if="isRunning" class="progress-container">
            <el-progress
              :percentage="progress"
              :status="progress === 100 ? 'success' : ''"
            />
            <div class="progress-status">{{ status }}</div>
          </div>
          
          <!-- Integration Result -->
          <div v-if="integrationResult" class="integration-result">
            <h3 class="section-title">{{ t('Generated Video') }}</h3>
            <div class="video-preview">
              <!-- Video preview would go here -->
              <div class="result-info">
                <span>{{ t('Video path') }}: {{ integrationResult }}</span>
                <el-button type="primary" size="small" @click="downloadVideo">{{ t('Download Video') }}</el-button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onUnmounted, onMounted } from 'vue';
import { useI18nStore } from '../stores/i18n';
import { useSettingsStore } from '../stores/settings';
import { apiService } from '../services/api';

const i18nStore = useI18nStore();
const t = i18nStore.t;
const settingsStore = useSettingsStore();

const STORAGE_KEY = 'moneyprinter-scene-integration';

// Input type
const inputType = ref('taskId');
// Task input
const taskInput = ref('');
// Task file information
const taskFiles = ref<any>(null);
// Start scene
const startScene = ref(1);
// End scene
const endScene = ref(1);
// Whether it's running
const isRunning = ref(false);
// Progress
const progress = ref(0);
// Status
const status = ref('');
// Integration result
const integrationResult = ref('');
// Current task ID for polling
const currentTaskId = ref('');
// Polling interval ID
let pollInterval: number | null = null;

const loadFromLocalStorage = () => {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    try {
      const parsed = JSON.parse(saved);
      inputType.value = parsed.inputType || 'taskId';
      taskInput.value = parsed.taskInput || '';
      startScene.value = parsed.startScene || 1;
      endScene.value = parsed.endScene || 1;
    } catch (e) {
      console.error('Failed to load scene integration settings from localStorage:', e);
    }
  }
};

const saveToLocalStorage = () => {
  const data = {
    inputType: inputType.value,
    taskInput: taskInput.value,
    startScene: startScene.value,
    endScene: endScene.value
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
};

onMounted(() => {
  loadFromLocalStorage();
});

// Watch start scene changes, update end scene
watch(startScene, (newStart) => {
  if (endScene.value < newStart) {
    endScene.value = newStart;
  }
  saveToLocalStorage();
});

watch(inputType, () => saveToLocalStorage());
watch(taskInput, () => saveToLocalStorage());
watch(endScene, () => saveToLocalStorage());

// Scan task
const scanTask = async () => {
  if (!taskInput.value) {
    return;
  }
  
  status.value = t('Scanning task directory...');
  isRunning.value = true;
  
  try {
    const response = await apiService.scanSceneIntegration(taskInput.value);
    if (response.status === 200 && response.data) {
      taskFiles.value = {
        sceneVideos: response.data.sceneVideos,
        sceneAudio: response.data.sceneAudio,
        subtitle: response.data.subtitle,
        totalScenes: response.data.totalScenes,
        isValid: response.data.isValid
      };
      
      startScene.value = 1;
      endScene.value = response.data.sceneVideos || 1;
    } else {
      taskFiles.value = null;
    }
  } catch (error) {
    console.error('Error scanning task:', error);
    taskFiles.value = null;
    status.value = t('Failed to scan task directory');
  } finally {
    isRunning.value = false;
    if (!status.value) {
      status.value = '';
    }
  }
};

// Start integration
const startIntegration = async () => {
  if (!taskInput.value || !taskFiles.value) {
    return;
  }
  
  isRunning.value = true;
  progress.value = 0;
  status.value = t('Starting...');
  integrationResult.value = '';
  
  // Get latest subtitle settings from settings store
  const subtitleParams = {
    subtitle_enabled: settingsStore.subtitle.enable,
    font_name: settingsStore.subtitle.font,
    font_size: settingsStore.subtitle.fontSize,
    text_fore_color: settingsStore.subtitle.color,
    text_background_color: 'transparent',
    stroke_color: settingsStore.subtitle.outlineColor,
    stroke_width: settingsStore.subtitle.outlineWidth,
    subtitle_position: settingsStore.subtitle.position,
    custom_position: parseFloat(settingsStore.subtitle.customPosition) || 70.0
  };
  
  // Get latest BGM settings from settings store
  const bgmParams = {
    bgm_type: settingsStore.audio.backgroundMusic || 'none',
    bgm_file: '',
    bgm_volume: parseFloat(settingsStore.audio.backgroundMusicVolume) || 0.2
  };
  
  try {
    // Merge subtitle and BGM parameters
    const requestParams = { ...subtitleParams, ...bgmParams };
    
    const response = await apiService.recoverSceneIntegration(
      taskInput.value, 
      startScene.value, 
      endScene.value,
      requestParams
    );
    
    if (response.status === 200 && response.data && response.data.task_id) {
      currentTaskId.value = response.data.task_id;
      status.value = t('Integration in progress...');
      startPolling();
    } else {
      status.value = t('Video integration failed');
      isRunning.value = false;
    }
  } catch (error) {
    console.error('Error starting integration:', error);
    status.value = t('Video integration failed');
    isRunning.value = false;
  }
};

// Start polling task status
const startPolling = () => {
  stopPolling();
  
  pollInterval = window.setInterval(async () => {
    try {
      const response = await apiService.getTask(currentTaskId.value);
      if (response.status === 200 && response.data) {
        const task = response.data;
        
        if (task.progress !== undefined) {
          progress.value = task.progress;
        }
        
        if (task.state === 'processing' || task.state === 1) {
          status.value = t('Integration in progress...');
        } else if (task.state === 'complete' || task.state === 2) {
          progress.value = 100;
          status.value = t('Scene integration completed');
          if (task.videos && task.videos.length > 0) {
            integrationResult.value = task.videos[0];
          }
          stopPolling();
          isRunning.value = false;
        } else if (task.state === 'failed' || task.state === 3) {
          status.value = t('Video integration failed');
          stopPolling();
          isRunning.value = false;
        }
      }
    } catch (error) {
      console.error('Error polling task status:', error);
    }
  }, 3000);
};

// Stop polling
const stopPolling = () => {
  if (pollInterval !== null) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
};

// Cleanup on unmount
onUnmounted(() => {
  stopPolling();
});

// Download video
const downloadVideo = () => {
  // Simulate download
  console.log('Downloading video:', integrationResult.value);
};

defineExpose({
  inputType,
  taskInput,
  taskFiles,
  startScene,
  endScene,
  isRunning,
  progress,
  status,
  integrationResult
});
</script>

<style scoped>
.scene-integration {
  width: 100%;
}

.card-header {
  margin-bottom: 4px;
}



.integration-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 0px;
}

.form-label {
  font-weight: normal;
  font-size: 14px;
  color: #333;
  margin-bottom: 4px;
  line-height: 1.4;
}

.form-input {
  width: 100%;
  padding: 6px 8px;
  border-radius: 4px;
  box-sizing: border-box;
}

.form-input :deep(.el-input) {
  width: 100%;
}

.form-select {
  width: 100%;
  padding: 6px 8px;
  border-radius: 4px;
  box-sizing: border-box;
}

.form-select :deep(.el-select) {
  width: 100%;
}

.form-button {
  width: 100%;
  padding: 10px;
  font-size: 14px;
  border-radius: 4px;
  transition: all 0.3s;
}

.form-button:hover {
  opacity: 0.9;
}

.tip {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.scan-results {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #e0e0e0;
}

.section-title {
  font-size: 16px;
  font-weight: bold;
  margin: 15px 0 10px 0;
  color: #333;
}

.file-status {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 15px;
}

.scene-range {
  margin: 15px 0;
}

.range-selectors {
  display: flex;
  gap: 15px;
}

.range-selectors .form-item {
  flex: 1;
}

.progress-container {
  margin: 15px 0;
}

.progress-status {
  text-align: center;
  margin-top: 5px;
  font-size: 14px;
  color: #606266;
}

.integration-result {
  margin-top: 20px;
  padding-top: 15px;
  border-top: 1px solid #e0e0e0;
}

.video-preview {
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  padding: 15px;
  background-color: #f9f9f9;
}

.result-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>