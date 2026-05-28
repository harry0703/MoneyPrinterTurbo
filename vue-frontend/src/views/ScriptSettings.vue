<template>
  <div class="script-settings">
    <!-- Script Settings Card -->
    <el-card :body-style="{ padding: '20px' }" class="main-card">
      <template #header>
        <div class="card-header">
          <h2 class="title">✏️ {{ t('Script Settings') }}</h2>
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
          <div class="scene-count">{{ t('Total Scenes') }}: {{ scenes.length }}</div>
        </div>
        
        <!-- Title Text -->
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Title Text'))"></label>
          <el-input
            v-model="form.videoTitle"
            :placeholder="t('Enter title text')"
            type="text"
            maxlength="100"
            show-word-limit
            class="form-input"
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
                      <span class="intro-video-file">{{ getIntroVideoDisplayName(scene.introVideo) }}</span>
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
                    accept=".mp4,.mov,.avi,.flv,.mkv,.jpg,.jpeg,.png,.gif"
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
import api from '../services/api';

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
  introVideoOriginalPath?: string;
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
    introVideoOriginalPath: sceneToCopy.introVideoOriginalPath,
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
const exportScenes = async () => {
  if (scenes.value.length === 0) {
    ElMessage.warning('No scenes to export');
    return;
  }
  
  // Convert to snake_case for backend compatibility (avoid duplicate keys)
  const exportData = {
    video_title: form.videoTitle,
    scenes: scenes.value.map(scene => ({
      id: scene.id,
      duration: scene.duration,
      visual_requirement: scene.visual_requirement,
      keywords: scene.keywords,
      script: scene.script,
      intro_video: scene.introVideo,
      intro_video_original_path: scene.introVideoOriginalPath,
      intro_duration: scene.introVideoDuration,
    }))
  };
  const scenesData = JSON.stringify(exportData, null, 2);
  const blob = new Blob([scenesData], { type: 'application/json' });
  const fileName = `scenes-${new Date().toISOString().split('T')[0]}.json`;
  
  try {
    // Try to use File System Access API for "Save As" dialog
    const showSaveFilePicker = (window as any).showSaveFilePicker;
    if (showSaveFilePicker) {
      const handle = await showSaveFilePicker({
        suggestedName: fileName,
        types: [{
          description: 'JSON File',
          accept: { 'application/json': ['.json'] }
        }]
      });
      
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      
      ElMessage.success('Scenes exported successfully');
    } else {
      // Fallback for browsers that don't support File System Access API
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      
      ElMessage.success('Scenes exported successfully');
    }
  } catch (error: any) {
    // User cancelled the save dialog or an error occurred
    if (error.name !== 'AbortError') {
      console.error('Export failed:', error);
      ElMessage.error('Failed to export scenes');
    }
    // If user cancelled, silently do nothing
  }
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
      
      let importedData;
      try {
        importedData = JSON.parse(content);
      } catch (parseError) {
        ElMessage.error('Invalid JSON format: ' + (parseError as Error).message);
        console.error('JSON parse error:', parseError);
        input.value = '';
        return;
      }
      
      let importedScenes: any[];
      let videoTitle = '';
      
      if (Array.isArray(importedData)) {
        importedScenes = importedData;
      } else if (importedData && typeof importedData === 'object' && Array.isArray(importedData.scenes)) {
        importedScenes = importedData.scenes;
        videoTitle = importedData.video_title || importedData.videoTitle || '';
      } else {
        ElMessage.error('Imported file must contain an array of scenes or an object with scenes property');
        input.value = '';
        return;
      }
      
      const validScenes = importedScenes.filter((scene: any) => {
        return scene && typeof scene === 'object' && 
               typeof scene.duration === 'number' &&
               typeof scene.visual_requirement === 'string' &&
               typeof scene.keywords === 'string' &&
               typeof scene.script === 'string';
      });
      
      if (validScenes.length > 0) {
        const formattedScenes = validScenes.map((scene: any) => {
          let introVideo = scene.introVideo || scene.intro_video;
          let introVideoOriginalPath = scene.introVideoOriginalPath || scene.intro_video_original_path;
          let introVideoDuration = scene.introVideoDuration || scene.intro_duration || 10;
          
          if (introVideo && typeof introVideo === 'string') {
            introVideo = introVideo.trim();
            if (!introVideo || introVideo.length === 0) {
              introVideo = undefined;
              introVideoDuration = 10;
            }
          } else {
            introVideo = undefined;
            introVideoDuration = 10;
          }
          
          if (!introVideo && introVideoOriginalPath) {
            introVideoOriginalPath = introVideoOriginalPath.trim();
            if (!introVideoOriginalPath || introVideoOriginalPath.length === 0) {
              introVideoOriginalPath = undefined;
            }
          }
          
          return {
            id: scene.id || Date.now().toString() + Math.random().toString(36).substr(2, 9),
            duration: scene.duration,
            visual_requirement: scene.visual_requirement,
            keywords: scene.keywords,
            script: scene.script,
            introVideo,
            introVideoOriginalPath,
            introVideoDuration
          };
        });
        
        scriptStore.updateScenes(formattedScenes);
        
        if (videoTitle) {
          scriptStore.updateVideoTitle(videoTitle);
        }
        
        const scenesWithIntroVideo = formattedScenes.filter((s: any) => s.introVideo);
        if (scenesWithIntroVideo.length > 0) {
          ElMessage.success(`Successfully imported ${validScenes.length} scenes (${scenesWithIntroVideo.length} have intro videos - please verify file paths exist)`);
        } else {
          ElMessage.success(`Successfully imported ${validScenes.length} scenes`);
        }
      } else {
        ElMessage.error('Imported file format is incorrect - no valid scenes found');
      }
    } catch (error) {
      ElMessage.error('Error importing file: ' + (error as Error).message);
      console.error('Import error:', error);
    } finally {
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

// Validate intro video file
const validateIntroVideo = (file: File): { valid: boolean; message: string } => {
  const allowedExtensions = ['.mp4', '.mov', '.avi', '.flv', '.mkv', '.jpg', '.jpeg', '.png', '.gif'];
  const fileName = file.name.toLowerCase();
  const isValidExtension = allowedExtensions.some(ext => fileName.endsWith(ext));
  
  if (!isValidExtension) {
    return { valid: false, message: `Invalid file format. Allowed formats: ${allowedExtensions.join(', ')}` };
  }
  
  const maxSizeMB = 100;
  const maxSizeBytes = maxSizeMB * 1024 * 1024;
  if (file.size > maxSizeBytes) {
    return { valid: false, message: `File size exceeds ${maxSizeMB}MB limit` };
  }
  
  return { valid: true, message: 'Valid file' };
};

// Import intro video
const importIntroVideo = async (event: Event, index: number) => {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  
  if (!file) return;
  
  // Validate file first
  const validation = validateIntroVideo(file);
  if (!validation.valid) {
    ElMessage.warning(`Intro video validation failed: ${validation.message}`);
    input.value = '';
    return;
  }
  
  try {
    // Upload immediately to storage/local_videos/
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await api.post('/video_materials', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
    
    if (response.data.status === 200 && response.data.data?.file) {
      const fullPath = response.data.data.file;
      const updatedScene = { 
        ...scenes.value[index], 
        introVideo: fullPath,
        introVideoOriginalPath: file.name,
        introVideoDuration: scenes.value[index].introVideoDuration || 10
      };
      scriptStore.updateScene(index, updatedScene);
      ElMessage.success('Intro video uploaded successfully');
    } else {
      ElMessage.error('Failed to upload intro video');
    }
  } catch (error) {
    console.error('Error uploading intro video:', error);
    ElMessage.error('Failed to upload intro video');
  } finally {
    // Reset file input to allow selecting the same file again
    input.value = '';
  }
};

// Clear intro video
const clearIntroVideo = (index: number) => {
  const updatedScene = { ...scenes.value[index], introVideo: undefined, introVideoOriginalPath: undefined, introVideoDuration: 10 };
  scriptStore.updateScene(index, updatedScene);
  ElMessage.success('Intro video cleared');
};

// Get display name for intro video (show only filename, not full path)
const getIntroVideoDisplayName = (fullPath: string): string => {
  if (!fullPath) return '';
  // Handle both Windows and Unix paths
  const parts = fullPath.split(/[\\/]/);
  return parts[parts.length - 1];
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

watch(
  () => form.videoTitle,
  (newValue) => {
    scriptStore.updateVideoTitle(newValue);
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
      
      // Auto-generate video title from the first scene if not already set
      if (!form.videoTitle && response.scenes.length > 0) {
        const firstScene = response.scenes[0];
        let generatedTitle = '';
        
        if (firstScene.visual_requirement && firstScene.visual_requirement.length > 0) {
          generatedTitle = firstScene.visual_requirement;
        } else if (firstScene.script && firstScene.script.length > 0) {
          generatedTitle = firstScene.script;
        }
        
        if (generatedTitle.length > 0) {
          generatedTitle = generatedTitle.trim();
          // Truncate to 100 characters
          if (generatedTitle.length > 100) {
            generatedTitle = generatedTitle.substring(0, 100) + '...';
          }
          scriptStore.updateVideoTitle(generatedTitle);
        }
      }
      
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



.settings-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin: 0;
  padding: 0;
}

.form-label {
  font-size: 14px;
  margin-bottom: 4px;
  margin-top: 0;
  padding: 0;
}

.form-input {
  width: 100%;
  margin-top: 0;
}

.form-input :deep(.el-input) {
  margin-top: 0;
}

.form-textarea {
  width: 100%;
  margin-top: 0;
}

.form-textarea :deep(.el-textarea) {
  margin-top: 0;
}

.form-select {
  width: 100%;
  margin-top: 0;
}

.form-select :deep(.el-select) {
  margin-top: 0;
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
  align-items: center;
}

.scene-count {
  margin-left: auto;
  padding: 6px 12px;
  color: #666;
  font-size: 14px;
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
  gap: 16px;
}

.scene-content .form-item {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin: 0;
  padding: 0;
}

.scene-content .form-label {
  font-size: 14px;
  margin-bottom: 4px;
  margin-top: 0;
  padding: 0;
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