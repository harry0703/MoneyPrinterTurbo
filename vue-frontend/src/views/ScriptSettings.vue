<template>
  <div class="script-settings">
    <!-- Script Settings Card -->
    <el-card :body-style="{ padding: '20px' }" class="main-card">
      <template #header>
        <div class="card-header">
          <h2 class="title">{{ t('Script Settings') }}</h2>
        </div>
      </template>
      
      <div class="settings-form">
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Video Topic'))"></label>
          <el-input
            v-model="form.videoSubject"
            :placeholder="t('Enter video topic')"
            type="text"
            maxlength="100"
            show-word-limit
            class="form-input"
          />
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Language for video script'))"></label>
          <el-select v-model="form.language" :placeholder="t('Select language')" class="form-select">
            <el-option :label="t('Auto Detect')" value="auto" />
            <el-option :label="t('Chinese')" value="zh" />
            <el-option :label="t('English')" value="en" />
            <el-option :label="t('German')" value="de" />
            <el-option :label="t('Portuguese')" value="pt" />
            <el-option :label="t('Russian')" value="ru" />
            <el-option :label="t('Turkish')" value="tr" />
            <el-option :label="t('Vietnamese')" value="vi" />
          </el-select>
        </div>
        
        <div class="form-item">
          <el-button type="primary" class="form-button" @click="handleGenerateVideoScript" :loading="loading.generateScript">{{ t('Generate [Video Script] from Topic') }}</el-button>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Video Script'))"></label>
          <el-input
            v-model="form.videoScript"
            :placeholder="t('Enter video script')"
            type="textarea"
            :rows="6"
            maxlength="5000"
            show-word-limit
            class="form-textarea"
          />
        </div>
        
        <div class="form-item">
          <el-button type="primary" class="form-button" @click="parseVideoScript" :loading="loading.parseScript">{{ t('Parse Current [Video Script]') }}</el-button>
        </div>
      </div>
    </el-card>
    
    <!-- Scene Management Card -->
    <el-card :body-style="{ padding: '20px' }" class="scene-card-container">
      <template #header>
        <div class="card-header">
          <h2 class="title">🎬 {{ t('Scene Management') }}</h2>
        </div>
      </template>
      
      <div class="scene-management-content">
        <!-- Import/Export Buttons -->
        <div class="scene-actions">
          <el-button size="small" @click="exportScenes">{{ t('Export Scenes') }}</el-button>
          <el-button size="small" @click="triggerImport">{{ t('Import Scenes') }}</el-button>
          <el-button size="small" type="danger" @click="clearScenes">{{ t('Clear Scenes') }}</el-button>
          <input
            ref="fileInput"
            type="file"
            accept=".json"
            style="display: none"
            @change="importScenes"
          />
        </div>
        
        <!-- Scene List -->
        <div class="scenes-list">
          <div v-for="(scene, index) in scenes" :key="scene.id" class="scene-card">
            <div class="scene-header">
              <div class="scene-title">{{ t('Scene') }} {{ index + 1 }}</div>
              <div class="scene-header-actions">
                <el-button size="small" @click="deleteScene(index)">{{ t('Delete') }}</el-button>
                <el-button size="small" @click="copyScene(index)">{{ t('Copy') }}</el-button>
                <el-button size="small" @click="moveSceneUp(index)" :disabled="index === 0">{{ t('Move Up') }}</el-button>
                <el-button size="small" @click="moveSceneDown(index)" :disabled="index === scenes.length - 1">{{ t('Move Down') }}</el-button>
              </div>
            </div>
            
            <div class="scene-content">
              <div class="form-item">
                <label class="form-label" v-html="parseLabelMarkdown(t('Duration (seconds)'))"></label>
                <el-input v-model.number="scene.duration" type="number" :placeholder="t('Enter duration')" class="form-input" />
              </div>
              
              <div class="form-item">
                <label class="form-label" v-html="parseLabelMarkdown(t('Visual Requirements'))"></label>
                <el-input v-model="scene.visual_requirement" type="textarea" :rows="3" :placeholder="t('Enter detailed description')" class="form-textarea" />
              </div>
              
              <div class="form-item">
                <label class="form-label" v-html="parseLabelMarkdown(t('Keywords (comma separated)'))"></label>
                <el-input v-model="scene.keywords" :placeholder="t('Enter keywords')" class="form-input" />
              </div>
              
              <div class="form-item">
                <label class="form-label" v-html="parseLabelMarkdown(t('Scene Script'))"></label>
                <el-input v-model="scene.script" type="textarea" :rows="4" :placeholder="t('Enter scene script')" class="form-textarea" />
              </div>
              
              <div class="form-item">
                <label class="form-label" v-html="parseLabelMarkdown(t('Intro Video'))"></label>
                <div class="intro-video-section">
                  <div class="intro-video-info" v-if="scene.introVideo">
                    <div class="intro-video-path">
                      <span class="intro-video-file">{{ scene.introVideo }}</span>
                      <el-button size="small" @click="clearIntroVideo(index)">{{ t('Clear') }}</el-button>
                    </div>
                    <div class="intro-video-duration">
                      <el-icon class="video-icon"><VideoCamera /></el-icon>
                      <el-input v-model.number="scene.introVideoDuration" type="number" :placeholder="t('Duration')" class="duration-input" />
                      <span class="duration-unit">{{ t('s') }}</span>
                    </div>
                  </div>
                  <div class="intro-video-placeholder" v-else>
                    <span>{{ t('Not set') }}</span>
                    <el-button size="small" @click="triggerIntroVideoImport(index)">{{ t('Import Intro Video') }}</el-button>
                  </div>
                  <input
                    :ref="el => setFileInputRef(el, index)"
                    type="file"
                    accept=".mp4,.mov,.avi"
                    style="display: none"
                    @change="(e) => importIntroVideo(e, index)"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
        
        <!-- Add New Scene Button -->
        <div class="form-item">
          <el-button type="primary" class="form-button" @click="addNewScene">{{ t('Add New Scene') }}</el-button>
        </div>
      </div>
    </el-card>
    

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import { useScriptStore } from '../stores/script';
import { useI18nStore } from '../stores/i18n';
import { ElMessage } from 'element-plus';
import { VideoCamera } from '@element-plus/icons-vue';
import { parseLabelMarkdown } from '../utils/markdownParser';
import { generateVideoScript, parseVideoScript as apiParseVideoScript } from '../services/api';

const scriptStore = useScriptStore();
const i18nStore = useI18nStore();
const t = i18nStore.t;

const fileInput = ref<HTMLInputElement | null>(null);
const introVideoFileInputs = ref<{[key: number]: HTMLInputElement | null}>({});

// Loading state
const loading = ref({
  generateScript: false,
  parseScript: false
});

// Get data from store
const form = scriptStore;
const scenes = computed(() => scriptStore.scenes);

interface Scene {
  id: string;
  duration: number;
  visual_requirement: string;
  keywords: string;
  script: string;
  introVideo?: string;
  introVideoDuration?: number;
}

const addNewScene = () => {
  const newScene: Scene = {
    id: Date.now().toString(),
    duration: 30,
    visual_requirement: '',
    keywords: '',
    script: '',
    introVideo: undefined,
    introVideoDuration: 10
  };
  scriptStore.addScene(newScene);
};

const deleteScene = (index: number) => {
  scriptStore.removeScene(index);
};

const copyScene = (index: number) => {
  const sceneToCopy = scenes.value[index];
  const copiedScene: Scene = {
    id: Date.now().toString(),
    duration: sceneToCopy.duration,
    visual_requirement: sceneToCopy.visual_requirement,
    keywords: sceneToCopy.keywords,
    script: sceneToCopy.script,
    introVideo: sceneToCopy.introVideo,
    introVideoDuration: sceneToCopy.introVideoDuration
  };
  // Copy to index+1 position
  const newScenes = [...scenes.value];
  newScenes.splice(index + 1, 0, copiedScene);
  scriptStore.updateScenes(newScenes);
};

const moveSceneUp = (index: number) => {
  if (index > 0) {
    const newScenes = [...scenes.value];
    const temp = newScenes[index];
    newScenes[index] = newScenes[index - 1];
    newScenes[index - 1] = temp;
    scriptStore.updateScenes(newScenes);
  }
};

const moveSceneDown = (index: number) => {
  if (index < scenes.value.length - 1) {
    const newScenes = [...scenes.value];
    const temp = newScenes[index];
    newScenes[index] = newScenes[index + 1];
    newScenes[index + 1] = temp;
    scriptStore.updateScenes(newScenes);
  }
};

// Export scenes
const exportScenes = () => {
  if (scenes.value.length === 0) {
    ElMessage.warning('No scenes to export');
    return;
  }
  
  const scenesData = JSON.stringify(scenes.value, null, 2);
  const blob = new Blob([scenesData], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `scenes-${new Date().toISOString().split('T')[0]}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  
  ElMessage.success('Scenes exported successfully');
};

// Clear all scenes
const clearScenes = () => {
  if (scenes.value.length === 0) {
    ElMessage.warning('No scenes to clear');
    return;
  }
  
  scriptStore.updateScenes([]);
  ElMessage.success('All scenes cleared successfully');
};

// Trigger import
const triggerImport = () => {
  fileInput.value?.click();
};

// Import scenes
const importScenes = (event: Event) => {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  
  if (!file) return;
  
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const content = e.target?.result as string;
      const importedScenes = JSON.parse(content);
      
      if (Array.isArray(importedScenes)) {
          // Validate imported data format
          const validScenes = importedScenes.filter((scene: any) => {
            return scene && typeof scene === 'object' && 
                   typeof scene.duration === 'number' &&
                   typeof scene.visual_requirement === 'string' &&
                   typeof scene.keywords === 'string' &&
                   typeof scene.script === 'string';
          });
          
          if (validScenes.length > 0) {
            // Clear existing scenes and import new scenes
            const formattedScenes = validScenes.map((scene: any) => ({
              id: Date.now().toString() + Math.random().toString(36).substr(2, 9),
              duration: scene.duration,
              visual_requirement: scene.visual_requirement,
              keywords: scene.keywords,
              script: scene.script,
              introVideo: scene.introVideo,
              introVideoDuration: scene.introVideoDuration || 10
            }));
            scriptStore.updateScenes(formattedScenes);
            ElMessage.success(`Successfully imported ${validScenes.length} scenes`);
          } else {
            ElMessage.error('Imported file format is incorrect');
          }
        } else {
          ElMessage.error('Imported file format is incorrect');
        }
      } catch (error) {
        ElMessage.error('Error importing file');
        console.error('Import error:', error);
      } finally {
        // Reset file input to allow selecting the same file again
        input.value = '';
      }
  };
  reader.readAsText(file);
};

// Set file input reference
const setFileInputRef = (el: any, index: number) => {
  if (el) {
    introVideoFileInputs.value[index] = el;
  }
};

// Trigger intro video import
const triggerIntroVideoImport = (index: number) => {
  introVideoFileInputs.value[index]?.click();
};

// Import intro video
const importIntroVideo = (event: Event, index: number) => {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  
  if (!file) return;
  
  // File upload logic can be added here
  // Currently only storing file name
  const updatedScene = { ...scenes.value[index], introVideo: file.name };
  scriptStore.updateScene(index, updatedScene);
  
  // Reset file input to allow selecting the same file again
  input.value = '';
  
  ElMessage.success('Intro video imported successfully');
};

// Clear intro video
const clearIntroVideo = (index: number) => {
  const updatedScene = { ...scenes.value[index], introVideo: undefined, introVideoDuration: 10 };
  scriptStore.updateScene(index, updatedScene);
  ElMessage.success('Intro video cleared');
};

// Scene changes are automatically handled by the store, no need for additional listening

// Watch form field changes, auto save
watch(
  () => form.videoSubject,
  (newValue) => {
    scriptStore.updateVideoSubject(newValue);
  }
);

watch(
  () => form.videoScript,
  (newValue) => {
    scriptStore.updateVideoScript(newValue);
  }
);

watch(
  () => form.language,
  (newValue) => {
    scriptStore.updateLanguage(newValue);
  }
);

// Generate video script from topic
const handleGenerateVideoScript = async () => {
  if (!form.videoSubject) {
    ElMessage.warning(t('Please Enter the Video Subject'));
    return;
  }

  loading.value.generateScript = true;
  try {
    // If language is "auto", pass null to let backend detect language
    const language = form.language === 'auto' ? null : form.language;
    const response = await generateVideoScript({
      video_subject: form.videoSubject,
      video_language: language,
      paragraph_number: 1
    });
    form.videoScript = response.video_script;
    ElMessage.success('Video script generated successfully');
  } catch (error) {
    console.error('Error generating video script:', error);
    ElMessage.error('Failed to generate video script. Please try again.');
  } finally {
    loading.value.generateScript = false;
  }
};

// Parse current video script
const parseVideoScript = async () => {
  if (!form.videoScript) {
    ElMessage.warning('Please enter a script first');
    return;
  }

  loading.value.parseScript = true;
  try {
    // If language is "auto", pass null to let backend detect language
    const language = form.language === 'auto' ? null : form.language;
    const response = await apiParseVideoScript({
      video_script: form.videoScript,
      language: language
    });
    
    if (response.status === 'success' || response.status === 'manual') {
      // Update scenes in store
      scriptStore.updateScenes(response.scenes);
      ElMessage.success(`Successfully parsed ${response.scenes.length} scenes`);
    } else {
      ElMessage.error('Failed to parse script. Please try again.');
    }
  } catch (error) {
    console.error('Error parsing video script:', error);
    ElMessage.error('Failed to parse script. Please try again.');
  } finally {
    loading.value.parseScript = false;
  }
};

// Load data when component is mounted
onMounted(() => {
  scriptStore.loadFromLocalStorage();
});

defineExpose({
  form,
  scenes
});
</script>

<style scoped>
.script-settings {
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

.settings-form {
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

.form-textarea {
  width: 100%;
  padding: 6px 8px;
  border-radius: 4px;
  box-sizing: border-box;
  resize: vertical;
}

.form-textarea :deep(.el-input) {
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

.tip {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
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

/* 卡片布局样式 */
.main-card {
  margin-bottom: 20px;
}

.scene-card-container {
  margin-bottom: 20px;
}

/* 场景管理样式 */
.scene-management-content {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.scene-actions {
  display: flex;
  gap: 10px;
}

.scenes-list {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.scene-card {
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  padding: 15px;
  background-color: #f9f9f9;
}

.scene-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
  padding-bottom: 10px;
  border-bottom: 1px solid #e0e0e0;
}

.scene-title {
  font-weight: bold;
  font-size: 14px;
  color: #333;
}

.scene-header-actions {
  display: flex;
  gap: 5px;
}

.scene-content {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.intro-video-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.intro-video-info {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.intro-video-path {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.intro-video-file {
  font-size: 14px;
  color: #1890ff;
  flex: 1;
  min-width: 200px;
  background-color: #f5f5f5;
  padding: 6px 8px;
  border-radius: 4px;
}

.intro-video-placeholder {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: #909399;
}

.intro-video-duration {
  display: flex;
  align-items: center;
  gap: 10px;
}

.video-icon {
  color: #1890ff;
  font-size: 18px;
}

.duration-input {
  width: 80px;
}

.duration-unit {
  font-size: 14px;
  color: #606266;
}


</style>