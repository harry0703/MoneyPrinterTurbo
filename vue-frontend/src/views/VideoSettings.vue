<template>
  <div class="video-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">🎬 {{ t('Video Settings') }}</h2>
        </div>
      </template>
      
      <div class="settings-form">
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Video Source'))"></label>
          <el-select v-model="form.videoSource" :placeholder="t('Select video source')" class="form-select">
            <el-option :label="t('Pexels')" value="pexels" />
            <el-option :label="t('Pixabay')" value="pixabay" />
            <el-option :label="t('Local file')" value="local" />
            <el-option :label="t('TikTok')" value="douyin" />
            <el-option :label="t('Bilibili')" value="bilibili" />
            <el-option :label="t('Xiaohongshu')" value="xiaohongshu" />
          </el-select>
        </div>
        
        <div v-if="form.videoSource === 'local'" class="local-files-section">
          <div class="form-item">
            <label class="form-label" v-html="parseLabelMarkdown(t('Local Files'))"></label>
            <FileUploader
              :multiple="true"
              :accept="'video/*,image/*'"
              :auto-upload="false"
              :upload-text="t('Upload Local Files')"
              v-model="localFiles"
              @remove="handleFileRemove"
            />
            <div v-if="localFiles.length > 0" class="uploaded-files-info">
              <el-alert
                :title="t('Uploaded Files')"
                type="info"
                :closable="false"
                show-icon
                class="mt-2"
              >
                <p>{{ t('Successfully uploaded ' + localFiles.length + ' files') }}</p>
                <div v-for="file in localFiles" :key="file.uid" class="file-item">
                  📄 {{ file.name }}
                </div>
              </el-alert>
            </div>
          </div>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Video Concat Mode'))"></label>
          <el-select v-model="form.videoConcatMode" :placeholder="t('Select concat mode')" class="form-select">
            <el-option :label="t('Sequential')" value="sequential" />
            <el-option :label="t('Random')" value="random" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Video Transition Mode'))"></label>
          <el-select v-model="form.videoTransitionMode" :placeholder="t('Select transition mode')" class="form-select">
            <el-option :label="t('None')" value="none" />
            <el-option :label="t('Shuffle')" value="shuffle" />
            <el-option :label="t('FadeIn')" value="fade_in" />
            <el-option :label="t('FadeOut')" value="fade_out" />
            <el-option :label="t('SlideIn')" value="slide_in" />
            <el-option :label="t('SlideOut')" value="slide_out" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Video Ratio'))"></label>
          <el-select v-model="form.videoAspect" :placeholder="t('Select video ratio')" class="form-select">
            <el-option :label="t('Landscape')" value="landscape" />
            <el-option :label="t('Portrait')" value="portrait" />
            <el-option :label="t('Square')" value="square" />
            <el-option :label="t('3:4 Portrait')" value="portrait_3_4" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Clip Duration'))"></label>
          <el-select v-model="form.videoClipDuration" :placeholder="t('Select clip duration')" class="form-select">
            <el-option v-for="duration in [2, 3, 4, 5, 6, 7, 8, 9, 10]" :key="duration" :label="duration" :value="duration" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Number of Videos Generated Simultaneously'))"></label>
          <el-select v-model="form.videoCount" :placeholder="t('Select number of videos')" class="form-select">
            <el-option v-for="count in [1, 2, 3, 4, 5]" :key="count" :label="count" :value="count" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Video Style'))"></label>
          <el-select v-model="form.videoStyle" :placeholder="t('Select video style')" class="form-select">
            <el-option :label="t('Video Style None')" value="none" />
            <el-option :label="t('People/Human')" value="people" />
            <el-option :label="t('Nature/Landscape')" value="nature" />
            <el-option :label="t('Animation')" value="animation" />
            <el-option :label="t('Cartoon')" value="cartoon" />
          </el-select>
        </div>

        <div class="form-item">
          <label class="form-label">{{ t('Video Brightness') }}</label>
          <div class="slider-control">
            <el-slider
              v-model="form.videoBrightness"
              :min="0.5"
              :max="2.0"
              :step="0.05"
              :show-input="true"
              :input-size="'small'"
            />
            <span class="slider-value">{{ form.videoBrightness.toFixed(2) }}</span>
          </div>
        </div>

        <div class="form-item">
          <label class="form-label">{{ t('Video Contrast') }}</label>
          <div class="slider-control">
            <el-slider
              v-model="form.videoContrast"
              :min="0.5"
              :max="2.0"
              :step="0.05"
              :show-input="true"
              :input-size="'small'"
            />
            <span class="slider-value">{{ form.videoContrast.toFixed(2) }}</span>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, onMounted } from 'vue';
import FileUploader from '../components/FileUploader.vue';
import { useI18nStore } from '../stores/i18n';
import { parseLabelMarkdown } from '../utils/markdownParser';
import { useSettingsStore } from '../stores/settings';
import { apiService } from '../services/api';

interface FileItem {
  name: string;
  url?: string;
  status?: string;
  uid: string;
}

const i18nStore = useI18nStore();
const t = i18nStore.t;
const settingsStore = useSettingsStore();

const localFiles = ref<FileItem[]>([]);

const form = reactive({
  videoSource: settingsStore.video.source,
  videoConcatMode: settingsStore.video.concatMode,
  videoTransitionMode: settingsStore.video.transitionMode,
  videoAspect: settingsStore.video.aspect,
  videoClipDuration: settingsStore.video.clipDuration,
  videoCount: settingsStore.video.count,
  videoStyle: settingsStore.video.style,
  videoQuality: settingsStore.video.quality,
  videoBitrate: settingsStore.video.bitrate,
  videoBrightness: settingsStore.video.brightness,
  videoContrast: settingsStore.video.contrast
});

const handleFileRemove = (file: FileItem) => {
  const index = localFiles.value.findIndex(item => item.uid === file.uid);
  if (index !== -1) {
    localFiles.value.splice(index, 1);
  }
};

const setVideoQualityBasedOnGPU = () => {
  if (settingsStore.app.useGpu) {
    form.videoQuality = 'ultra';
    form.videoBitrate = '20M';
  } else {
    form.videoQuality = 'high';
    form.videoBitrate = '10M';
  }
};

const loadConfig = async () => {
  try {
    const response = await apiService.getConfig();
    if (response.status === 200 && response.data) {
      const cfg = response.data;
      if (cfg.app) {
        if (cfg.app.video_source) {
          form.videoSource = cfg.app.video_source;
        }
        if (typeof cfg.app.use_gpu === 'boolean') {
          settingsStore.app.useGpu = cfg.app.use_gpu;
        }
        setVideoQualityBasedOnGPU();
        if (cfg.app.video_brightness !== undefined) {
          form.videoBrightness = Number(cfg.app.video_brightness);
        }
        if (cfg.app.video_contrast !== undefined) {
          form.videoContrast = Number(cfg.app.video_contrast);
        }
        if (cfg.app.video_concat_mode) {
          form.videoConcatMode = cfg.app.video_concat_mode;
        }
        if (cfg.app.video_transition_mode) {
          form.videoTransitionMode = cfg.app.video_transition_mode;
        }
        if (cfg.app.video_aspect) {
          form.videoAspect = cfg.app.video_aspect;
        }
        if (cfg.app.video_clip_duration !== undefined) {
          form.videoClipDuration = Number(cfg.app.video_clip_duration);
        }
        if (cfg.app.video_count !== undefined) {
          form.videoCount = Number(cfg.app.video_count);
        }
        if (cfg.app.video_style) {
          form.videoStyle = cfg.app.video_style;
        }
      }
    }
  } catch (error: any) {
    console.error('Failed to load config:', error);
  }
};

const saveConfig = async () => {
  try {
    const cfg = {
      app: {
        video_source: form.videoSource,
        video_quality: form.videoQuality,
        video_bitrate: form.videoBitrate,
        video_brightness: form.videoBrightness,
        video_contrast: form.videoContrast,
        video_concat_mode: form.videoConcatMode,
        video_transition_mode: form.videoTransitionMode,
        video_aspect: form.videoAspect,
        video_clip_duration: form.videoClipDuration,
        video_count: form.videoCount,
        video_style: form.videoStyle
      }
    };
    await apiService.updateConfig(cfg);
    console.log('[VideoSettings] Config saved:', cfg);
  } catch (error: any) {
    console.error('Failed to save config:', error);
  }
};

watch([
  () => form.videoSource,
  () => form.videoConcatMode,
  () => form.videoTransitionMode,
  () => form.videoAspect,
  () => form.videoClipDuration,
  () => form.videoCount,
  () => form.videoStyle,
  () => form.videoQuality,
  () => form.videoBitrate,
  () => form.videoBrightness,
  () => form.videoContrast
], () => {
  saveConfig();
  settingsStore.updateVideoSetting('source', form.videoSource);
  settingsStore.updateVideoSetting('concatMode', form.videoConcatMode);
  settingsStore.updateVideoSetting('transitionMode', form.videoTransitionMode);
  settingsStore.updateVideoSetting('aspect', form.videoAspect);
  settingsStore.updateVideoSetting('clipDuration', form.videoClipDuration);
  settingsStore.updateVideoSetting('count', form.videoCount);
  settingsStore.updateVideoSetting('style', form.videoStyle);
  settingsStore.updateVideoSetting('quality', form.videoQuality);
  settingsStore.updateVideoSetting('bitrate', form.videoBitrate);
  settingsStore.updateVideoSetting('brightness', form.videoBrightness);
  settingsStore.updateVideoSetting('contrast', form.videoContrast);
});

watch(() => settingsStore.video, (newVideo) => {
  console.log('[VideoSettings] Store video changed, updating form:', newVideo);
  form.videoSource = newVideo.source;
  form.videoConcatMode = newVideo.concatMode;
  form.videoTransitionMode = newVideo.transitionMode;
  form.videoAspect = newVideo.aspect;
  form.videoClipDuration = newVideo.clipDuration;
  form.videoCount = newVideo.count;
  form.videoStyle = newVideo.style;
  form.videoQuality = newVideo.quality;
  form.videoBitrate = newVideo.bitrate;
  form.videoBrightness = newVideo.brightness;
  form.videoContrast = newVideo.contrast;
}, { deep: true });

watch(() => settingsStore.app.useGpu, () => {
  console.log('[VideoSettings] useGpu changed, updating video quality/bitrate');
  setVideoQualityBasedOnGPU();
});

onMounted(async () => {
  await loadConfig();
});

defineExpose({
  form,
  localFiles
});
</script>

<style scoped>
.video-settings {
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
  gap: 0px;
}

.form-label {
  font-weight: normal;
  font-size: 14px;
  color: #333;
  margin-bottom: 4px;
  line-height: 1.4;
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

.local-files-section {
  margin-top: 16px;
  padding: 16px;
  background-color: #f9f9f9;
  border-radius: 4px;
}

.uploaded-files-info {
  margin-top: 12px;
}

.file-item {
  margin-top: 6px;
  font-size: 14px;
}

.slider-control {
  display: flex;
  align-items: center;
  gap: 10px;
}

.slider-value {
  min-width: 60px;
  text-align: right;
  font-size: 14px;
  color: #666;
}

.mt-2 {
  margin-top: 8px;
}
</style>