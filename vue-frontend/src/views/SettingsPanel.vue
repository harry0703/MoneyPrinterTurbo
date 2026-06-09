<template>
  <div class="settings-panel">
    <el-dialog
      v-model="visible"
      :title="t('Settings')"
      width="800px"
      destroy-on-close
    >
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span v-html="t('LLM Settings')"></span>
        </template>
        
        <el-form :model="form" label-width="150px">
          <el-form-item :label="t('LLM Provider')">
            <el-select v-model="form.llmProvider" @change="handleLLMProviderChange">
              <el-option v-for="provider in llmProviders" :key="provider.value" :label="provider.label" :value="provider.value" />
            </el-select>
          </el-form-item>
        </el-form>
        
        <el-alert
          :title="t('LLM Provider Recommendation')"
          type="info"
          :closable="false"
          show-icon
          class="mb-4"
        >
          <p v-html="t('LLM Provider Recommendation Content')"></p>
        </el-alert>
        
        <div v-if="llmTips" class="llm-tips">
          <el-alert
            :title="llmTips.title"
            :type="llmTips.type"
            :closable="false"
            show-icon
          >
            <div v-html="llmTips.content"></div>
          </el-alert>
        </div>
        
        <el-form :model="form" label-width="150px">
          
          <el-form-item>
            <template #label>
              <span>{{ t('API Key') }} <span style="color: red;">*</span></span>
            </template>
            <el-input v-model="form.llmApiKey" type="password" />
          </el-form-item>
          
          <el-form-item :label="t('Base Url')">
            <el-input v-model="form.llmBaseUrl" />
          </el-form-item>
          
          <el-form-item v-if="form.llmProvider !== 'ernie'">
            <template #label>
              <el-tooltip :content="t('Model Name Tooltip')" placement="top">
                <span>{{ t('Model Name') }}</span>
              </el-tooltip>
            </template>
            <el-input v-model="form.llmModelName" />
          </el-form-item>
          
          <el-form-item :label="t('Secret Key')" v-if="form.llmProvider === 'ernie'">
            <el-input v-model="form.llmSecretKey" type="password" />
          </el-form-item>
          
          <el-form-item :label="t('Account ID')" v-if="form.llmProvider === 'cloudflare'">
            <el-input v-model="form.llmAccountId" />
          </el-form-item>
        </el-form>
      </el-card>
      
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span v-html="t('Video Source Settings')"></span>
        </template>
        
        <el-form :model="form" label-position="top">
          <el-form-item>
            <template #label>
              <span v-html="t('Pexels API Key')"></span>
            </template>
            <div v-for="(_, index) in form.pexelsApiKeys" :key="index" class="api-key-input-group">
              <el-input v-model="form.pexelsApiKeys[index]" type="password">
                <template #append>
                  <el-button 
                    v-if="form.pexelsApiKeys.length > 1" 
                    type="danger" 
                    circle 
                    @click="removePexelsApiKey(index)"
                  >
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </template>
              </el-input>
            </div>
            <el-button type="primary" plain @click="addPexelsApiKey" class="mt-2">
              <el-icon><Plus /></el-icon>
              {{ t('Add') }}
            </el-button>
          </el-form-item>
          
          <el-form-item>
            <template #label>
              <span v-html="t('Pixabay API Key')"></span>
            </template>
            <div v-for="(_, index) in form.pixabayApiKeys" :key="index" class="api-key-input-group">
              <el-input v-model="form.pixabayApiKeys[index]" type="password">
                <template #append>
                  <el-button 
                    v-if="form.pixabayApiKeys.length > 1" 
                    type="danger" 
                    circle 
                    @click="removePixabayApiKey(index)"
                  >
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </template>
              </el-input>
            </div>
            <el-button type="primary" plain @click="addPixabayApiKey" class="mt-2">
              <el-icon><Plus /></el-icon>
              {{ t('Add') }}
            </el-button>
          </el-form-item>
        </el-form>
      </el-card>
      
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span v-html="t('Whisper Settings')"></span>
        </template>
        
        <el-form :model="form" label-width="150px">
          <el-form-item :label="t('Whisper Device')">
            <el-select v-model="form.whisperDevice">
              <el-option :label="t('CPU')" value="CPU" />
              <el-option :label="t('GPU')" value="GPU" />
              <el-option :label="t('Auto')" value="auto" />
            </el-select>
          </el-form-item>
        </el-form>
      </el-card>
      
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span v-html="t('Video Encoder Settings')"></span>
        </template>
        
        <el-form :model="form" label-width="150px">
          <el-form-item :label="t('Video Encoder')">
            <el-select v-model="form.videoEncoder">
              <el-option :label="t('CPU')" value="CPU" />
              <el-option :label="t('GPU')" value="GPU" />
            </el-select>
          </el-form-item>
        </el-form>
      </el-card>
      
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span v-html="t('Video Synthesis')"></span>
        </template>
        
        <el-form :model="form" label-width="150px">
          <el-form-item :label="t('Silence Prefix')">
            <el-slider
              v-model="form.silenceDuration"
              :min="0.0"
              :max="5.0"
              :step="0.1"
              :show-input="true"
              :input-size="'small'"
            />
          </el-form-item>
          
          <el-form-item :label="t('Host Visible')">
            <el-switch v-model="form.hostVisible" :active-text="t('Visible')" :inactive-text="t('Hidden')" />
          </el-form-item>
        </el-form>
      </el-card>
      
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span v-html="t('Cloned Voices Setting')"></span>
        </template>
        
        <div class="voice-actions mt-4">
          <el-button 
            type="primary" 
            plain 
            size="small" 
            @click="showAddVoiceModal = true"
          >
            <el-icon><Plus /></el-icon>
            {{ t('Add Voice') }}
          </el-button>
          <label class="el-button el-button--success el-button--plain el-button--small ml-2">
            <el-icon><Upload /></el-icon>
            {{ t('Import JSON') }}
            <input 
              type="file" 
              accept=".json" 
              class="voice-file-upload"
              @change="handleFileUpload"
            />
          </label>
        </div>
        
        <div v-if="clonedVoices.length === 0" class="empty-state">
          <el-empty 
            description="No cloned voices configured. Click 'Add Voice' or 'Import JSON' to add."
          />
        </div>
        
        <el-table 
          v-else 
          :data="clonedVoices" 
          border 
          class="mt-4"
          :max-height="300"
        >
          <el-table-column label="Display Name" prop="displayName" />
          <el-table-column label="Voice ID" prop="voiceId" width="300" />
          <el-table-column label="Gender" prop="gender" />
          <el-table-column label="Model" prop="model" width="200" />
          <el-table-column label="Actions" width="120">
            <template #default="scope">
              <el-button 
                size="small" 
                @click="editVoice(scope.row)"
              >
                <el-icon><Edit /></el-icon>
              </el-button>
              <el-button 
                size="small" 
                type="danger" 
                @click="deleteVoice(scope.row.voiceId)"
              >
                <el-icon><Delete /></el-icon>
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
      
      <!-- Add/Edit Voice Modal -->
      <el-dialog 
        v-model="showAddVoiceModal" 
        :title="editingVoice ? t('Edit Voice') : t('Add Cloned Voice')"
        width="500px"
      >
        <el-form :model="voiceForm" label-width="120px">
          <el-form-item :label="t('Display Name')" required>
            <el-input v-model="voiceForm.displayName" />
          </el-form-item>
          <el-form-item :label="t('Voice ID')" required>
            <el-input v-model="voiceForm.voiceId" placeholder="e.g., qwen-tts-vc-xxx" />
          </el-form-item>
          <el-form-item :label="t('Gender')">
            <el-select v-model="voiceForm.gender">
              <el-option label="Male" value="Male" />
              <el-option label="Female" value="Female" />
              <el-option label="Unknown" value="" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('Model')" required>
            <el-input v-model="voiceForm.model" placeholder="e.g., qwen3-tts-vc-2026-01-22" />
          </el-form-item>
          <el-form-item :label="t('Brief')">
            <el-input v-model="voiceForm.brief" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item :label="t('Provider')">
            <el-input v-model="voiceForm.provider" />
          </el-form-item>
          <el-form-item :label="t('Region')">
            <el-input v-model="voiceForm.region" />
          </el-form-item>
        </el-form>
        
        <template #footer>
          <el-button @click="showAddVoiceModal = false">{{ t('Cancel') }}</el-button>
          <el-button type="primary" @click="saveVoice">{{ t('Save') }}</el-button>
        </template>
      </el-dialog>
      
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="visible = false">{{ t('Cancel') }}</el-button>
          <el-button type="primary" @click="saveSettings">{{ t('Save') }}</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, onMounted, watch } from 'vue';
import { useSettingsStore } from '../stores/settings';
import { useI18nStore } from '../stores/i18n';
import { Delete, Plus, Edit, Upload } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import { apiService } from '../services/api';

const props = defineProps<{
  visible: boolean;
}>();

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void;
  (e: 'settings-saved'): void;
}>();

const visible = computed({
  get: () => props.visible,
  set: (value) => emit('update:visible', value)
});

const i18nStore = useI18nStore();
const t = i18nStore.t;

const settingsStore = useSettingsStore();

// Load settings into form
const loadSettingsToForm = () => {
  form.llmProvider = settingsStore.app.llmProvider;
  
  // Load LLM configuration
  const llmConfig = settingsStore.getLLMConfig(form.llmProvider);
  form.llmApiKey = llmConfig.apiKey || '';
  form.llmBaseUrl = llmConfig.baseUrl || '';
  form.llmModelName = llmConfig.modelName || '';
  
  // Load video source configuration
  const pexelsKeys = settingsStore.getVideoSourceConfig('pexels');
  form.pexelsApiKeys = pexelsKeys.length > 0 ? pexelsKeys : [''];
  
  const pixabayKeys = settingsStore.getVideoSourceConfig('pixabay');
  form.pixabayApiKeys = pixabayKeys.length > 0 ? pixabayKeys : [''];
  
  // Load Whisper configuration
  form.whisperDevice = settingsStore.whisper.device || 'CPU';
  
  // Load video encoder configuration
  form.videoEncoder = settingsStore.app.useGpu ? 'GPU' : 'CPU';
  
  // Load Silence Prefix configuration
  form.silenceDuration = settingsStore.video.silenceDuration;
  
  // Load Host Visible configuration
  form.hostVisible = settingsStore.video.hostVisible;
};

const form = reactive({
  llmProvider: 'openai',
  llmApiKey: '',
  llmBaseUrl: '',
  llmModelName: '',
  llmSecretKey: '',
  llmAccountId: '',
  pexelsApiKeys: [''],
  pixabayApiKeys: [''],
  whisperDevice: 'CPU',
  videoEncoder: 'CPU',
  silenceDuration: 0.3,
  hostVisible: true
});

// Cloned voices data
const clonedVoices = reactive<Array<{
  voiceId: string;
  displayName: string;
  gender: string;
  model: string;
  brief?: string;
  provider?: string;
  region?: string;
}>>([]);

const showAddVoiceModal = ref(false);
const editingVoice = ref<typeof clonedVoices[0] | null>(null);

const voiceForm = reactive({
  voiceId: '',
  displayName: '',
  gender: '',
  model: '',
  brief: '',
  provider: '',
  region: ''
});

// Cloned voices methods
const loadClonedVoices = async () => {
  try {
    const response = await apiService.getClonedVoices();
    if (response.data && response.data.voices) {
      clonedVoices.splice(0, clonedVoices.length, ...response.data.voices);
    }
  } catch (error) {
    console.error('Failed to load cloned voices:', error);
  }
};

const editVoice = (voice: typeof clonedVoices[0]) => {
  editingVoice.value = voice;
  voiceForm.voiceId = voice.voiceId;
  voiceForm.displayName = voice.displayName;
  voiceForm.gender = voice.gender || '';
  voiceForm.model = voice.model;
  voiceForm.brief = voice.brief || '';
  voiceForm.provider = voice.provider || '';
  voiceForm.region = voice.region || '';
  showAddVoiceModal.value = true;
};

const saveVoice = async () => {
  if (!voiceForm.voiceId || !voiceForm.displayName || !voiceForm.model) {
    ElMessage.error('Voice ID, Display Name, and Model are required');
    return;
  }
  
  try {
    const voiceData = {
      voiceId: voiceForm.voiceId,
      displayName: voiceForm.displayName,
      gender: voiceForm.gender,
      model: voiceForm.model,
      brief: voiceForm.brief,
      provider: voiceForm.provider,
      region: voiceForm.region
    };
    
    const response = await apiService.saveClonedVoice(voiceData);
    if (response.data && response.data.voices) {
      clonedVoices.splice(0, clonedVoices.length, ...response.data.voices);
    }
    
    ElMessage.success(editingVoice.value ? 'Voice updated successfully' : 'Voice added successfully');
    showAddVoiceModal.value = false;
    editingVoice.value = null;
    resetVoiceForm();
  } catch (error: any) {
    console.error('Failed to save voice:', error);
    ElMessage.error('Failed to save voice: ' + (error?.message || 'Unknown error'));
  }
};

const deleteVoice = async (voiceId: string) => {
  try {
    const response = await apiService.deleteClonedVoice(voiceId);
    if (response.data && response.data.voices) {
      clonedVoices.splice(0, clonedVoices.length, ...response.data.voices);
    }
    ElMessage.success('Voice deleted successfully');
  } catch (error: any) {
    console.error('Failed to delete voice:', error);
    ElMessage.error('Failed to delete voice: ' + (error?.message || 'Unknown error'));
  }
};

const handleFileUpload = async (event: Event) => {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  
  if (!file) {
    return;
  }
  
  if (!file.name.endsWith('.json')) {
    ElMessage.error('Please select a JSON file');
    target.value = '';
    return;
  }
  
  try {
    const reader = new FileReader();
    
    reader.onload = async (e) => {
      try {
        const jsonData = e.target?.result as string;
        const response = await apiService.importClonedVoices(jsonData);
        
        if (response.data && response.data.voices) {
          clonedVoices.splice(0, clonedVoices.length, ...response.data.voices);
        }
        
        ElMessage.success('Voices imported successfully');
      } catch (error: any) {
        console.error('Failed to import voices:', error);
        ElMessage.error('Failed to import voices: ' + (error?.message || 'Unknown error'));
      }
    };
    
    reader.onerror = () => {
      ElMessage.error('Failed to read file');
    };
    
    reader.readAsText(file);
  } catch (error: any) {
    console.error('Failed to handle file:', error);
    ElMessage.error('Failed to process file: ' + (error?.message || 'Unknown error'));
  }
  
  target.value = '';
};

const resetVoiceForm = () => {
  voiceForm.voiceId = '';
  voiceForm.displayName = '';
  voiceForm.gender = '';
  voiceForm.model = '';
  voiceForm.brief = '';
  voiceForm.provider = '';
  voiceForm.region = '';
};

// API Key management methods
const addPexelsApiKey = () => {
  form.pexelsApiKeys.push('');
};

const removePexelsApiKey = (index: number) => {
  if (form.pexelsApiKeys.length > 1) {
    form.pexelsApiKeys.splice(index, 1);
  }
};

const addPixabayApiKey = () => {
  form.pixabayApiKeys.push('');
};

const removePixabayApiKey = (index: number) => {
  if (form.pixabayApiKeys.length > 1) {
    form.pixabayApiKeys.splice(index, 1);
  }
};

const llmProviders = [
  { label: 'OpenAI', value: 'openai' },
  { label: 'Moonshot', value: 'moonshot' },
  { label: 'Azure', value: 'azure' },
  { label: 'Qwen', value: 'qwen' },
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'ModelScope', value: 'modelscope' },
  { label: 'Gemini', value: 'gemini' },
  { label: 'Ollama', value: 'ollama' },
  { label: 'G4f', value: 'g4f' },
  { label: 'OneAPI', value: 'oneapi' },
  { label: 'Cloudflare', value: 'cloudflare' },
  { label: 'ERNIE', value: 'ernie' },
  { label: 'Pollinations', value: 'pollinations' }
];

const llmTips = computed(() => {
  const provider = form.llmProvider;
  let title = '';
  let content = '';
  
  switch (provider) {
    case 'deepseek':
      title = t('DeepSeek Configuration');
      content = `
        <p>${t('API Key')}: ${t('DeepSeek API Key Tip').replace('API Key: ', '')}</p>
        <p>${t('Base Url')}: ${t('DeepSeek Base Url Tip').replace('Base Url: ', '')}</p>
        <p>${t('Model Name')}: ${t('DeepSeek Model Name Tip').replace('Model Name: ', '')}</p>
      `;
      break;
    case 'moonshot':
      title = t('Moonshot Configuration');
      content = `
        <p>${t('API Key')}: ${t('Moonshot API Key Tip').replace('API Key: ', '')}</p>
        <p>${t('Base Url')}: ${t('Moonshot Base Url Tip').replace('Base Url: ', '')}</p>
        <p>${t('Model Name')}: ${t('Moonshot Model Name Tip').replace('Model Name: ', '')}</p>
      `;
      break;
    case 'openai':
      title = t('OpenAI Configuration');
      content = `
        <p>${t('OpenAI VPN Tip')}</p>
        <p>${t('API Key')}: ${t('OpenAI API Key Tip').replace('API Key: ', '')}</p>
        <p>${t('Base Url')}: ${t('OpenAI Base Url Tip').replace('Base Url: ', '')}</p>
        <p>${t('Model Name')}: ${t('OpenAI Model Name Tip').replace('Model Name: ', '')}</p>
      `;
      break;
    case 'ollama':
      title = t('Ollama Configuration');
      content = `
        <p>${t('API Key')}: ${t('Ollama API Key Tip').replace('API Key: ', '')}</p>
        <p>${t('Base Url')}: ${t('Ollama Base Url Tip').replace('Base Url: ', '')}</p>
        <p>- ${t('Ollama Base Url Tip 2')}</p>
        <p>- ${t('Ollama Base Url Tip 3')}</p>
        <p>${t('Model Name')}: ${t('Ollama Model Name Tip').replace('Model Name: ', '')}</p>
      `;
      break;
    default:
      title = t('LLM Configuration');
      content = `
        <p>${t('API Key')}: ${t('Please Enter LLM API Key')}</p>
        <p>${t('Base Url')}: ${t('Base Url Tooltip')}</p>
        <p>${t('Model Name')}: ${t('Model Name Tooltip')}</p>
      `;
  }
  
  return {
    title: title,
    type: 'info',
    content: content
  };
});

const handleLLMProviderChange = () => {
  // Set default values based on selected LLM provider
  const provider = form.llmProvider;
  
  switch (provider) {
    case 'ollama':
      form.llmModelName = 'qwen:7b';
      form.llmBaseUrl = 'http://localhost:11434/v1';
      break;
    case 'openai':
      form.llmModelName = 'gpt-3.5-turbo';
      form.llmBaseUrl = '';
      break;
    case 'moonshot':
      form.llmModelName = 'moonshot-v1-8k';
      form.llmBaseUrl = 'https://api.moonshot.cn/v1';
      break;
    case 'deepseek':
      form.llmModelName = 'deepseek-chat';
      form.llmBaseUrl = 'https://api.deepseek.com';
      break;
    case 'qwen':
      form.llmModelName = 'qwen-max';
      form.llmBaseUrl = '';
      break;
    case 'gemini':
      form.llmModelName = 'gemini-1.0-pro';
      form.llmBaseUrl = '';
      break;
    case 'modelscope':
      form.llmModelName = 'Qwen/Qwen3-32B';
      form.llmBaseUrl = 'https://api-inference.modelscope.cn/v1/';
      break;
    case 'g4f':
      form.llmModelName = 'gpt-3.5-turbo';
      form.llmBaseUrl = '';
      break;
    case 'oneapi':
      form.llmModelName = 'claude-3-5-sonnet-20240620';
      form.llmBaseUrl = '';
      break;
    default:
      form.llmModelName = '';
      form.llmBaseUrl = '';
  }
};

const saveSettings = async () => {
  try {
    // Save settings to state management
    settingsStore.updateAppSetting('llmProvider', form.llmProvider);

    // Save LLM configuration
    settingsStore.updateLLMSetting(form.llmProvider, 'apiKey', form.llmApiKey);
    settingsStore.updateLLMSetting(form.llmProvider, 'baseUrl', form.llmBaseUrl);
    if (form.llmProvider !== 'ernie') {
      settingsStore.updateLLMSetting(form.llmProvider, 'modelName', form.llmModelName);
    }

    // Save video source configuration
    const pexelsKeys = form.pexelsApiKeys.map(key => key.trim()).filter(Boolean);
    const pixabayKeys = form.pixabayApiKeys.map(key => key.trim()).filter(Boolean);
    settingsStore.updateVideoSourceSetting('pexels', pexelsKeys);
    settingsStore.updateVideoSourceSetting('pixabay', pixabayKeys);

    // Save Whisper configuration
    settingsStore.updateWhisperSetting('device', form.whisperDevice);

    // Save video encoder configuration
    settingsStore.updateAppSetting('useGpu', form.videoEncoder === 'GPU');
    
    // Save Silence Prefix configuration
    settingsStore.updateVideoSetting('silenceDuration', form.silenceDuration);
    
    // Save Host Visible configuration
    settingsStore.updateVideoSetting('hostVisible', form.hostVisible);

    // Build app config based on LLM provider
    const appConfig: Record<string, any> = {
      llm_provider: form.llmProvider,
      use_gpu: form.videoEncoder === 'GPU',
      pexels_api_keys: pexelsKeys,
      pixabay_api_keys: pixabayKeys,
      silence_duration: form.silenceDuration,
      host_visible: form.hostVisible
    };

    // Add LLM specific configs based on provider
    switch (form.llmProvider) {
      case 'openai':
        appConfig.openai_api_key = form.llmApiKey;
        appConfig.openai_base_url = form.llmBaseUrl;
        appConfig.openai_model_name = form.llmModelName;
        break;
      case 'moonshot':
        appConfig.moonshot_api_key = form.llmApiKey;
        appConfig.moonshot_base_url = form.llmBaseUrl;
        appConfig.moonshot_model_name = form.llmModelName;
        break;
      case 'deepseek':
        appConfig.deepseek_api_key = form.llmApiKey;
        appConfig.deepseek_base_url = form.llmBaseUrl;
        appConfig.deepseek_model_name = form.llmModelName;
        break;
    }

    // Prepare config object to send to backend - create plain object to avoid circular references
    const configToSave = JSON.parse(JSON.stringify({
      app: appConfig,
      whisper: {
        device: form.whisperDevice
      }
    }));

    // Send config to backend
    const response = await apiService.updateConfig(configToSave);
    console.log('[saveSettings] Response:', response.status, response.data);

    // Save to local storage
    settingsStore.saveToLocalStorage();

    // Show success message
    ElMessage.success(t('Settings saved successfully'));

    // Close dialog
    visible.value = false;

    // Trigger settings saved event
    emit('settings-saved');
  } catch (error: any) {
    console.error('Failed to save settings:', error?.message || error);
    ElMessage.error(t('Failed to save settings') + ': ' + (error?.message || 'Unknown error'));
  }
};

// Watch for dialog opening to reload the form
watch(() => props.visible, async (newValue) => {
  if (newValue) {
    try {
      await settingsStore.fetchConfig();
      loadSettingsToForm();
      await loadClonedVoices();
    } catch (error) {
      console.error('Failed to load settings:', error);
    }
  }
});

onMounted(async () => {
  try {
    await settingsStore.fetchConfig();
    loadSettingsToForm();
    await loadClonedVoices();
  } catch (error) {
    console.error('Failed to load settings:', error);
  }
});
</script>

<style scoped>
.settings-panel {
  width: 100%;
}

.mt-4 {
  margin-top: 16px;
}

.llm-tips {
  margin-top: 16px;
}

.dialog-footer {
  width: 100%;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.api-key-input-group {
  margin-bottom: 12px;
  width: 100%;
}

.api-key-input-group:last-of-type {
  margin-bottom: 12px;
}

.api-key-input-group .el-input {
  width: 100%;
}

/* Style for input fields to match ui-setting.png */
.el-input__inner {
  background-color: #f5f5f5;
  border-color: #d9d9d9;
}

/* Style for LLM tips to match the blue box background */
.llm-tips {
  margin: 16px 0;
}

.llm-tips .el-alert {
  background-color: #e6f7ff;
  border-color: #91d5ff;
  border-radius: 4px;
}

/* Style for LLM provider recommendation to match the yellow box background */
.mb-4 {
  background-color: #fff7e6;
  border-color: #ffd591;
  border-radius: 4px;
}

.mt-2 {
  margin-top: 8px;
}

.voice-file-upload {
  display: none;
}

.voice-actions {
  display: flex;
  gap: 8px;
}
</style>