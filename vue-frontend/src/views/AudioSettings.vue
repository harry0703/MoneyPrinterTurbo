<template>
  <div class="audio-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">音频设置</h2>
        </div>
      </template>
      
      <div class="settings-form">
        <div class="form-item">
          <label class="form-label">TTS服务器</label>
          <el-select v-model="form.ttsServer" placeholder="选择TTS服务器" class="form-select">
            <el-option label="Azure TTS V1" value="azure-tts-v1" />
            <el-option label="Azure TTS V2" value="azure-tts-v2" />
            <el-option label="SiliconFlow TTS" value="siliconflow" />
            <el-option label="Google Gemini TTS" value="gemini-tts" />
            <el-option label="Coze TTS" value="coze-tts" />
          </el-select>
        </div>
        
        <!-- Coze TTS 特有设置 - 搜索和刷新 -->
        <div v-if="form.ttsServer === 'coze-tts'" class="form-item">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span>Coze TTS</span>
            <el-button type="primary" size="small" icon="Refresh">
              刷新
            </el-button>
          </div>
          <el-input
            v-model="searchKeyword"
            placeholder="输入音色关键词搜索..."
            class="form-input"
          />
        </div>
        
        <div class="form-item">
          <label class="form-label">朗读声音 <span style="color: red;">（与文案语言保持一致）</span><span v-if="form.ttsServer === 'azure-tts-v1'" style="color: red;">（注意：V2版本更好，但需要API KEY）</span></label>
          <el-select v-model="form.speechSynthesis" placeholder="选择声音" class="form-select">
            <el-option 
              v-for="voice in filteredVoiceList" 
              :key="voice.value" 
              :label="voice.label" 
              :value="voice.value" 
            />
          </el-select>
        </div>
        
        <!-- Coze TTS 特有设置 - 情感选择 -->
        <div v-if="form.ttsServer === 'coze-tts' && currentVoiceSupportsEmotion" class="form-item">
          <label class="form-label">语音情感</label>
          <el-select v-model="form.voiceEmotion" placeholder="选择情感" class="form-select">
            <el-option label="neutral-中性" value="neutral" />
            <el-option label="happy-开心" value="happy" />
            <el-option label="sad-悲伤" value="sad" />
            <el-option label="angry-愤怒" value="angry" />
            <el-option label="fear-恐惧" value="fear" />
            <el-option label="surprise-惊讶" value="surprise" />
          </el-select>
        </div>
        
        <div class="form-item">
          <el-button type="primary" class="form-button">试听语音合成</el-button>
        </div>
        
        <!-- Azure TTS V2 特有设置 -->
        <div v-if="form.ttsServer === 'azure-tts-v2'">
          <div class="form-item">
            <label class="form-label">服务区域 <span style="color: blue;">（必填，<a href="https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/SpeechServices" target="_blank">点击获取</a>）</span></label>
            <el-input
              v-model="form.speechRegion"
              placeholder="输入服务区域"
              class="form-input"
            />
          </div>
          
          <div class="form-item">
            <label class="form-label">API Key <span style="color: blue;">（必填，密钥1或密钥2均可 <a href="https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/SpeechServices" target="_blank">点击获取</a>）</span></label>
            <el-input
              v-model="form.speechKey"
              placeholder="输入API Key"
              type="password"
              show-password
              class="form-input"
            />
          </div>
        </div>
        
        <!-- SiliconFlow TTS 特有设置 -->
        <div v-if="form.ttsServer === 'siliconflow'">
          <div class="form-item">
            <label class="form-label">硅基流动API密钥 <a href="https://cloud.siliconflow.cn/account/ak" target="_blank">点击获取</a></label>
            <el-input
              v-model="form.siliconflowApiKey"
              placeholder="输入API密钥"
              type="password"
              show-password
              class="form-input"
            />
          </div>
          
          <div class="form-item">
            <el-alert
              title="硅基流动TTS设置："
              type="info"
              :closable="false"
            >
              <ul>
                <li>语速范围 [0.25, 4.0]，默认值为1.0</li>
                <li>音量：使用朗读音量设置，默认值1.0对应增益0</li>
              </ul>
            </el-alert>
          </div>
        </div>
        
        <!-- Coze TTS 特有设置 -->
        <div v-if="form.ttsServer === 'coze-tts'">
          <div class="form-item">
            <label class="form-label">Coze API Key</label>
            <el-input
              v-model="form.cozeApiKey"
              placeholder="输入API Key"
              type="password"
              show-password
              class="form-input"
            />
          </div>
          
          <div class="form-item">
            <el-alert
              title="Coze TTS设置："
              type="info"
              :closable="false"
            >
              <ul>
                <li>语速范围 [0.5, 2.0]，默认值为1.0</li>
                <li>音量范围 [0.1, 2.0]，默认值为1.0</li>
                <li>从 <a href="https://www.coze.cn" target="_blank">https://www.coze.cn</a> 获取 API Key</li>
              </ul>
            </el-alert>
          </div>
        </div>
        
        <div class="form-item">
          <label class="form-label">朗读音量（1.0表示100%）</label>
          <el-select v-model="form.speechVolume" placeholder="选择音量" class="form-select">
            <el-option label="0.5" value="0.5" />
            <el-option label="0.8" value="0.8" />
            <el-option label="1.0" value="1.0" />
            <el-option label="1.2" value="1.2" />
            <el-option label="1.5" value="1.5" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label">朗读速度（1.0表示1倍速）</label>
          <el-select v-model="form.speechRate" placeholder="选择速度" class="form-select">
            <el-option label="0.8" value="0.8" />
            <el-option label="1.0" value="1.0" />
            <el-option label="1.2" value="1.2" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label">背景音乐</label>
          <el-select v-model="form.backgroundMusic" placeholder="选择背景音乐" class="form-select">
            <el-option label="无背景音乐" value="none" />
            <el-option label="随机背景音乐" value="random" />
            <el-option label="自定义背景音乐" value="custom" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label">背景音乐音量（0.2表示20%，背景声音不宜过高）</label>
          <el-select v-model="form.backgroundMusicVolume" placeholder="选择音量" class="form-select">
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

// 搜索关键词
const searchKeyword = ref('');

// 模拟不同TTS服务器的声音列表
const voiceLists = {
  'azure-tts-v1': [
    { label: 'zh-CN-XiaoxiaoNeural-女性', value: 'zh-CN-XiaoxiaoNeural' },
    { label: 'zh-CN-XiaoyiNeural-女性', value: 'zh-CN-XiaoyiNeural' },
    { label: 'zh-CN-YunjianNeural-男性', value: 'zh-CN-YunjianNeural' },
    { label: 'zh-CN-YunxiNeural-男性', value: 'zh-CN-YunxiNeural' },
    { label: 'zh-CN-YunxiaNeural-男性', value: 'zh-CN-YunxiaNeural' },
    { label: 'zh-CN-YunyangNeural-男性', value: 'zh-CN-YunyangNeural' },
    { label: 'zh-CN-liaoning-XiaobeiNeural-女性', value: 'zh-CN-liaoning-XiaobeiNeural' },
    { label: 'zh-CN-shaanxi-XiaoniNeural-女性', value: 'zh-CN-shaanxi-XiaoniNeural' },
    { label: 'zh-HK-HiuGaaiNeural-女性', value: 'zh-HK-HiuGaaiNeural' },
    { label: 'zh-HK-HiuMaanNeural-女性', value: 'zh-HK-HiuMaanNeural' },
    { label: 'zh-HK-WanLungNeural-男性', value: 'zh-HK-WanLungNeural' },
    { label: 'zh-TW-HsiaoChenNeural-女性', value: 'zh-TW-HsiaoChenNeural' },
    { label: 'zh-TW-HsiaoYuNeural-女性', value: 'zh-TW-HsiaoYuNeural' },
    { label: 'zh-TW-YunJheNeural-男性', value: 'zh-TW-YunJheNeural' }
  ],
  'azure-tts-v2': [
    { label: 'zh-CN-XiaoxiaoNeural-V2-女性', value: 'zh-CN-XiaoxiaoNeural-V2' },
    { label: 'zh-CN-XiaoyiNeural-V2-女性', value: 'zh-CN-XiaoyiNeural-V2' },
    { label: 'zh-CN-YunjianNeural-V2-男性', value: 'zh-CN-YunjianNeural-V2' },
    { label: 'zh-CN-YunxiNeural-V2-男性', value: 'zh-CN-YunxiNeural-V2' },
    { label: 'zh-CN-YunxiaNeural-V2-男性', value: 'zh-CN-YunxiaNeural-V2' },
    { label: 'zh-CN-YunyangNeural-V2-男性', value: 'zh-CN-YunyangNeural-V2' },
    { label: 'de-DE-FlorianMultilingual-V2-男性', value: 'de-DE-FlorianMultilingual-V2' },
    { label: 'en-US-JennyMultilingual-V2-女性', value: 'en-US-JennyMultilingual-V2' }
  ],
  'gemini-tts': [
    { label: 'gemini:Zephyr-女性', value: 'gemini:Zephyr-Female' },
    { label: 'gemini:Puck-男性', value: 'gemini:Puck-Male' },
    { label: 'gemini:Charon-男性', value: 'gemini:Charon-Male' },
    { label: 'gemini:Kore-女性', value: 'gemini:Kore-Female' },
    { label: 'gemini:Fenrir-男性', value: 'gemini:Fenrir-Male' },
    { label: 'gemini:Aoede-女性', value: 'gemini:Aoede-Female' },
    { label: 'gemini:Thalia-女性', value: 'gemini:Thalia-Female' },
    { label: 'gemini:Sage-男性', value: 'gemini:Sage-Male' },
    { label: 'gemini:Echo-女性', value: 'gemini:Echo-Female' },
    { label: 'gemini:Harmony-女性', value: 'gemini:Harmony-Female' },
    { label: 'gemini:Lux-女性', value: 'gemini:Lux-Female' },
    { label: 'gemini:Nova-女性', value: 'gemini:Nova-Female' },
    { label: 'gemini:Vale-男性', value: 'gemini:Vale-Male' },
    { label: 'gemini:Orion-男性', value: 'gemini:Orion-Male' },
    { label: 'gemini:Atlas-男性', value: 'gemini:Atlas-Male' }
  ],
  'siliconflow': [
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex-男性', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex-Male' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:anna-女性', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:anna-Female' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:bella-女性', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:bella-Female' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:benjamin-男性', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:benjamin-Male' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:charles-男性', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:charles-Male' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:claire-女性', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:claire-Female' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:david-男性', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:david-Male' },
    { label: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:diana-女性', value: 'siliconflow:FunAudioLLM/CosyVoice2-0.5B:diana-Female' }
  ],
  'coze-tts': [
    { label: '骜苍-男性', value: 'coze|7426720361732915209|骜苍-男性', supportsEmotion: false },
    { label: '做好霸总 (多情感)-男性', value: 'coze|7426720361732915210|做好霸总-男性', supportsEmotion: true },
    { label: '小一-女性', value: 'coze|7426720361732915211|小一-女性', supportsEmotion: false },
    { label: '小暖-女性', value: 'coze|7426720361732915212|小暖-女性', supportsEmotion: false },
    { label: '小酷-男性', value: 'coze|7426720361732915213|小酷-男性', supportsEmotion: false },
    { label: '小甜-女性', value: 'coze|7426720361732915214|小甜-女性', supportsEmotion: false },
    { label: '小稳-男性', value: 'coze|7426720361732915215|小稳-男性', supportsEmotion: false },
    { label: '小萌-女性', value: 'coze|7426720361732915216|小萌-女性', supportsEmotion: false },
    { label: '小飒-女性', value: 'coze|7426720361732915217|小飒-女性', supportsEmotion: false },
    { label: '小智-男性', value: 'coze|7426720361732915218|小智-男性', supportsEmotion: false }
  ]
};

// 当前TTS服务器的声音列表
const currentVoiceList = computed(() => {
  return voiceLists[form.ttsServer] || [];
});

// 过滤后的声音列表（支持搜索）
const filteredVoiceList = computed(() => {
  if (!searchKeyword.value) {
    return currentVoiceList.value;
  }
  const keyword = searchKeyword.value.toLowerCase();
  return currentVoiceList.value.filter(voice => 
    voice.label.toLowerCase().includes(keyword)
  );
});

// 检查当前选择的声音是否支持情感
const currentVoiceSupportsEmotion = computed(() => {
  if (form.ttsServer !== 'coze-tts') {
    return false;
  }
  const selectedVoice = currentVoiceList.value.find(voice => voice.value === form.speechSynthesis);
  return selectedVoice ? selectedVoice.supportsEmotion : false;
});

// 监听TTS服务器变化，重置声音选择
watch(() => form.ttsServer, (newServer) => {
  const voices = voiceLists[newServer] || [];
  form.speechSynthesis = voices.length > 0 ? voices[0].value : '';
  form.voiceEmotion = 'neutral';
});

// 监听声音变化，重置情感选择
watch(() => form.speechSynthesis, () => {
  if (!currentVoiceSupportsEmotion.value) {
    form.voiceEmotion = 'neutral';
  }
});

// 初始化默认声音
const initDefaultVoice = () => {
  const voices = voiceLists[form.ttsServer] || [];
  form.speechSynthesis = voices.length > 0 ? voices[0].value : '';
};

// 初始化
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