<template>
  <div class="scene-integration">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <span>{{ t('Scene Integration') }}</span>
          <el-button type="primary" @click="addScene">
            <el-icon><Plus /></el-icon>
            {{ t('Add Scene') }}
          </el-button>
        </div>
      </template>
      
      <div v-if="scenes.length === 0" class="empty-scenes">
        <el-empty description="{{ t('No scenes yet, click Add Scene to create one') }}" />
      </div>
      
      <div v-else class="scenes-list">
        <el-collapse v-model="activeScenes">
          <el-collapse-item v-for="(scene, index) in scenes" :key="scene.id" :title="getSceneTitle(scene, index)" :name="scene.id">
            <div class="scene-content">
              <el-form :model="scene" label-width="120px">
                <el-form-item label="Duration (s)">
                  <el-input-number v-model="scene.duration" :min="1" :max="60" :step="1" />
                </el-form-item>
                
                <el-form-item label="Visual Requirement">
                  <el-input
                    v-model="scene.visual_requirement"
                    type="textarea"
                    :rows="3"
                    placeholder="Enter visual requirements"
                  />
                </el-form-item>
                
                <el-form-item label="Script">
                  <el-input
                    v-model="scene.script"
                    type="textarea"
                    :rows="4"
                    placeholder="Enter scene script"
                  />
                </el-form-item>
                
                <el-form-item label="Keywords">
                  <el-input
                    v-model="scene.keywords"
                    placeholder="Enter keywords separated by commas"
                  />
                </el-form-item>
                
                <div class="scene-actions">
                  <el-button type="primary" size="small" @click="moveSceneUp(index)">
                    <el-icon><Top /></el-icon>
                    {{ t('Move Up') }}
                  </el-button>
                  <el-button type="primary" size="small" @click="moveSceneDown(index)">
                    <el-icon><Bottom /></el-icon>
                    {{ t('Move Down') }}
                  </el-button>
                  <el-button type="danger" size="small" @click="deleteScene(index)">
                    <el-icon><Delete /></el-icon>
                    {{ t('Delete') }}
                  </el-button>
                </div>
              </el-form>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
      
      <div class="smart-parser-section">
        <el-card :body-style="{ padding: '15px' }">
          <div class="parser-header">
            <span>{{ t('Smart Script Parser') }}</span>
            <el-button type="primary" @click="parseScript">
              <el-icon><Document /></el-icon>
              {{ t('Parse Script') }}
            </el-button>
          </div>
          
          <el-form-item label="Script to Parse">
            <el-input
              v-model="scriptToParse"
              type="textarea"
              :rows="5"
              placeholder="Paste your script here for automatic scene parsing"
            />
          </el-form-item>
        </el-card>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue';
import { Plus, Top, Bottom, Delete, Document } from '@element-plus/icons-vue';
import { useI18nStore } from '../stores/i18n';

interface Scene {
  id: string;
  duration: number;
  visual_requirement: string;
  script: string;
  keywords: string;
}

const i18nStore = useI18nStore();
const t = i18nStore.t;

const scenes = ref<Scene[]>([]);
const activeScenes = ref<string[]>([]);
const scriptToParse = ref('');

const addScene = () => {
  const newScene: Scene = {
    id: Date.now().toString(),
    duration: 30,
    visual_requirement: '',
    script: '',
    keywords: ''
  };
  scenes.value.push(newScene);
  activeScenes.value = [newScene.id];
};

const deleteScene = (index: number) => {
  scenes.value.splice(index, 1);
  if (scenes.value.length > 0) {
    activeScenes.value = [scenes.value[0].id];
  } else {
    activeScenes.value = [];
  }
};

const moveSceneUp = (index: number) => {
  if (index > 0) {
    const temp = scenes.value[index];
    scenes.value[index] = scenes.value[index - 1];
    scenes.value[index - 1] = temp;
  }
};

const moveSceneDown = (index: number) => {
  if (index < scenes.value.length - 1) {
    const temp = scenes.value[index];
    scenes.value[index] = scenes.value[index + 1];
    scenes.value[index + 1] = temp;
  }
};

const getSceneTitle = (scene: Scene, index: number): string => {
  const scriptPreview = scene.script.substring(0, 30) + (scene.script.length > 30 ? '...' : '');
  return `Scene ${index + 1}: ${scriptPreview}`;
};

const parseScript = () => {
  // 这里实现智能脚本解析逻辑
  // 暂时简单分割为场景
  if (scriptToParse.value) {
    const lines = scriptToParse.value.split('\n');
    const newScenes: Scene[] = [];
    
    let currentScene: Scene = {
      id: Date.now().toString(),
      duration: 30,
      visual_requirement: '',
      script: '',
      keywords: ''
    };
    
    lines.forEach(line => {
      line = line.trim();
      if (line.startsWith('[Scene') || line.startsWith('Scene')) {
        if (currentScene.script) {
          newScenes.push(currentScene);
          currentScene = {
            id: Date.now().toString() + Math.random(),
            duration: 30,
            visual_requirement: '',
            script: '',
            keywords: ''
          };
        }
      } else if (line) {
        currentScene.script += line + '\n';
      }
    });
    
    if (currentScene.script) {
      newScenes.push(currentScene);
    }
    
    if (newScenes.length > 0) {
      scenes.value = newScenes;
      activeScenes.value = [newScenes[0].id];
    }
  }
};

defineExpose({
  scenes
});
</script>

<style scoped>
.scene-integration {
  width: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.empty-scenes {
  padding: 40px 0;
  text-align: center;
}

.scenes-list {
  margin-top: 20px;
}

.scene-content {
  padding: 10px 0;
}

.scene-actions {
  display: flex;
  gap: 10px;
  margin-top: 15px;
}

.smart-parser-section {
  margin-top: 30px;
}

.parser-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
}
</style>