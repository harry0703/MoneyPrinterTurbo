<template>
  <div class="title-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">📝 {{ t('Title Settings') }}</h2>
        </div>
      </template>
      
      <div class="settings-form">
        <div class="form-item">
          <label class="form-label">
            <el-checkbox v-model="form.titleEnabled" />
            {{ t('Enable Title') }}
          </label>
        </div>
        
        <div v-if="form.titleEnabled" class="title-content">
          <div class="form-item">
            <label class="form-label">{{ t('Duration') }} ({{ t('seconds') }})</label>
            <div class="slider-control">
              <el-slider
                v-model="form.titleDuration"
                :min="1"
                :max="10"
                :step="0.5"
                :show-input="true"
                :input-size="'small'"
              />
              <span class="slider-value">{{ form.titleDuration.toFixed(1) }}s</span>
            </div>
          </div>
          
          <div class="form-item">
            <label class="form-label">{{ t('Style Preset') }}</label>
            <el-select v-model="form.titleStyle" :placeholder="t('Select style')" class="form-select" @change="applyStyle">
              <el-option :label="t('Custom')" value="" />
              <el-option 
                v-for="(style, key) in titleStyles" 
                :key="key" 
                :label="style.name" 
                :value="key"
              />
            </el-select>
          </div>
          
          <div class="form-item">
            <label class="form-label">{{ t('Font') }}</label>
            <el-select v-model="form.titleFont" :placeholder="t('Select font')" class="form-select">
              <el-option 
                v-for="font in availableFonts" 
                :key="font" 
                :label="font" 
                :value="font"
              />
            </el-select>
          </div>
          
          <div class="form-item">
            <label class="form-label">{{ t('Font Size') }}</label>
            <div class="slider-control">
              <el-slider
                v-model="form.titleFontSize"
                :min="20"
                :max="120"
                :step="2"
                :show-input="true"
                :input-size="'small'"
              />
              <span class="slider-value">{{ form.titleFontSize }}px</span>
            </div>
          </div>
          
          <div class="form-item">
            <label class="form-label">{{ t('Text Color') }}</label>
            <div class="color-select-wrapper">
              <div class="color-preview" :style="{ backgroundColor: form.titleColor }">
                <span v-if="isLightColor(form.titleColor)" class="preview-label">{{ form.titleColor }}</span>
                <span v-else class="preview-label light-text">{{ form.titleColor }}</span>
              </div>
              <div class="color-options">
                <button
                  v-for="color in colorOptions"
                  :key="color.value"
                  class="color-option"
                  :class="{ active: form.titleColor === color.hex }"
                  :style="{ backgroundColor: color.hex }"
                  :title="t(color.label)"
                  @click="form.titleColor = color.hex"
                >
                  <span v-if="form.titleColor === color.hex" class="check-icon">✓</span>
                </button>
              </div>
              <div class="custom-color-picker">
                <el-color-picker
                  v-model="form.titleColor"
                  show-alpha
                  class="color-picker"
                />
                <span class="custom-color-label">{{ t('Custom Color') }}</span>
              </div>
            </div>
          </div>
          
          <div class="form-item">
            <label class="form-label">{{ t('Stroke Color') }}</label>
            <div class="color-select-wrapper">
              <div class="color-options">
                <button
                  class="color-option"
                  :class="{ active: form.titleStrokeColor === 'transparent' }"
                  :style="{ backgroundColor: 'transparent', border: '2px dashed #999' }"
                  :title="t('Transparent')"
                  @click="form.titleStrokeColor = 'transparent'"
                >
                  <span v-if="form.titleStrokeColor === 'transparent'" class="check-icon">✓</span>
                </button>
                <button
                  v-for="color in colorOptions"
                  :key="color.value"
                  class="color-option"
                  :class="{ active: form.titleStrokeColor === color.hex }"
                  :style="{ backgroundColor: color.hex }"
                  :title="t(color.label)"
                  @click="form.titleStrokeColor = color.hex"
                >
                  <span v-if="form.titleStrokeColor === color.hex" class="check-icon">✓</span>
                </button>
              </div>
              <div class="custom-color-picker" v-if="form.titleStrokeColor !== 'transparent'">
                <el-color-picker
                  v-model="form.titleStrokeColor"
                  show-alpha
                  class="color-picker"
                />
              </div>
            </div>
          </div>
          
          <div class="form-item">
            <label class="form-label">{{ t('Stroke Width') }}</label>
            <div class="slider-control">
              <el-slider
                v-model="form.titleStrokeWidth"
                :min="0"
                :max="10"
                :step="0.5"
                :show-input="true"
                :input-size="'small'"
              />
              <span class="slider-value">{{ form.titleStrokeWidth }}px</span>
            </div>
          </div>
          
          <div class="form-item">
            <label class="form-label">{{ t('Background Color') }}</label>
            <div class="color-select-wrapper">
              <div class="color-options">
                <button
                  class="color-option"
                  :class="{ active: form.titleBackgroundColor === 'transparent' }"
                  :style="{ backgroundColor: 'transparent', border: '2px dashed #999' }"
                  :title="t('Transparent')"
                  @click="form.titleBackgroundColor = 'transparent'"
                >
                  <span v-if="form.titleBackgroundColor === 'transparent'" class="check-icon">✓</span>
                </button>
                <button
                  v-for="color in colorOptions"
                  :key="color.value"
                  class="color-option"
                  :class="{ active: form.titleBackgroundColor === color.hex }"
                  :style="{ backgroundColor: color.hex }"
                  :title="t(color.label)"
                  @click="form.titleBackgroundColor = color.hex"
                >
                  <span v-if="form.titleBackgroundColor === color.hex" class="check-icon">✓</span>
                </button>
              </div>
              <div class="custom-color-picker" v-if="form.titleBackgroundColor !== 'transparent'">
                <el-color-picker
                  v-model="form.titleBackgroundColor"
                  show-alpha
                  class="color-picker"
                />
              </div>
            </div>
          </div>
          
          <div class="form-item">
            <label class="form-label">{{ t('Position') }}</label>
            <el-select v-model="form.titlePosition" :placeholder="t('Select position')" class="form-select">
              <el-option :label="t('Top')" value="top" />
              <el-option :label="t('Center')" value="center" />
              <el-option :label="t('Bottom')" value="bottom" />
            </el-select>
          </div>
          
          <div class="form-item">
            <label class="form-label">{{ t('Vertical Margin') }} (%)</label>
            <div class="slider-control">
              <el-slider
                v-model="form.titleMargin"
                :min="0"
                :max="20"
                :step="1"
                :show-input="true"
                :input-size="'small'"
              />
              <span class="slider-value">{{ Math.round(form.titleMargin) }}%</span>
            </div>
          </div>
          
          <div class="form-item">
            <label class="form-label">{{ t('Horizontal Margin') }} (%)</label>
            <div class="margin-row">
              <div class="margin-item">
                <span class="margin-label">{{ t('Left') }}</span>
                <el-slider
                  v-model="form.titleMarginLeft"
                  :min="0"
                  :max="20"
                  :step="1"
                  :show-input="true"
                  :input-size="'small'"
                  class="margin-slider"
                />
                <span class="margin-value">{{ Math.round(form.titleMarginLeft) }}%</span>
              </div>
              <div class="margin-item">
                <span class="margin-label">{{ t('Right') }}</span>
                <el-slider
                  v-model="form.titleMarginRight"
                  :min="0"
                  :max="20"
                  :step="1"
                  :show-input="true"
                  :input-size="'small'"
                  class="margin-slider"
                />
                <span class="margin-value">{{ Math.round(form.titleMarginRight) }}%</span>
              </div>
            </div>
          </div>
          
          <div class="form-item">
            <label class="form-label">{{ t('Animation') }}</label>
            <el-select v-model="form.titleAnimation" :placeholder="t('Select animation')" class="form-select">
              <el-option :label="t('None')" value="none" />
              <el-option :label="t('Fade In')" value="fade_in" />
              <el-option :label="t('Fade Out')" value="fade_out" />
              <el-option :label="t('Slide Up')" value="slide_up" />
              <el-option :label="t('Slide Down')" value="slide_down" />
            </el-select>
          </div>
          
          <div v-if="form.titleAnimation !== 'none'" class="form-item">
            <label class="form-label">{{ t('Animation Duration') }} ({{ t('seconds') }})</label>
            <div class="slider-control">
              <el-slider
                v-model="form.titleAnimationDuration"
                :min="0.1"
                :max="2"
                :step="0.1"
                :show-input="true"
                :input-size="'small'"
              />
              <span class="slider-value">{{ form.titleAnimationDuration.toFixed(1) }}s</span>
            </div>
          </div>
          
          <div class="form-item">
            <label class="form-label">
              <el-checkbox v-model="form.titleBackgroundOverlay" />
              {{ t('Background Overlay') }}
            </label>
          </div>
          
          <div v-if="form.titleBackgroundOverlay" class="form-item">
            <label class="form-label">{{ t('Overlay Color') }}</label>
            <el-color-picker
              v-model="form.titleOverlayColor"
              show-alpha
              class="color-picker-full"
            />
          </div>
          
          <div class="form-item">
            <div class="label-row">
              <label class="form-label">{{ t('Title Text') }}</label>
              <el-button 
                size="small" 
                type="text" 
                @click="copyFromScenePanel"
                :disabled="!scriptStore.videoTitle"
              >
                {{ t('Copy title text from scene panel') }}
              </el-button>
            </div>
            <el-input 
              v-model="form.titleText" 
              :placeholder="t('Enter video title')"
              type="textarea"
              :rows="3"
              maxlength="500"
              show-word-limit
              class="form-textarea"
            />
          </div>
          
          <div class="form-item">
            <label class="form-label">{{ t('Horizontal Alignment') }}</label>
            <el-select v-model="form.titleAlign" :placeholder="t('Select alignment')" class="form-select">
              <el-option :label="t('Left')" value="left" />
              <el-option :label="t('Center')" value="center" />
              <el-option :label="t('Right')" value="right" />
            </el-select>
          </div>
          
          <div class="preview-section">
            <h3>{{ t('Preview') }}</h3>
            <div class="preview-container">
              <div class="preview-video-frame" :style="previewFrameStyle">
                <div 
                  class="preview-title"
                  :style="previewStyle"
                >
                  {{ form.titleText || scriptStore.videoTitle || t('Preview Title') }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style>
@font-face {
  font-family: 'Microsoft YaHei Bold';
  src: url('/fonts/MicrosoftYaHeiBold.ttc') format('truetype');
  font-weight: bold;
  font-display: swap;
}

@font-face {
  font-family: 'Microsoft YaHei Normal';
  src: url('/fonts/MicrosoftYaHeiNormal.ttc') format('truetype');
  font-display: swap;
}

@font-face {
  font-family: 'STHeiti Light';
  src: url('/fonts/STHeitiLight.ttc') format('truetype');
  font-weight: 300;
  font-display: swap;
}

@font-face {
  font-family: 'STHeiti Medium';
  src: url('/fonts/STHeitiMedium.ttc') format('truetype');
  font-weight: 500;
  font-display: swap;
}

@font-face {
  font-family: 'Charm Bold';
  src: url('/fonts/Charm-Bold.ttf') format('truetype');
  font-weight: bold;
  font-display: swap;
}

@font-face {
  font-family: 'Charm Regular';
  src: url('/fonts/Charm-Regular.ttf') format('truetype');
  font-display: swap;
}

@font-face {
  font-family: 'UTM Kabel KT';
  src: url('/fonts/UTM Kabel KT.ttf') format('truetype');
  font-display: swap;
}
</style>

<script setup lang="ts">
import { reactive, watch, onMounted, computed } from 'vue';
import { useI18nStore } from '../stores/i18n';
import { useSettingsStore } from '../stores/settings';
import { useScriptStore } from '../stores/script';
import { apiService } from '../services/api';

const i18nStore = useI18nStore();
const t = i18nStore.t;
const settingsStore = useSettingsStore();
const scriptStore = useScriptStore();

const titleStyles = reactive<{ [key: string]: { name: string; description: string } }>({});

const availableFonts = [
  // 原有字体 / Original fonts
  'MicrosoftYaHeiBold.ttc',
  'MicrosoftYaHeiNormal.ttc',
  'STHeitiLight.ttc',
  'STHeitiMedium.ttc',
  'Charm-Bold.ttf',
  'Charm-Regular.ttf',
  'UTM Kabel KT.ttf',
];

const fontNameMapping: { [key: string]: string } = {
  'MicrosoftYaHeiBold.ttc': 'Microsoft YaHei Bold',
  'MicrosoftYaHeiNormal.ttc': 'Microsoft YaHei Normal',
  'STHeitiLight.ttc': 'STHeiti Light',
  'STHeitiMedium.ttc': 'STHeiti Medium',
  'Charm-Bold.ttf': 'Charm Bold',
  'Charm-Regular.ttf': 'Charm Regular',
  'UTM Kabel KT.ttf': 'UTM Kabel KT',
};

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

const form = reactive({
  titleEnabled: settingsStore.video.title.enabled,
  titleText: settingsStore.video.title.text || scriptStore.videoTitle,
  titleDuration: settingsStore.video.title.duration,
  titleFont: settingsStore.video.title.font,
  titleFontSize: settingsStore.video.title.fontSize,
  titleColor: settingsStore.video.title.color,
  titleStrokeColor: settingsStore.video.title.strokeColor,
  titleStrokeWidth: settingsStore.video.title.strokeWidth,
  titleBackgroundColor: settingsStore.video.title.backgroundColor,
  titlePosition: settingsStore.video.title.position,
  titleMargin: settingsStore.video.title.margin * 100,
  titleMarginLeft: settingsStore.video.title.marginLeft * 100,
  titleMarginRight: settingsStore.video.title.marginRight * 100,
  titleAnimation: settingsStore.video.title.animation,
  titleAnimationDuration: settingsStore.video.title.animationDuration,
  titleBackgroundOverlay: settingsStore.video.title.backgroundOverlay,
  titleOverlayColor: settingsStore.video.title.overlayColor,
  titleStyle: settingsStore.video.title.style,
  titleAlign: settingsStore.video.title.align || 'center'
});

const isLightColor = (colorValue: string): boolean => {
  if (colorValue === 'transparent') return false;
  const hex = colorValue.startsWith('#') ? colorValue : '#000000';
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.5;
};

const previewFrameStyle = computed(() => {
  const aspect = settingsStore.video.aspect;
  const maxDim = 480;
  let width: number;
  let height: number;

  if (aspect === 'portrait' || aspect === 'portrait_9_16') {
    // 9:16
    height = maxDim;
    width = Math.round(maxDim * 9 / 16);
  } else if (aspect === 'landscape' || aspect === 'landscape_16_9') {
    // 16:9
    width = maxDim;
    height = Math.round(maxDim * 9 / 16);
  } else if (aspect === 'square') {
    // 1:1
    width = maxDim;
    height = maxDim;
  } else if (aspect === 'portrait_3_4') {
    // 3:4
    height = maxDim;
    width = Math.round(maxDim * 3 / 4);
  } else {
    // Default to portrait 9:16
    height = maxDim;
    width = Math.round(maxDim * 9 / 16);
  }

  return {
    backgroundColor: '#333',
    width: `${width}px`,
    height: `${height}px`
  };
});

const previewStyle = computed(() => {
  console.log('[TitleSettings] previewStyle computed - titleFont:', form.titleFont, 'mapped:', fontNameMapping[form.titleFont]);
  const marginPercent = form.titleMargin;
  const marginLeftPercent = form.titleMarginLeft;
  const marginRightPercent = form.titleMarginRight;
  
  // Scale font size proportionally to the preview frame vs real video width (1080px)
  const videoWidth = 1080;
  const previewWidth = parseInt(previewFrameStyle.value.width);
  const scaleFactor = previewWidth / videoWidth;
  const scaledFontSize = Math.round(form.titleFontSize * scaleFactor);
  
  let topPosition: string;
  if (form.titlePosition === 'top') {
    topPosition = `${marginPercent}%`;
  } else if (form.titlePosition === 'bottom') {
    topPosition = `auto`;
  } else {
    topPosition = '50%';
  }
  
  let bottomPosition: string;
  if (form.titlePosition === 'bottom') {
    bottomPosition = `${marginPercent}%`;
  } else {
    bottomPosition = 'auto';
  }
  
  const maxWidthPercent = 100 - marginLeftPercent - marginRightPercent;
  
  const scaledStrokeWidth = Math.max(1, Math.round(form.titleStrokeWidth * scaleFactor));
  const scaledPaddingV = Math.max(2, Math.round(10 * scaleFactor));
  const scaledPaddingH = Math.max(4, Math.round(20 * scaleFactor));
  const scaledBorderRadius = Math.max(2, Math.round(8 * scaleFactor));
  
  const mappedFont = fontNameMapping[form.titleFont] || form.titleFont;
  let fontFamilyValue = mappedFont;
  
  if (mappedFont.includes('YaHei')) {
    fontFamilyValue = `${mappedFont}, "Microsoft YaHei", "PingFang SC", sans-serif`;
  } else if (mappedFont.includes('Heiti')) {
    fontFamilyValue = `${mappedFont}, "STHeiti", "SimHei", sans-serif`;
  } else if (mappedFont.includes('Charm')) {
    fontFamilyValue = `${mappedFont}, cursive, sans-serif`;
  } else {
    fontFamilyValue = `${mappedFont}, sans-serif`;
  }
  
  return {
    fontFamily: `${fontFamilyValue} !important`,
    color: form.titleColor,
    fontSize: `${scaledFontSize}px`,
    textShadow: form.titleStrokeColor !== 'transparent' 
      ? `0 0 ${scaledStrokeWidth}px ${form.titleStrokeColor}, 0 0 ${scaledStrokeWidth}px ${form.titleStrokeColor}`
      : 'none',
    backgroundColor: form.titleBackgroundColor === 'transparent' ? 'transparent' : form.titleBackgroundColor,
    padding: form.titleBackgroundColor !== 'transparent' ? `${scaledPaddingV}px ${scaledPaddingH}px` : '0',
    borderRadius: form.titleBackgroundColor !== 'transparent' ? `${scaledBorderRadius}px` : '0',
    position: 'absolute' as const,
    left: `${marginLeftPercent}%`,
    right: `${marginRightPercent}%`,
    top: topPosition,
    bottom: bottomPosition,
    transform: form.titlePosition === 'center' ? 'translateY(-50%)' : 'none',
    textAlign: form.titleAlign as 'left' | 'center' | 'right',
    whiteSpace: 'pre-wrap' as const,
    maxWidth: `${maxWidthPercent}%`,
    wordBreak: 'break-word' as const
  };
});

const applyStyle = async (styleName: string) => {
  if (!styleName) return;
  
  const styleMap: { [key: string]: any } = {
    classic: {
      titleFont: 'STHeitiMedium.ttc',
      titleFontSize: 72,
      titleColor: '#FFFFFF',
      titleStrokeColor: '#000000',
      titleStrokeWidth: 2.0,
      titleBackgroundColor: 'transparent',
      titlePosition: 'center',
      titleMargin: 5,
      titleMarginLeft: 5,
      titleMarginRight: 5,
      titleAnimation: 'fade_in',
      titleAnimationDuration: 0.5,
      titleBackgroundOverlay: false,
      titleOverlayColor: 'rgba(0,0,0,0.5)'
    },
    modern: {
      titleFont: 'MicrosoftYaHeiBold.ttc',
      titleFontSize: 64,
      titleColor: '#F5F5F5',
      titleStrokeColor: '#333333',
      titleStrokeWidth: 1.5,
      titleBackgroundColor: 'transparent',
      titlePosition: 'top',
      titleMargin: 5,
      titleMarginLeft: 5,
      titleMarginRight: 5,
      titleAnimation: 'slide_down',
      titleAnimationDuration: 0.6,
      titleBackgroundOverlay: false,
      titleOverlayColor: 'rgba(0,0,0,0.5)'
    },
    bold: {
      titleFont: 'MicrosoftYaHeiBold.ttc',
      titleFontSize: 80,
      titleColor: '#FFD700',
      titleStrokeColor: '#8B4513',
      titleStrokeWidth: 3.0,
      titleBackgroundColor: 'transparent',
      titlePosition: 'center',
      titleMargin: 5,
      titleMarginLeft: 5,
      titleMarginRight: 5,
      titleAnimation: 'fade_in',
      titleAnimationDuration: 0.4,
      titleBackgroundOverlay: false,
      titleOverlayColor: 'rgba(0,0,0,0.5)'
    },
    minimal: {
      titleFont: 'STHeitiLight.ttc',
      titleFontSize: 60,
      titleColor: '#FFFFFF',
      titleStrokeColor: 'transparent',
      titleStrokeWidth: 0,
      titleBackgroundColor: 'transparent',
      titlePosition: 'bottom',
      titleMargin: 5,
      titleMarginLeft: 5,
      titleMarginRight: 5,
      titleAnimation: 'none',
      titleAnimationDuration: 0.3,
      titleBackgroundOverlay: false,
      titleOverlayColor: 'rgba(0,0,0,0.5)'
    },
    dark_overlay: {
      titleFont: 'MicrosoftYaHeiBold.ttc',
      titleFontSize: 68,
      titleColor: '#FFFFFF',
      titleStrokeColor: '#000000',
      titleStrokeWidth: 1.5,
      titleBackgroundColor: 'rgba(0,0,0,0.7)',
      titlePosition: 'bottom',
      titleMargin: 5,
      titleMarginLeft: 5,
      titleMarginRight: 5,
      titleAnimation: 'fade_in',
      titleAnimationDuration: 0.5,
      titleBackgroundOverlay: false,
      titleOverlayColor: 'rgba(0,0,0,0.5)'
    },
    gradient: {
      titleFont: 'UTM Kabel KT.ttf',
      titleFontSize: 76,
      titleColor: '#FF6B6B',
      titleStrokeColor: '#4ECDC4',
      titleStrokeWidth: 2.0,
      titleBackgroundColor: 'transparent',
      titlePosition: 'center',
      titleMargin: 5,
      titleMarginLeft: 5,
      titleMarginRight: 5,
      titleAnimation: 'slide_up',
      titleAnimationDuration: 0.7,
      titleBackgroundOverlay: false,
      titleOverlayColor: 'rgba(0,0,0,0.5)'
    },
    charm_elegant: {
      titleFont: 'Charm-Bold.ttf',
      titleFontSize: 76,
      titleColor: '#FFFFFF',
      titleStrokeColor: '#000000',
      titleStrokeWidth: 2.0,
      titleBackgroundColor: 'transparent',
      titlePosition: 'center',
      titleMargin: 5,
      titleMarginLeft: 5,
      titleMarginRight: 5,
      titleAnimation: 'fade_in',
      titleAnimationDuration: 0.6,
      titleBackgroundOverlay: false,
      titleOverlayColor: 'rgba(0,0,0,0.5)'
    },
    charm_regular: {
      titleFont: 'Charm-Regular.ttf',
      titleFontSize: 72,
      titleColor: '#F5F5F5',
      titleStrokeColor: '#333333',
      titleStrokeWidth: 1.5,
      titleBackgroundColor: 'transparent',
      titlePosition: 'center',
      titleMargin: 5,
      titleMarginLeft: 5,
      titleMarginRight: 5,
      titleAnimation: 'slide_down',
      titleAnimationDuration: 0.5,
      titleBackgroundOverlay: false,
      titleOverlayColor: 'rgba(0,0,0,0.5)'
    }
  };
  
  const style = styleMap[styleName];
  if (style) {
    Object.keys(style).forEach(key => {
      const formKey = key as keyof typeof form;
      if (formKey in form) {
        (form as any)[formKey] = style[key];
      }
    });
    form.titleStyle = styleName;
  }
};

const loadTitleStyles = async () => {
  try {
    const response = await apiService.getTitleStyles();
    if (response.status === 200 && response.data) {
      Object.assign(titleStyles, response.data);
    }
  } catch (error) {
    console.error('[TitleSettings] Failed to load title styles:', error);
  }
};

const loadConfig = async () => {
  try {
    const response = await apiService.getConfig();
    if (response.status === 200 && response.data) {
      const cfg = response.data;
      if (cfg.ui) {
        if (cfg.ui.title_enabled !== undefined) {
          form.titleEnabled = cfg.ui.title_enabled;
        }
        if (cfg.ui.title_text !== undefined) {
          form.titleText = cfg.ui.title_text;
        }
        if (cfg.ui.title_duration !== undefined) {
          form.titleDuration = cfg.ui.title_duration;
        }
        if (cfg.ui.title_font_name !== undefined) {
          form.titleFont = cfg.ui.title_font_name;
        }
        if (cfg.ui.title_font_size !== undefined) {
          form.titleFontSize = cfg.ui.title_font_size;
        }
        if (cfg.ui.title_text_color !== undefined) {
          form.titleColor = cfg.ui.title_text_color;
        }
        if (cfg.ui.title_stroke_color !== undefined) {
          form.titleStrokeColor = cfg.ui.title_stroke_color;
        }
        if (cfg.ui.title_stroke_width !== undefined) {
          form.titleStrokeWidth = cfg.ui.title_stroke_width;
        }
        if (cfg.ui.title_background_color !== undefined) {
          form.titleBackgroundColor = cfg.ui.title_background_color;
        }
        if (cfg.ui.title_position !== undefined) {
          form.titlePosition = cfg.ui.title_position;
        }
        if (cfg.ui.title_margin !== undefined) {
          form.titleMargin = cfg.ui.title_margin * 100;
        }
        if (cfg.ui.title_margin_left !== undefined) {
          form.titleMarginLeft = cfg.ui.title_margin_left * 100;
        }
        if (cfg.ui.title_margin_right !== undefined) {
          form.titleMarginRight = cfg.ui.title_margin_right * 100;
        }
        if (cfg.ui.title_animation !== undefined) {
          form.titleAnimation = cfg.ui.title_animation;
        }
        if (cfg.ui.title_animation_duration !== undefined) {
          form.titleAnimationDuration = cfg.ui.title_animation_duration;
        }
        if (cfg.ui.title_background_overlay !== undefined) {
          form.titleBackgroundOverlay = cfg.ui.title_background_overlay;
        }
        if (cfg.ui.title_overlay_color !== undefined) {
          form.titleOverlayColor = cfg.ui.title_overlay_color;
        }
        if (cfg.ui.title_style !== undefined) {
          form.titleStyle = cfg.ui.title_style;
        }
        if (cfg.ui.title_align !== undefined) {
          form.titleAlign = cfg.ui.title_align;
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
      ui: {
        title_enabled: form.titleEnabled,
        title_text: form.titleText,
        title_duration: form.titleDuration,
        title_font_name: form.titleFont,
        title_font_size: form.titleFontSize,
        title_text_color: form.titleColor,
        title_stroke_color: form.titleStrokeColor,
        title_stroke_width: form.titleStrokeWidth,
        title_background_color: form.titleBackgroundColor,
        title_position: form.titlePosition,
        title_margin: form.titleMargin / 100,
        title_margin_left: form.titleMarginLeft / 100,
        title_margin_right: form.titleMarginRight / 100,
        title_animation: form.titleAnimation,
        title_animation_duration: form.titleAnimationDuration,
        title_background_overlay: form.titleBackgroundOverlay,
        title_overlay_color: form.titleOverlayColor,
        title_style: form.titleStyle,
        title_align: form.titleAlign
      }
    };
    await apiService.updateConfig(cfg);
    console.log('[TitleSettings] Config saved:', cfg);
  } catch (error: any) {
    console.error('Failed to save config:', error);
  }
};

// Watch for changes to scriptStore.videoTitle
watch(() => scriptStore.videoTitle, (newTitle) => {
  if (newTitle) {
    form.titleText = newTitle;
  }
});

const copyFromScenePanel = () => {
  if (scriptStore.videoTitle) {
    form.titleText = scriptStore.videoTitle;
  }
};

const updateTitleSettings = () => {
  settingsStore.updateTitleSetting('enabled', form.titleEnabled);
  settingsStore.updateTitleSetting('text', form.titleText);
  settingsStore.updateTitleSetting('duration', form.titleDuration);
  settingsStore.updateTitleSetting('font', form.titleFont);
  settingsStore.updateTitleSetting('fontSize', form.titleFontSize);
  settingsStore.updateTitleSetting('color', form.titleColor);
  settingsStore.updateTitleSetting('strokeColor', form.titleStrokeColor);
  settingsStore.updateTitleSetting('strokeWidth', form.titleStrokeWidth);
  settingsStore.updateTitleSetting('backgroundColor', form.titleBackgroundColor);
  settingsStore.updateTitleSetting('position', form.titlePosition);
  settingsStore.updateTitleSetting('margin', form.titleMargin / 100);
  settingsStore.updateTitleSetting('marginLeft', form.titleMarginLeft / 100);
  settingsStore.updateTitleSetting('marginRight', form.titleMarginRight / 100);
  settingsStore.updateTitleSetting('animation', form.titleAnimation);
  settingsStore.updateTitleSetting('animationDuration', form.titleAnimationDuration);
  settingsStore.updateTitleSetting('backgroundOverlay', form.titleBackgroundOverlay);
  settingsStore.updateTitleSetting('overlayColor', form.titleOverlayColor);
  settingsStore.updateTitleSetting('style', form.titleStyle);
  settingsStore.updateTitleSetting('align', form.titleAlign);
};

watch([
  () => form.titleEnabled,
  () => form.titleText,
  () => form.titleDuration,
  () => form.titleFont,
  () => form.titleFontSize,
  () => form.titleColor,
  () => form.titleStrokeColor,
  () => form.titleStrokeWidth,
  () => form.titleBackgroundColor,
  () => form.titlePosition,
  () => form.titleMargin,
  () => form.titleMarginLeft,
  () => form.titleMarginRight,
  () => form.titleAnimation,
  () => form.titleAnimationDuration,
  () => form.titleBackgroundOverlay,
  () => form.titleOverlayColor,
  () => form.titleStyle,
  () => form.titleAlign
], () => {
  saveConfig();
  updateTitleSettings();
});

watch(() => settingsStore.video.title, (newTitle) => {
  form.titleEnabled = newTitle.enabled;
  form.titleText = newTitle.text || '';
  form.titleDuration = newTitle.duration;
  form.titleFont = newTitle.font;
  form.titleFontSize = newTitle.fontSize;
  form.titleColor = newTitle.color;
  form.titleStrokeColor = newTitle.strokeColor;
  form.titleStrokeWidth = newTitle.strokeWidth;
  form.titleBackgroundColor = newTitle.backgroundColor;
  form.titlePosition = newTitle.position;
  form.titleMargin = newTitle.margin * 100;
  form.titleMarginLeft = newTitle.marginLeft * 100;
  form.titleMarginRight = newTitle.marginRight * 100;
  form.titleAnimation = newTitle.animation;
  form.titleAnimationDuration = newTitle.animationDuration;
  form.titleBackgroundOverlay = newTitle.backgroundOverlay;
  form.titleOverlayColor = newTitle.overlayColor;
  form.titleStyle = newTitle.style;
  form.titleAlign = newTitle.align || 'center';
}, { deep: true });

onMounted(async () => {
  await loadConfig();
  await loadTitleStyles();
});

defineExpose({
  form,
  copyFromScenePanel
});
</script>

<style scoped>
.title-settings {
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
  gap: 4px;
}

.label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.form-label {
  font-weight: normal;
  font-size: 14px;
  color: #333;
  margin-bottom: 0;
  line-height: 1.4;
  display: flex;
  align-items: center;
  gap: 8px;
}

.form-input {
  width: 100%;
  padding: 8px 12px;
  border-radius: 4px;
  box-sizing: border-box;
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

.title-content {
  padding-top: 16px;
  border-top: 1px dashed #e4e7ed;
}

.slider-control {
  display: flex;
  align-items: center;
  gap: 10px;
}

.slider-value {
  min-width: 70px;
  text-align: right;
  font-size: 14px;
  color: #666;
}

.margin-row {
  display: flex;
  gap: 20px;
}

.margin-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.margin-label {
  font-size: 12px;
  color: #666;
}

.margin-slider {
  width: 100%;
}

.margin-value {
  font-size: 12px;
  color: #666;
  text-align: right;
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

.color-picker-full {
  width: 100%;
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

.preview-section {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px dashed #e4e7ed;
}

.preview-section h3 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 12px;
  color: #303133;
}

.preview-container {
  display: flex;
  justify-content: center;
}

.preview-video-frame {
  border-radius: 12px;
  position: relative;
  overflow: hidden;
}

.preview-title {
  color: #ffffff;
  font-family: inherit;
}
</style>