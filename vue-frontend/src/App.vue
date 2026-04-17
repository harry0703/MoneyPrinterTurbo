<template>
  <div class="app">
    <header class="app-header">
      <div class="header-content">
        <h1>{{ t('MoneyPrinterCN') }} <span v-if="settingsStore.version" class="version">{{ settingsStore.version.version }}</span></h1>
        <div class="header-actions">
          <el-button type="primary" @click="showSettings = true">
            <el-icon><Setting /></el-icon>
            {{ t('Settings') }}
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
        <el-aside width="200px" class="app-sidebar">
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
          
          <div class="app-actions" v-if="$route.path !== '/task'">
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
    const videoSettings = (window as any).__VUE_APP_VIDEO_SETTINGS__;
    const scriptSettings = (window as any).__VUE_APP_SCRIPT_SETTINGS__;
    const audioSettings = (window as any).__VUE_APP_AUDIO_SETTINGS__;
    const subtitleSettings = (window as any).__VUE_APP_SUBTITLE_SETTINGS__;
    const sceneIntegration = (window as any).__VUE_APP_SCENE_INTEGRATION__;

    let isValid = true;
    if (videoSettings && videoSettings.validate) {
      isValid = isValid && await videoSettings.validate();
    }
    if (scriptSettings && scriptSettings.validate) {
      isValid = isValid && await scriptSettings.validate();
    }
    if (audioSettings && audioSettings.validate) {
      isValid = isValid && await audioSettings.validate();
    }
    if (subtitleSettings && subtitleSettings.validate) {
      isValid = isValid && await subtitleSettings.validate();
    }

    if (!isValid) {
      ElMessage.warning(t('Video Script and Subject Cannot Both Be Empty'));
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

    const taskParams = {
      video_subject: scriptSettings?.form.videoSubject || '',
      video_script: scriptSettings?.form.videoScript || '',
      video_terms: scriptSettings?.form.videoTerms || '',
      video_source: videoSettings?.form.videoSource || 'pexels',
      video_concat_mode: videoSettings?.form.videoConcatMode || 'random',
      video_transition_mode: transitionMap[videoSettings?.form.videoTransitionMode] ?? null,
      video_aspect: aspectMap[videoSettings?.form.videoAspect] || '9:16',
      video_clip_duration: videoSettings?.form.videoClipDuration || 3,
      video_count: videoSettings?.form.videoCount || 1,
      video_style: videoSettings?.form.videoStyle || '',
      voice_provider: audioSettings?.form.voiceProvider || 'azure',
      voice_type: audioSettings?.form.voiceType || 'female',
      voice_name: audioSettings?.form.voiceName || 'zh-CN-XiaoxiaoNeural',
      bgm: audioSettings?.form.bgm || '',
      bgm_volume: audioSettings?.form.bgmVolume || 30,
      voice_volume: audioSettings?.form.voiceVolume || 80,
      subtitle_language: subtitleSettings?.form.subtitleLanguage || 'zh',
      subtitle_position: subtitleSettings?.form.subtitlePosition || 'bottom',
      subtitle_font: subtitleSettings?.form.subtitleFont || 'Microsoft YaHei',
      subtitle_font_size: subtitleSettings?.form.subtitleFontSize || 24,
      subtitle_color: subtitleSettings?.form.subtitleColor || '#ffffff',
      subtitle_background: subtitleSettings?.form.subtitleBackground || 'rgba(0, 0, 0, 0.5)',
      subtitle_bold: subtitleSettings?.form.subtitleBold || false,
      subtitle_italic: subtitleSettings?.form.subtitleItalic || false,
      scenes: sceneIntegration?.scenes || [],
      language: scriptSettings?.form.language || 'zh'
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