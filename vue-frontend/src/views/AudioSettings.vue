<template>
  <div class="audio-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">{{ t('Audio Settings') }}</h2>
        </div>
      </template>
      
      <div class="settings-form">
        <div class="form-item">
          <label class="form-label">{{ t('TTS Server') }}</label>
          <el-select v-model="form.ttsServer" :placeholder="t('Select TTS server')" class="form-select">
            <el-option label="Azure TTS V1" value="azure-tts-v1" />
            <el-option label="Azure TTS V2" value="azure-tts-v2" />
            <el-option label="SiliconFlow TTS" value="siliconflow" />
            <el-option label="Google Gemini TTS" value="gemini-tts" />
            <el-option label="Coze TTS" value="coze-tts" />
          </el-select>
        </div>
        
        <!-- Coze TTS specific settings - search and refresh -->
        <div v-if="form.ttsServer === 'coze-tts'" class="form-item">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span>Coze TTS</span>
            <el-button type="primary" size="small" icon="Refresh">
              {{ t('Refresh') }}
            </el-button>
          </div>
          <el-input
            v-model="searchKeyword"
            :placeholder="t('Enter voice keyword to search...')"
            class="form-input"
          />
        </div>
        
        <div class="form-item">
          <label class="form-label">{{ t('Speaking Voice') }} <span style="color: red;">{{ t('(Keep consistent with copy language)') }}</span><span v-if="form.ttsServer === 'azure-tts-v1'" style="color: red;">{{ t('(Note: V2 version is better, but requires API KEY)') }}</span></label>
          <el-select v-model="form.speechSynthesis" :placeholder="t('Select voice')" class="form-select">
            <el-option 
              v-for="voice in filteredVoiceList" 
              :key="voice.value" 
              :label="voice.label" 
              :value="voice.value" 
            />
          </el-select>
        </div>
        
        <!-- Coze TTS specific settings - emotion selection -->
        <div v-if="form.ttsServer === 'coze-tts' && currentVoiceSupportsEmotion" class="form-item">
          <label class="form-label">{{ t('Voice Emotion') }}</label>
          <el-select v-model="form.voiceEmotion" :placeholder="t('Select emotion')" class="form-select">
            <el-option :label="t('neutral-Neutral')" value="neutral" />
            <el-option :label="t('happy-Happy')" value="happy" />
            <el-option :label="t('sad-Sad')" value="sad" />
            <el-option :label="t('angry-Angry')" value="angry" />
            <el-option :label="t('fear-Fear')" value="fear" />
            <el-option :label="t('surprise-Surprise')" value="surprise" />
          </el-select>
        </div>
        
        <div class="form-item">
          <el-button type="primary" class="form-button">{{ t('Test Speech Synthesis') }}</el-button>
        </div>
        
        <!-- Azure TTS V2 specific settings -->
        <div v-if="form.ttsServer === 'azure-tts-v2'">
          <div class="form-item">
            <label class="form-label">{{ t('Service Region') }} <span style="color: blue;">{{ t('(Required, ') }}<a href="https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/SpeechServices" target="_blank">{{ t('click to get') }}</a>{{ t(')') }}</span></label>
            <el-input
              v-model="form.speechRegion"
              :placeholder="t('Enter service region')"
              class="form-input"
            />
          </div>
          
          <div class="form-item">
            <label class="form-label">API Key <span style="color: blue;">{{ t('(Required, either key 1 or key 2 ') }}<a href="https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/SpeechServices" target="_blank">{{ t('click to get') }}</a>{{ t(')') }}</span></label>
            <el-input
              v-model="form.speechKey"
              :placeholder="t('Enter API Key')"
              type="password"
              show-password
              class="form-input"
            />
          </div>
        </div>
        
        <!-- SiliconFlow TTS specific settings -->
        <div v-if="form.ttsServer === 'siliconflow'">
          <div class="form-item">
            <label class="form-label">{{ t('SiliconFlow API Key') }} <a href="https://cloud.siliconflow.cn/account/ak" target="_blank">{{ t('click to get') }}</a></label>
            <el-input
              v-model="form.siliconflowApiKey"
              :placeholder="t('Enter API key')"
              type="password"
              show-password
              class="form-input"
            />
          </div>
          
          <div class="form-item">
            <el-alert
              :title="t('SiliconFlow TTS Settings:')"
              type="info"
              :closable="false"
            >
              <ul>
                <li>{{ t('Speech rate range [0.25, 4.0], default value is 1.0') }}</li>
                <li>{{ t('Volume: Use speaking volume setting, default value 1.0 corresponds to gain 0') }}</li>
              </ul>
            </el-alert>
          </div>
        </div>
        
        <!-- Coze TTS specific settings -->
        <div v-if="form.ttsServer === 'coze-tts'">
          <div class="form-item">
            <label class="form-label">Coze API Key</label>
            <el-input
              v-model="form.cozeApiKey"
              :placeholder="t('Enter API Key')"
              type="password"
              show-password
              class="form-input"
            />
          </div>
          
          <div class="form-item">
            <el-alert
              :title="t('Coze TTS Settings:')"
              type="info"
              :closable="false"
            >
              <ul>
                <li>{{ t('Speech rate range [0.5, 2.0], default value is 1.0') }}</li>
                <li>{{ t('Volume range [0.1, 2.0], default value is 1.0') }}</li>
                <li>{{ t('Get API Key from') }} <a href="https://www.coze.cn" target="_blank">https://www.coze.cn</a></li>
              </ul>
            </el-alert>
          </div>
        </div>
        
        <div class="form-item">
          <label class="form-label">{{ t('Speaking Volume (1.0 means 100%)') }}</label>
          <el-select v-model="form.speechVolume" :placeholder="t('Select volume')" class="form-select">
            <el-option label="0.5" value="0.5" />
            <el-option label="0.8" value="0.8" />
            <el-option label="1.0" value="1.0" />
            <el-option label="1.2" value="1.2" />
            <el-option label="1.5" value="1.5" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label">{{ t('Speaking Rate (1.0 means normal speed)') }}</label>
          <el-select v-model="form.speechRate" :placeholder="t('Select rate')" class="form-select">
            <el-option label="0.8" value="0.8" />
            <el-option label="1.0" value="1.0" />
            <el-option label="1.2" value="1.2" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label">{{ t('Background Music') }}</label>
          <el-select v-model="form.backgroundMusic" :placeholder="t('Select background music')" class="form-select">
            <el-option :label="t('No background music')" value="none" />
            <el-option :label="t('Random background music')" value="random" />
            <el-option :label="t('Custom background music')" value="custom" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label">{{ t('Background Music Volume (0.2 means 20%, background sound should not be too loud)') }}</label>
          <el-select v-model="form.backgroundMusicVolume" :placeholder="t('Select volume')" class="form-select">
            <el-option label="0.1" value="0.1" />
            <el-option label="0.2" value="0.2" />
            <el-option label="0.3" value="0.3" />
            <el-option label="0.4" value="0.4" />
            <el-option label="0.5" value="0.5" />
          </el-select>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue';
import { useI18nStore } from '../stores/i18n';

const i18nStore = useI18nStore();
const t = i18nStore.t;

const form = reactive({
  ttsServer: 'azure-tts-v1',
  speechSynthesis: '',
  speechRegion: '',
  speechKey: '',
  siliconflowApiKey: '',
  cozeApiKey: '',
  voiceEmotion: 'neutral',
  speechVolume: '1.0',
  speechRate: '1.0',
  backgroundMusic: 'random',
  backgroundMusicVolume: '0.2'
});

// Search keyword
const searchKeyword = ref('');

// Voice interface with optional supportsEmotion property
interface Voice {
  label: string;
  value: string;
  supportsEmotion?: boolean;
}

// Simulated voice lists for different TTS servers
const voiceLists: Record<string, Voice[]> = {
  'azure-tts-v1': [
    { label: 'zh-CN-XiaoxiaoNeural-Female', value: 'zh-CN-XiaoxiaoNeural' },
    { label: 'zh-CN-YiaoyiNeural-Female', value: 'zh-CN-YiaoyiNeural' },
    { label: 'zh-CN-YunjianNeural-Male', value: 'zh-CN-YunjianNeural' },
    { label: 'zh-CN-YunxiNeural-Male', value: 'zh-CN-YunxiNeural' },
    { label: 'zh-CN-YunxiaNeural-Male', value: 'zh-CN-YunxiaNeural' },
    { label: 'zh-CN-YunyangNeural-Male', value: 'zh-CN-YunyangNeural' },
    { label: 'zh-CN-liaoning-XiaobeiNeural-Female', value: 'zh-CN-liaoning-XiaobeiNeural' },
    { label: 'zh-CN-shaanxi-XiaoniNeural-Female', value: 'zh-CN-shaanxi-XiaoniNeural' },
    { label: 'zh-HK-HiuGaaiNeural-Female', value: 'zh-HK-HiuGaaiNeural' },
    { label: 'zh-HK-HiuMaanNeural-Female', value: 'zh-HK-HiuMaanNeural' },
    { label: 'zh-HK-WanLungNeural-Male', value: 'zh-HK-WanLungNeural' },
    { label: 'zh-TW-HsiaoChenNeural-Female', value: 'zh-TW-HsiaoChenNeural' },
    { label: 'zh-TW-HsiaoYuNeural-Female', value: 'zh-TW-HsiaoYuNeural' },
    { label: 'zh-TW-YunJheNeural-Male', value: 'zh-TW-YunJheNeural' }
  ],
  'azure-tts-v2': [
    { label: 'zh-CN-XiaoxiaoNeural-V2-Female', value: 'zh-CN-XiaoxiaoNeural-V2' },
    { label: 'zh-CN-YiaoyiNeural-V2-Female', value: 'zh-CN-YiaoyiNeural-V2' },
    { label: 'zh-CN-YunjianNeural-V2-Male', value: 'zh-CN-YunjianNeural-V2' },
    { label: 'zh-CN-YunxiNeural-V2-Male', value: 'zh-CN-YunxiNeural-V2' },
    { label: 'zh-CN-YunxiaNeural-V2-Male', value: 'zh-CN-YunxiaNeural-V2' },
    { label: 'zh-CN-YunyangNeural-V2-Male', value: 'zh-CN-YunyangNeural-V2' },
    { label: 'de-DE-FlorianMultilingual-V2-Male', value: 'de-DE-FlorianMultilingual-V2' },
    { label: 'en-US-JennyMultilingual-V2-Female', value: 'en-US-JennyMultilingual-V2' }
  ],
  'gemini-tts': [
    { label: 'gemini:Zephyr-Female', value: 'gemini:Zephyr-Female' },
    { label: 'gemini:Puck-Male', value: 'gemini:Puck-Male' },
    { label: 'gemini:Charon-Male', value: 'gemini:Charon-Male' },
    { label: 'gemini:Kore-Female', value: 'gemini:Kore-Female' },
    { label: 'gemini:Fenrir-Male', value: 'gemini:Fenrir-Male' },
    { label: 'gemini:Aoede-Female', value: 'gemini:Aoede-Female' },
    { label: 'gemini:Thalia-Female', value: 'gemini:Thalia-Female' },
    { label: 'gemini:Sage-Male', value: 'gemini:Sage-Male' },
    { label: 'gemini:Echo-Female', value: 'gemini:Echo-Female' },
    { label: 'gemini:Harmony-Female', value: 'gemini:Harmony-Female' },
    { label: 'gemini:Lux-Female', value: 'gemini:Lux-Female' },
    { label: 'gemini:Nova-Female', value: 'gemini:Nova-Female' },
    { label: 'gemini:Vale-Male', value: 'gemini:Vale-Male' },
    { label: 'gemini:Orion-Male', value: 'gemini:Orion-Male' },
    { label: 'gemini:Atlas-Male', value: 'gemini:Atlas-Male' }
  ],
  'siliconflow': [
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex-Male', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex-Male' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:anna-Female', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:anna-Female' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:bella-Female', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:bella-Female' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:benjamin-Male', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:benjamin-Male' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:charles-Male', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:charles-Male' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:claire-Female', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:claire-Female' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:david-Male', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:david-Male' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:diana-Female', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:diana-Female' }
  ],
  'coze-tts': [
    { label: 'Ao Cang-Male', value: 'coze|7426720361732915209|骜苍-男性', supportsEmotion: false },
    { label: 'Zhuang Zong (Multi-emotion)-Male', value: 'coze|7426720361732915210|做好霸总-男性', supportsEmotion: true },
    { label: 'Xiao Yi-Female', value: 'coze|7426720361732915211|小一-女性', supportsEmotion: false },
    { label: 'Xiao Nuan-Female', value: 'coze|7426720361732915212|小暖-女性', supportsEmotion: false },
    { label: 'Xiao Ku-Male', value: 'coze|7426720361732915213|小酷-男性', supportsEmotion: false },
    { label: 'Xiao Tian-Female', value: 'coze|7426720361732915214|小甜-女性', supportsEmotion: false },
    { label: 'Xiao Wen-Male', value: 'coze|7426720361732915215|小稳-男性', supportsEmotion: false },
    { label: 'Xiao Meng-Female', value: 'coze|7426720361732915216|小萌-女性', supportsEmotion: false },
    { label: 'Xiao Sa-Female', value: 'coze|7426720361732915217|小飒-女性', supportsEmotion: false },
    { label: 'Xiao Zhi-Male', value: 'coze|7426720361732915218|小智-男性', supportsEmotion: false }
  ]
};

// Current TTS server's voice list
const currentVoiceList = computed(() => {
  return voiceLists[form.ttsServer as keyof typeof voiceLists] || [];
});

// Filtered voice list (supports search)
const filteredVoiceList = computed(() => {
  if (!searchKeyword.value) {
    return currentVoiceList.value;
  }
  const keyword = searchKeyword.value.toLowerCase();
  return currentVoiceList.value.filter((voice: Voice) => 
    voice.label.toLowerCase().includes(keyword)
  );
});

// Check if current selected voice supports emotion
const currentVoiceSupportsEmotion = computed(() => {
  if (form.ttsServer !== 'coze-tts') {
    return false;
  }
  const selectedVoice = currentVoiceList.value.find((voice: Voice) => voice.value === form.speechSynthesis);
  return selectedVoice ? selectedVoice.supportsEmotion || false : false;
});

// Watch TTS server changes, reset voice selection
watch(() => form.ttsServer, (newServer) => {
  const voices = voiceLists[newServer as keyof typeof voiceLists] || [];
  form.speechSynthesis = voices.length > 0 ? voices[0].value : '';
  form.voiceEmotion = 'neutral';
});

// Watch voice changes, reset emotion selection
watch(() => form.speechSynthesis, () => {
  if (!currentVoiceSupportsEmotion.value) {
    form.voiceEmotion = 'neutral';
  }
});

// Initialize default voice
const initDefaultVoice = () => {
  const voices = voiceLists[form.ttsServer as keyof typeof voiceLists] || [];
  form.speechSynthesis = voices.length > 0 ? voices[0].value : '';
};

// Initialize
initDefaultVoice();

defineExpose({
  form
});
</script>

<style scoped>
.audio-settings {
  width: 100%;
}

.card-header {
  margin-bottom: 4px;
}

.title {
  font-size: 18px;
  font-weight: bold;
  margin: 0;
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
  font-size: 14px;
  margin-bottom: 4px;
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
  border-color: #000;
  outline: none;
}

.form-input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  transition: border-color 0.3s;
  box-sizing: border-box;
}

.form-input:hover {
  border-color: #000;
}

.form-input:focus {
  border-color: #000;
  outline: none;
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
</style>