<template>
  <div class="scene-integration">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">🎬 {{ t('Scene Integration') }}</h2>
        </div>
      </template>
      
      <div class="integration-content">
        <!-- 输入类型选择 -->
        <div class="form-item">
          <label class="form-label">{{ t('Input Type') }}</label>
          <el-radio-group v-model="inputType">
            <el-radio label="taskId">{{ t('Task ID') }}</el-radio>
            <el-radio label="directory">{{ t('Task Directory') }}</el-radio>
          </el-radio-group>
        </div>
        
        <!-- 任务输入 -->
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
        
        <!-- 扫描按钮 -->
        <div class="form-item">
          <el-button type="primary" class="form-button" @click="scanTask">{{ t('Scan') }}</el-button>
        </div>
        
        <!-- 扫描结果 -->
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
              :title="taskFiles.sceneAudio > 0 ? `✅ ${t('Scene Audio')}: ${taskFiles.sceneAudio} ${t('items')}` : '⚠️ 未找到场景音频'"
              :closable="false"
            />
            
            <el-alert
              :type="taskFiles.subtitle ? 'success' : 'warning'"
              :title="taskFiles.subtitle ? `✅ ${t('Subtitle File')}: 1 ${t('items')}` : '⚠️ 未找到字幕文件'"
              :closable="false"
            />
          </div>
          
          <!-- 场景范围选择 -->
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
          
          <!-- 开始集成按钮 -->
          <div v-if="taskFiles.sceneVideos > 0" class="form-item">
            <el-button
              type="primary"
              class="form-button"
              @click="startIntegration"
              :disabled="isRunning"
            >
              {{ isRunning ? '集成中...' : t('Start Integration') }}
            </el-button>
          </div>
          
          <!-- 进度条 -->
          <div v-if="isRunning" class="progress-container">
            <el-progress
              :percentage="progress"
              :status="progress === 100 ? 'success' : ''"
            />
            <div class="progress-status">{{ status }}</div>
          </div>
          
          <!-- 集成结果 -->
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
import { ref, reactive, watch } from 'vue';
import { useI18nStore } from '../stores/i18n';

const i18nStore = useI18nStore();
const t = i18nStore.t;

// 输入类型
const inputType = ref('taskId');
// 任务输入
const taskInput = ref('');
// 任务文件信息
const taskFiles = ref<any>(null);
// 开始场景
const startScene = ref(1);
// 结束场景
const endScene = ref(1);
// 是否正在运行
const isRunning = ref(false);
// 进度
const progress = ref(0);
// 状态
const status = ref('');
// 集成结果
const integrationResult = ref('');

// 监听开始场景变化，更新结束场景
watch(startScene, (newStart) => {
  if (endScene.value < newStart) {
    endScene.value = newStart;
  }
});

// 扫描任务
const scanTask = () => {
  if (!taskInput.value) {
    return;
  }
  
  // 模拟扫描过程
  status.value = t('Scanning task directory...');
  isRunning.value = true;
  
  // 模拟API调用
  setTimeout(() => {
    // 模拟扫描结果
    taskFiles.value = {
      sceneVideos: 5,
      sceneAudio: 5,
      subtitle: true
    };
    
    startScene.value = 1;
    endScene.value = 5;
    isRunning.value = false;
    status.value = '';
  }, 1000);
};

// 开始集成
const startIntegration = () => {
  if (!taskInput.value || !taskFiles.value) {
    return;
  }
  
  isRunning.value = true;
  progress.value = 0;
  status.value = t('Starting...');
  
  // 模拟集成过程
  let currentProgress = 0;
  const interval = setInterval(() => {
    currentProgress += 10;
    progress.value = currentProgress;
    
    if (currentProgress < 30) {
      status.value = '处理场景视频...';
    } else if (currentProgress < 60) {
      status.value = '处理音频...';
    } else if (currentProgress < 90) {
      status.value = '处理字幕...';
    } else {
      status.value = '生成最终视频...';
    }
    
    if (currentProgress >= 100) {
      clearInterval(interval);
      isRunning.value = false;
      status.value = t('Scene integration completed');
      integrationResult.value = 'output/video_integration.mp4';
    }
  }, 500);
};

// 下载视频
const downloadVideo = () => {
  // 模拟下载
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

.title {
  font-weight: bold;
  font-size: 20px;
  margin: 0;
  color: #333;
}

.integration-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-label {
  font-weight: normal;
  font-size: 14px;
  color: #333;
  margin: 0;
  line-height: 1.4;
}

.form-input {
  width: 100%;
  border: 1px solid #e0e0e0;
  background-color: transparent;
  padding: 6px 8px;
  font-size: 14px;
  border-radius: 4px;
  transition: border-color 0.2s;
  box-sizing: border-box;
}

.form-input:hover {
  border-color: #000;
}

.form-input:focus {
  outline: none;
  border-color: #000;
}

.form-select {
  width: 100%;
  border: 1px solid #e0e0e0;
  background-color: transparent;
  padding: 6px 8px;
  font-size: 14px;
  border-radius: 4px;
  transition: border-color 0.2s;
  box-sizing: border-box;
}

.form-select:hover {
  border-color: #000;
}

.form-select:focus {
  outline: none;
  border-color: #000;
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