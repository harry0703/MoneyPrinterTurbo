<template>
  <div class="app">
    <header class="app-header">
      <div class="header-content">
        <h1>{{ t('MoneyPrinterCN') }} <span v-if="settingsStore.version" class="version">{{ settingsStore.version.version }}</span></h1>
        <div class="header-actions">
          <el-button type="primary" @click="showSettings = true">
            <el-icon><Setting /></el-icon>
          </el-button>
          <div class="language-selector">
            <el-select v-model="currentLanguage" @change="changeLanguage" placeholder="Select language">
              <el-option v-for="lang in availableLanguages" :key="lang.code" :label="lang.name" :value="lang.code" />
            </el-select>
          </div>
        </div>
      </div>
    </header>
    
    <!-- Settings Panel -->
    <SettingsPanel v-model:visible="showSettings" @settings-saved="handleSettingsSaved" />
    
    <main class="app-main">
      <el-container>
        <el-aside width="160px" class="app-sidebar">
          <el-menu
            :default-active="activeMenu"
            class="sidebar-menu"
            router
            @select="handleMenuSelect"
          >
            <el-menu-item index="/script">
              <el-icon><Document /></el-icon>
              <span>{{ t('Script Settings') }}</span>
            </el-menu-item>
            <el-menu-item index="/video">
              <el-icon><VideoCamera /></el-icon>
              <span>{{ t('Video Settings') }}</span>
            </el-menu-item>
            <el-menu-item index="/audio">
              <el-icon><Microphone /></el-icon>
              <span>{{ t('Audio Settings') }}</span>
            </el-menu-item>
            <el-menu-item index="/subtitle">
              <el-icon><ChatLineSquare /></el-icon>
              <span>{{ t('Subtitle Settings') }}</span>
            </el-menu-item>
            <el-menu-item index="/scene">
              <el-icon><Collection /></el-icon>
              <span>{{ t('Scene Integration') }}</span>
            </el-menu-item>
            <el-menu-item index="/task">
              <el-icon><Timer /></el-icon>
              <span>{{ t('Task Management') }}</span>
            </el-menu-item>
            <el-menu-item index="/logs">
              <el-icon><Document /></el-icon>
              <span>{{ t('Running Logs') }}</span>
            </el-menu-item>
          </el-menu>
        </el-aside>
        
        <el-main class="app-content">
          <router-view v-slot="{ Component }">
            <transition name="fade" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
          
          <div class="app-actions" v-if="$route.path !== '/task' && $route.path !== '/logs' && $route.path !== '/scene'">
            <el-button type="danger" size="large" @click="generateVideo" :loading="isGenerating">
              <el-icon><VideoPlay /></el-icon>
              {{ isGenerating ? t('Generating Video') : t('Generate Video') }}
            </el-button>
          </div>
        </el-main>
      </el-container>
    </main>
    
    <footer class="app-footer">
      <p>{{ t('MoneyPrinterCN') }} © {{ new Date().getFullYear() }}</p>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { VideoCamera, Document, Microphone, ChatLineSquare, Collection, Timer, VideoPlay, Setting } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import { useI18nStore } from './stores/i18n';
import { useTasksStore } from './stores/tasks';
import { useSettingsStore } from './stores/settings';
import { useScriptStore } from './stores/script';
import SettingsPanel from './views/SettingsPanel.vue';

const route = useRoute();
const router = useRouter();
const i18nStore = useI18nStore();
const tasksStore = useTasksStore();
const settingsStore = useSettingsStore();

const showSettings = ref(false);
const isGenerating = ref(false);
const activeMenu = computed(() => route.path);
const currentLanguage = computed({
  get: () => i18nStore.currentLanguage,
  set: (value) => i18nStore.setLanguage(value as any)
});
const availableLanguages = computed(() => i18nStore.availableLanguages);
const t = i18nStore.t;

const changeLanguage = (lang: string) => {
  i18nStore.setLanguage(lang as any);
};

const handleMenuSelect = (key: string) => {
  router.push(key);
};

const handleSettingsSaved = () => {
  console.log('Settings saved successfully');
};

const generateVideo = async () => {
  if (isGenerating.value) {
    return;
  }

  isGenerating.value = true;

  try {
    // 直接使用store获取数据
    const scriptStore = useScriptStore();
    
    // 检查必要的参数（参照streamlit逻辑）
    const videoSubject = scriptStore.videoSubject || '';
    const videoScript = scriptStore.videoScript || '';
    const scenes = scriptStore.scenes || [];
    const hasScenes = scenes.length > 0;
    const hasScript = videoScript.trim();
    const hasSubject = videoSubject.trim();
    
    if (!hasScenes && !hasScript && !hasSubject) {
      ElMessage.warning(t('Please provide at least one of video subject, video script, or scene information'));
      return;
    }

    const aspectMap: Record<string, string> = {
      'landscape': '16:9',
      'portrait': '9:16',
      'square': '1:1',
      'portrait_3_4': '3:4'
    };

    const transitionMap: Record<string, string | null> = {
      'none': null,
      'shuffle': 'Shuffle',
      'fade_in': 'FadeIn',
      'fade_out': 'FadeOut',
      'slide_in': 'SlideIn',
      'slide_out': 'SlideOut'
    };

    // 使用默认值，因为没有其他store
    const taskParams = {
      video_subject: videoSubject,
      video_script: videoScript,
      video_terms: '',
      video_source: 'pexels',
      video_concat_mode: 'sequential',
      video_transition_mode: null,
      video_aspect: '9:16',
      video_clip_duration: 3,
      video_count: 1,
      video_style: '',
      voice_provider: 'azure',
      voice_type: 'female',
      voice_name: 'zh-CN-XiaoxiaoNeural',
      bgm: '',
      bgm_volume: 30,
      voice_volume: 80,
      subtitle_language: 'zh',
      subtitle_position: 'bottom',
      subtitle_font: 'Microsoft YaHei',
      subtitle_font_size: 24,
      subtitle_color: '#ffffff',
      subtitle_background: 'rgba(0, 0, 0, 0.5)',
      subtitle_bold: false,
      subtitle_italic: false,
      scenes: scenes,
      language: scriptStore.language || 'zh'
    };

    const task = await tasksStore.createTask(taskParams, 'video');
    if (task) {
      ElMessage.success(t('Start Generating Video'));
      router.push('/task');
    } else {
      ElMessage.error(t('Video Generation Failed'));
    }
  } catch (error) {
    console.error('Error generating video:', error);
    ElMessage.error(t('Video Generation Failed'));
  } finally {
    isGenerating.value = false;
  }
};

onMounted(async () => {
  await i18nStore.loadTranslations();
  i18nStore.loadLanguageFromLocalStorage();
  await settingsStore.fetchVersion();
});
</script>

<style scoped>
.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  background-color: #1890ff;
  color: white;
  padding: 0 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 64px;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}

.header-content h1 {
  margin: 0;
  font-size: 1.5rem;
  display: flex;
  align-items: center;
  gap: 10px;
}

.version {
  font-size: 0.8rem;
  font-weight: normal;
  color: rgba(255, 255, 255, 0.8);
  background-color: rgba(255, 255, 255, 0.2);
  padding: 2px 8px;
  border-radius: 4px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 15px;
}

.language-selector {
  min-width: 150px;
}

.app-main {
  flex: 1;
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
  padding: 20px;
}

.app-sidebar {
  background-color: #f5f5f5;
  border-right: 1px solid #e8e8e8;
}

.sidebar-menu {
  height: 100%;
}

.app-content {
  padding: 0 20px;
}

.app-actions {
  margin-top: 30px;
  text-align: center;
}

.app-footer {
  background-color: #f5f5f5;
  border-top: 1px solid #e8e8e8;
  padding: 20px;
  text-align: center;
  margin-top: auto;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 768px) {
  .app-main {
    flex-direction: column;
  }
  
  .app-sidebar {
    width: 100% !important;
    height: auto;
  }
  
  .sidebar-menu {
    display: flex;
    overflow-x: auto;
  }
  
  .el-menu-item {
    white-space: nowrap;
  }
}
</style>