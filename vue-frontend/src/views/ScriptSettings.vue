<template>
  <div class="script-settings">
    <!-- 文案设置卡片 -->
    <el-card :body-style="{ padding: '20px' }" class="main-card">
      <template #header>
        <div class="card-header">
          <h2 class="title">文案设置</h2>
        </div>
      </template>
      
      <div class="settings-form">
        <div class="form-item">
          <label class="form-label">视频主题（给定一个关键词，<span style="color: red;">AI自动生成视频文案</span>）</label>
          <el-input
            v-model="form.videoSubject"
            placeholder="输入视频主题"
            type="text"
            maxlength="100"
            show-word-limit
            class="form-input"
          />
        </div>
        
        <div class="form-item">
          <label class="form-label">生成视频脚本的语言（一般情况AI会自动根据你输入的主题语言输出）</label>
          <el-select v-model="form.language" placeholder="选择语言" class="form-select">
            <el-option label="自动检测" value="auto" />
            <el-option label="Chinese" value="zh" />
            <el-option label="English" value="en" />
            <el-option label="German" value="de" />
            <el-option label="Portuguese" value="pt" />
            <el-option label="Russian" value="ru" />
            <el-option label="Turkish" value="tr" />
            <el-option label="Vietnamese" value="vi" />
          </el-select>
        </div>
        
        <div class="form-item">
          <el-button type="primary" class="form-button">根据主题生成【视频文案】</el-button>
        </div>
        
        <div class="form-item">
          <label class="form-label">视频文案 <span style="color: blue;">（①可不填，使用AI生成 ②合理使用标点断句，有助于生成字幕）</span></label>
          <el-input
            v-model="form.videoScript"
            placeholder="输入视频文案"
            type="textarea"
            :rows="6"
            maxlength="5000"
            show-word-limit
            class="form-textarea"
          />
        </div>
        
        <div class="form-item">
          <el-button type="primary" class="form-button">解析当前【视频文案】</el-button>
        </div>
      </div>
    </el-card>
    
    <!-- 场景管理卡片 -->
    <el-card :body-style="{ padding: '20px' }" class="scene-card-container">
      <template #header>
        <div class="card-header">
          <h2 class="title">🎬 场景管理</h2>
        </div>
      </template>
      
      <div class="scene-management-content">
        <!-- 导入导出按钮 -->
        <div class="scene-actions">
          <el-button size="small" @click="exportScenes">导出场景</el-button>
          <el-button size="small" @click="triggerImport">导入场景</el-button>
          <input
            ref="fileInput"
            type="file"
            accept=".json"
            style="display: none"
            @change="importScenes"
          />
        </div>
        
        <!-- 场景列表 -->
        <div class="scenes-list">
          <div v-for="(scene, index) in scenes" :key="scene.id" class="scene-card">
            <div class="scene-header">
              <div class="scene-title">场景 {{ index + 1 }}</div>
              <div class="scene-header-actions">
                <el-button size="small" @click="deleteScene(index)">删除</el-button>
                <el-button size="small" @click="copyScene(index)">复制</el-button>
                <el-button size="small" @click="moveSceneUp(index)" :disabled="index === 0">上移</el-button>
                <el-button size="small" @click="moveSceneDown(index)" :disabled="index === scenes.length - 1">下移</el-button>
              </div>
            </div>
            
            <div class="scene-content">
              <div class="form-item">
                <label class="form-label">时长（秒）</label>
                <el-input v-model.number="scene.duration" type="number" placeholder="输入时长" class="form-input" />
              </div>
              
              <div class="form-item">
                <label class="form-label">视觉需求</label>
                <el-input v-model="scene.visual_requirement" type="textarea" :rows="3" placeholder="输入详细描述" class="form-textarea" />
              </div>
              
              <div class="form-item">
                <label class="form-label">关键词（逗号分隔）</label>
                <el-input v-model="scene.keywords" placeholder="输入关键词" class="form-input" />
              </div>
              
              <div class="form-item">
                <label class="form-label">场景文案</label>
                <el-input v-model="scene.script" type="textarea" :rows="4" placeholder="输入场景文案" class="form-textarea" />
              </div>
              
              <div class="form-item">
                <label class="form-label">片头视频</label>
                <div class="intro-video-section">
                  <div class="intro-video-info" v-if="scene.introVideo">
                    <div class="intro-video-path">
                      <span class="intro-video-file">{{ scene.introVideo }}</span>
                      <el-button size="small" @click="clearIntroVideo(index)">清除</el-button>
                    </div>
                    <div class="intro-video-duration">
                      <el-icon class="video-icon"><VideoCamera /></el-icon>
                      <el-input v-model.number="scene.introVideoDuration" type="number" placeholder="时长" class="duration-input" />
                      <span class="duration-unit">s</span>
                    </div>
                  </div>
                  <div class="intro-video-placeholder" v-else>
                    <span>未设置</span>
                    <el-button size="small" @click="triggerIntroVideoImport(index)">导入片头视频</el-button>
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
        
        <!-- 添加新场景按钮 -->
        <div class="form-item">
          <el-button type="primary" class="form-button" @click="addNewScene">添加新场景</el-button>
        </div>
      </div>
    </el-card>
    

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import { useI18nStore } from '../stores/i18n';
import { useScriptStore } from '../stores/script';
import { ElMessage } from 'element-plus';
import { VideoCamera } from '@element-plus/icons-vue';

const i18nStore = useI18nStore();
const scriptStore = useScriptStore();
const t = i18nStore.t;

const fileInput = ref<HTMLInputElement | null>(null);
const introVideoFileInputs = ref<{[key: number]: HTMLInputElement | null}>({});

// 从store获取数据
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
  // 复制到index+1位置
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

// 导出场景
const exportScenes = () => {
  if (scenes.value.length === 0) {
    ElMessage.warning('没有场景可以导出');
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
  
  ElMessage.success('场景导出成功');
};

// 触发导入
const triggerImport = () => {
  fileInput.value?.click();
};

// 导入场景
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
        // 验证导入的数据格式
        const validScenes = importedScenes.filter((scene: any) => {
          return scene && typeof scene === 'object' && 
                 typeof scene.duration === 'number' &&
                 typeof scene.visual_requirement === 'string' &&
                 typeof scene.keywords === 'string' &&
                 typeof scene.script === 'string';
        });
        
        if (validScenes.length > 0) {
          // 清空现有场景并导入新场景
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
          ElMessage.success(`成功导入 ${validScenes.length} 个场景`);
        } else {
          ElMessage.error('导入的文件格式不正确');
        }
      } else {
        ElMessage.error('导入的文件格式不正确');
      }
    } catch (error) {
      ElMessage.error('导入文件时出错');
      console.error('Import error:', error);
    } finally {
      // 重置文件输入，以便可以重复选择同一个文件
      input.value = '';
    }
  };
  reader.readAsText(file);
};

// 设置文件输入引用
const setFileInputRef = (el: HTMLInputElement | null, index: number) => {
  if (el) {
    introVideoFileInputs.value[index] = el;
  }
};

// 触发片头视频导入
const triggerIntroVideoImport = (index: number) => {
  introVideoFileInputs.value[index]?.click();
};

// 导入片头视频
const importIntroVideo = (event: Event, index: number) => {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  
  if (!file) return;
  
  // 这里可以添加文件上传逻辑
  // 目前只存储文件名
  const updatedScene = { ...scenes.value[index], introVideo: file.name };
  scriptStore.updateScene(index, updatedScene);
  
  // 重置文件输入，以便可以重复选择同一个文件
  input.value = '';
  
  ElMessage.success('片头视频导入成功');
};

// 清除片头视频
const clearIntroVideo = (index: number) => {
  const updatedScene = { ...scenes.value[index], introVideo: undefined, introVideoDuration: 10 };
  scriptStore.updateScene(index, updatedScene);
  ElMessage.success('片头视频已清除');
};

// 场景变化由store自动处理，不需要额外监听

// 监听表单字段变化，自动保存
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

// 组件挂载时加载数据
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

.form-textarea {
  width: 100%;
  border: 1px solid #e0e0e0;
  background-color: transparent;
  padding: 6px 8px;
  font-size: 14px;
  border-radius: 4px;
  transition: border-color 0.2s;
  box-sizing: border-box;
  resize: vertical;
}

.form-textarea:hover {
  border-color: #000;
}

.form-textarea:focus {
  outline: none;
  border-color: #000;
}

.form-select {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  transition: border-color 0.3s;
  box-sizing: border-box;
}

.form-select:hover {
  border-color: #000;
}

.form-select:focus {
  outline: none;
  border-color: #000;
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