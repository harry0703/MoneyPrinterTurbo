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
            <el-option :label="t('Industry')" value="industry" />
            <el-option :label="t('Science')" value="science" />
            <el-option :label="t('Tech')" value="tech" />
            <el-option :label="t('Business')" value="business" />
            <el-option :label="t('AI')" value="ai" />
          </el-select>
        </div>
        
        <div class="form-group intro-video-background-group">
          <div class="form-item">
            <label class="form-label" v-html="parseLabelMarkdown(t('Intro Video Background Type'))"></label>
            <el-select v-model="form.introVideoBgType" :placeholder="t('Select intro video background type')" class="form-select">
              <el-option :label="t('Solid Color')" value="solid" />
              <el-option :label="t('Blurred')" value="blurred" />
            </el-select>
          </div>
          
          <div v-if="form.introVideoBgType === 'blurred'" class="form-item">
            <label class="form-label">{{ t('Intro Video Blur Intensity') }}</label>
            <div class="slider-control">
              <el-slider
                v-model="form.introVideoBgBlur"
                :min="1"
                :max="50"
                :step="1"
                :show-input="true"
                :input-size="'small'"
              />
              <span class="slider-value">{{ form.introVideoBgBlur }}</span>
            </div>
          </div>
          
          <div v-if="form.introVideoBgType === 'solid'" class="form-item">
            <label class="form-label">{{ t('Intro Video Background Color') }}</label>
            <div class="color-select-wrapper">
              <div class="color-preview" :style="{ backgroundColor: getColorValue(form.introVideoBgColor) }">
                <span v-if="isLightColor(form.introVideoBgColor)" class="preview-label">{{ getColorName(form.introVideoBgColor) }}</span>
                <span v-else class="preview-label light-text">{{ getColorName(form.introVideoBgColor) }}</span>
              </div>
              <div class="color-options">
                <button
                  v-for="color in colorOptions"
                  :key="color.value"
                  class="color-option"
                  :class="{ active: form.introVideoBgColor === color.value }"
                  :style="{ backgroundColor: color.hex }"
                  :title="t(color.label)"
                  @click="form.introVideoBgColor = color.value"
                >
                  <span v-if="form.introVideoBgColor === color.value" class="check-icon">✓</span>
                </button>
              </div>
              <div class="custom-color-picker">
                <el-color-picker
                  v-model="introVideoCustomColor"
                  show-alpha
                  class="color-picker"
                  @change="handleIntroVideoCustomColorChange"
                />
                <span class="custom-color-label">{{ t('Custom Color') }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="form-item">
          <label class="form-label">{{ t('Silence Prefix') }} (s)</label>
          <div class="slider-control">
            <el-slider
              v-model="form.silenceDuration"
              :min="0.0"
              :max="5.0"
              :step="0.1"
              :show-input="true"
              :input-size="'small'"
            />
            <span class="slider-value">{{ form.silenceDuration.toFixed(1) }}s</span>
          </div>
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

        <div class="form-item">
          <label class="form-label">{{ t('Output Background Color') }}</label>
          <div class="color-select-wrapper">
            <div class="color-preview" :style="{ backgroundColor: getColorValue(form.outputBgColor) }">
              <span v-if="isLightColor(form.outputBgColor)" class="preview-label">{{ getColorName(form.outputBgColor) }}</span>
              <span v-else class="preview-label light-text">{{ getColorName(form.outputBgColor) }}</span>
            </div>
            <div class="color-options">
              <button
                v-for="color in colorOptions"
                :key="color.value"
                class="color-option"
                :class="{ active: form.outputBgColor === color.value }"
                :style="{ backgroundColor: color.hex }"
                :title="t(color.label)"
                @click="form.outputBgColor = color.value"
              >
                <span v-if="form.outputBgColor === color.value" class="check-icon">✓</span>
              </button>
            </div>
            <div class="custom-color-picker">
              <el-color-picker
                v-model="customColor"
                show-alpha
                class="color-picker"
                @change="handleCustomColorChange"
              />
              <span class="custom-color-label">{{ t('Custom Color') }}</span>
            </div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch, onMounted, computed, ref } from 'vue';
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

const localFiles = computed({
  get: () => settingsStore.video.localFiles,
  set: (value) => {
    settingsStore.video.localFiles = value;
    settingsStore.saveToLocalStorage();
  }
});

const form = reactive({
  videoSource: settingsStore.video.source,
  videoConcatMode: settingsStore.video.concatMode,
  videoTransitionMode: settingsStore.video.transitionMode,
  videoAspect: settingsStore.video.aspect,
  videoClipDuration: settingsStore.video.clipDuration,
  videoCount: settingsStore.video.count,
  silenceDuration: settingsStore.video.silenceDuration,
  videoStyle: settingsStore.video.style,
  videoQuality: settingsStore.video.quality,
  videoBitrate: settingsStore.video.bitrate,
  videoBrightness: settingsStore.video.brightness,
  videoContrast: settingsStore.video.contrast,
  outputBgColor: settingsStore.video.outputBgColor,
  introVideoBgType: settingsStore.video.introVideoBgType,
  introVideoBgBlur: settingsStore.video.introVideoBgBlur,
  introVideoBgColor: settingsStore.video.introVideoBgColor
});

const customColor = ref('#000000');
const introVideoCustomColor = ref('#000000');

const colorOptions = [
  { value: 'black', label: 'Black', hex: '#000000' },
  { value: 'white', label: 'White', hex: '#FFFFFF' },
  { value: 'red', label: 'Red', hex: '#FF0000' },
  { value: 'green', label: 'Green', hex: '#00FF00' },
  { value: 'blue', label: 'Blue', hex: '#0000FF' },
  { value: 'yellow', label: 'Yellow', hex: '#FFFF00' },
  { value: 'purple', label: 'Purple', hex: '#800080' },
  { value: 'gray', label: 'Gray', hex: '#808080' },
  { value: 'darkgray', label: 'Dark Gray', hex: '#404040' },
  { value: 'lightgray', label: 'Light Gray', hex: '#D3D3D3' },
  { value: 'orange', label: 'Orange', hex: '#FFA500' },
  { value: 'pink', label: 'Pink', hex: '#FFC0CB' },
  { value: 'cyan', label: 'Cyan', hex: '#00FFFF' },
  { value: 'brown', label: 'Brown', hex: '#A52A2A' },
  { value: 'gold', label: 'Gold', hex: '#FFD700' },
  { value: 'silver', label: 'Silver', hex: '#C0C0C0' },
];

const getColorValue = (colorValue: string): string => {
  const color = colorOptions.find(c => c.value === colorValue);
  if (color) {
    return color.hex;
  }
  if (colorValue.startsWith('#')) {
    return colorValue;
  }
  return '#000000';
};

const getColorName = (colorValue: string): string => {
  const color = colorOptions.find(c => c.value === colorValue);
  if (color) {
    return t(color.label);
  }
  return colorValue;
};

const isLightColor = (colorValue: string): boolean => {
  const hex = getColorValue(colorValue);
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.5;
};

const handleCustomColorChange = (color: string) => {
  form.outputBgColor = color;
};

const handleIntroVideoCustomColorChange = (color: string) => {
  form.introVideoBgColor = color;
};

const handleFileRemove = (file: FileItem) => {
  const index = localFiles.value.findIndex(item => item.uid === file.uid);
  if (index !== -1) {
    localFiles.value.splice(index, 1);
  }
};

let uploadInProgress = false;
let pendingUploads: FileItem[] = [];

const uploadPendingFiles = async () => {
  if (uploadInProgress || pendingUploads.length === 0) return;
  uploadInProgress = true;

  const toUpload = [...pendingUploads];
  pendingUploads = [];

  for (const fileItem of toUpload) {
    const index = localFiles.value.findIndex(item => item.uid === fileItem.uid);
    if (index === -1) continue;

    try {
      const rawFile = (fileItem as any).raw;
      console.log('[VideoSettings] uploadPendingFiles - fileItem:', fileItem.name, 'rawFile:', !!rawFile);
      
      if (!rawFile) {
        console.warn('[VideoSettings] No raw file for:', fileItem.name, ', fileItem:', fileItem);
        continue;
      }

      console.log('[VideoSettings] Uploading file:', rawFile.name);
      const response = await apiService.uploadVideoMaterial(rawFile);
      console.log('[VideoSettings] Upload response:', response);
      
      if (response.status === 200 && response.data && response.data.file) {
        const currentIndex = localFiles.value.findIndex(item => item.uid === fileItem.uid);
        if (currentIndex !== -1) {
          localFiles.value[currentIndex] = {
            ...localFiles.value[currentIndex],
            url: response.data.file,
            status: 'completed'
          };
          console.log('[VideoSettings] Updated localFiles:', localFiles.value[currentIndex]);
        }
      }
    } catch (error) {
      console.error('[VideoSettings] Failed to upload local file:', fileItem.name, error);
    }
  }

  uploadInProgress = false;
  if (pendingUploads.length > 0) {
    uploadPendingFiles();
  }
};

watch(() => localFiles.value.length, (newLen, oldLen) => {
  console.log('[VideoSettings] localFiles length changed:', oldLen, '->', newLen);
  if (newLen > oldLen) {
    const newItems = localFiles.value.slice(oldLen);
    console.log('[VideoSettings] New items added:', newItems);
    for (const item of newItems) {
      console.log('[VideoSettings] Item:', item.name, 'url:', item.url, 'has raw:', !!(item as any).raw);
      if (!item.url || item.url.startsWith('blob:')) {
        pendingUploads.push(item);
        console.log('[VideoSettings] Added to pending uploads:', item.name);
      }
    }
    console.log('[VideoSettings] pendingUploads count:', pendingUploads.length);
    uploadPendingFiles();
  }
});

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
        if (cfg.app.silence_duration !== undefined) {
          form.silenceDuration = Number(cfg.app.silence_duration);
        }
        if (cfg.app.video_style) {
          form.videoStyle = cfg.app.video_style;
        }
        if (cfg.app.intro_video_bg_type) {
          form.introVideoBgType = cfg.app.intro_video_bg_type;
        }
        if (cfg.app.intro_video_bg_blur !== undefined) {
          form.introVideoBgBlur = Number(cfg.app.intro_video_bg_blur);
        }
        if (cfg.app.intro_video_bg_color) {
          form.introVideoBgColor = cfg.app.intro_video_bg_color;
        }
      }
      if (cfg.ui && cfg.ui.output_bg_color) {
        form.outputBgColor = cfg.ui.output_bg_color;
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
        silence_duration: form.silenceDuration,
        video_style: form.videoStyle,
        intro_video_bg_type: form.introVideoBgType,
        intro_video_bg_blur: form.introVideoBgBlur,
        intro_video_bg_color: form.introVideoBgColor
      },
      ui: {
        output_bg_color: form.outputBgColor
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
  () => form.silenceDuration,
  () => form.videoStyle,
  () => form.videoQuality,
  () => form.videoBitrate,
  () => form.videoBrightness,
  () => form.videoContrast,
  () => form.outputBgColor,
  () => form.introVideoBgType,
  () => form.introVideoBgBlur,
  () => form.introVideoBgColor
], () => {
  saveConfig();
  settingsStore.updateVideoSetting('source', form.videoSource);
  settingsStore.updateVideoSetting('concatMode', form.videoConcatMode);
  settingsStore.updateVideoSetting('transitionMode', form.videoTransitionMode);
  settingsStore.updateVideoSetting('aspect', form.videoAspect);
  settingsStore.updateVideoSetting('clipDuration', form.videoClipDuration);
  settingsStore.updateVideoSetting('count', form.videoCount);
  settingsStore.updateVideoSetting('silenceDuration', form.silenceDuration);
  settingsStore.updateVideoSetting('style', form.videoStyle);
  settingsStore.updateVideoSetting('quality', form.videoQuality);
  settingsStore.updateVideoSetting('bitrate', form.videoBitrate);
  settingsStore.updateVideoSetting('brightness', form.videoBrightness);
  settingsStore.updateVideoSetting('contrast', form.videoContrast);
  settingsStore.updateVideoSetting('outputBgColor', form.outputBgColor);
  settingsStore.updateVideoSetting('introVideoBgType', form.introVideoBgType);
  settingsStore.updateVideoSetting('introVideoBgBlur', form.introVideoBgBlur);
  settingsStore.updateVideoSetting('introVideoBgColor', form.introVideoBgColor);
});

watch(() => settingsStore.video, (newVideo) => {
  console.log('[VideoSettings] Store video changed, updating form:', newVideo);
  form.videoSource = newVideo.source;
  form.videoConcatMode = newVideo.concatMode;
  form.videoTransitionMode = newVideo.transitionMode;
  form.videoAspect = newVideo.aspect;
  form.videoClipDuration = newVideo.clipDuration;
  form.videoCount = newVideo.count;
  form.silenceDuration = newVideo.silenceDuration;
  form.videoStyle = newVideo.style;
  form.videoQuality = newVideo.quality;
  form.videoBitrate = newVideo.bitrate;
  form.videoBrightness = newVideo.brightness;
  form.videoContrast = newVideo.contrast;
  form.outputBgColor = newVideo.outputBgColor;
  form.introVideoBgType = newVideo.introVideoBgType;
  form.introVideoBgBlur = newVideo.introVideoBgBlur;
  form.introVideoBgColor = newVideo.introVideoBgColor;
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

.color-select-wrapper {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 4px;
}

.color-preview {
  width: 100%;
  height: 48px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid #e4e7ed;
  transition: all 0.3s ease;
  cursor: pointer;
}

.color-preview:hover {
  border-color: #409eff;
  box-shadow: 0 0 8px rgba(64, 158, 255, 0.3);
}

.preview-label {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}

.preview-label.light-text {
  color: #ffffff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
}

.color-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.color-option {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  border: 2px solid transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  position: relative;
}

.color-option:hover {
  transform: scale(1.1);
  border-color: #909399;
}

.color-option.active {
  border-color: #409eff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.2);
}

.check-icon {
  color: white;
  font-size: 16px;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
  font-weight: bold;
}

.custom-color-picker {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px dashed #e4e7ed;
}

.color-picker {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  cursor: pointer;
}

.custom-color-label {
  font-size: 13px;
  color: #909399;
}

.color-picker :deep(.el-color-picker__trigger) {
  width: 100%;
  height: 100%;
  border-radius: 8px;
  padding: 0;
}

.color-picker :deep(.el-color-picker__icon) {
  display: none;
}

.form-group {
  padding: 16px;
  background-color: #f9f9f9;
  border-radius: 8px;
  margin-bottom: 0;
}

.intro-video-background-group {
  border: 1px solid #e4e7ed;
}

.intro-video-background-group .form-item {
  margin-bottom: 16px;
}

.intro-video-background-group .form-item:last-child {
  margin-bottom: 0;
}
</style>