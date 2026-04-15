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
          <el-button size="small">导出场景</el-button>
          <el-button size="small">导入场景</el-button>
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
import { ref, reactive } from 'vue';
import { useI18nStore } from '../stores/i18n';

const i18nStore = useI18nStore();
const t = i18nStore.t;

const form = reactive({
  videoSubject: '',
  videoScript: '',
  language: 'auto'
});

interface Scene {
  id: string;
  duration: number;
  visual_requirement: string;
  keywords: string;
  script: string;
}

const scenes = reactive<Scene[]>([]);

const addNewScene = () => {
  const newScene: Scene = {
    id: Date.now().toString(),
    duration: 30,
    visual_requirement: '',
    keywords: '',
    script: ''
  };
  scenes.push(newScene);
};

const deleteScene = (index: number) => {
  scenes.splice(index, 1);
};

const copyScene = (index: number) => {
  const sceneToCopy = scenes[index];
  const copiedScene: Scene = {
    id: Date.now().toString(),
    duration: sceneToCopy.duration,
    visual_requirement: sceneToCopy.visual_requirement,
    keywords: sceneToCopy.keywords,
    script: sceneToCopy.script
  };
  scenes.splice(index + 1, 0, copiedScene);
};

const moveSceneUp = (index: number) => {
  if (index > 0) {
    const temp = scenes[index];
    scenes[index] = scenes[index - 1];
    scenes[index - 1] = temp;
  }
};

const moveSceneDown = (index: number) => {
  if (index < scenes.length - 1) {
    const temp = scenes[index];
    scenes[index] = scenes[index + 1];
    scenes[index + 1] = temp;
  }
};

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


</style>