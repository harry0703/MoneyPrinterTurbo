import { defineStore } from 'pinia';
import { apiService } from '../services/api';

interface LLMConfig {
  apiKey: string;
  baseUrl: string;
  modelName: string;
}

interface LLMConfigs {
  [key: string]: LLMConfig;
  openai: LLMConfig;
  moonshot: LLMConfig;
  deepseek: LLMConfig;
}

interface AppSettings {
  llmProvider: string;
  videoSource: string;
  useGpu: boolean;
  hideConfig: boolean;
}

interface VideoSources {
  pexelsApiKeys: string[];
  pixabayApiKeys: string[];
}

interface WhisperSettings {
  device: string;
}

interface UISettings {
  language: string;
  hideLog: boolean;
}

interface VersionInfo {
  name: string;
  version: string;
}

export const useSettingsStore = defineStore('settings', {
  state: (): {
    app: AppSettings;
    llm: LLMConfigs;
    videoSources: VideoSources;
    whisper: WhisperSettings;
    ui: UISettings;
    version: VersionInfo | null;
  } => ({
    // Version information
    version: null,
    // App settings
    app: {
      llmProvider: 'openai',
      videoSource: 'pexels',
      useGpu: false,
      hideConfig: false
    },
    
    // LLM configuration
    llm: {
      openai: {
        apiKey: '',
        baseUrl: '',
        modelName: 'gpt-3.5-turbo'
      },
      moonshot: {
        apiKey: '',
        baseUrl: 'https://api.moonshot.cn/v1',
        modelName: 'moonshot-v1-8k'
      },
      deepseek: {
        apiKey: '',
        baseUrl: 'https://api.deepseek.com',
        modelName: 'deepseek-chat'
      }
    },
    
    // Video source configuration
    videoSources: {
      pexelsApiKeys: [],
      pixabayApiKeys: []
    },
    
    // Whisper configuration
    whisper: {
      device: 'CPU'
    },
    
    // UI configuration
    ui: {
      language: 'zh',
      hideLog: false
    }
  }),
  
  getters: {
    getLLMConfig: (state) => (provider: string) => {
      return state.llm[provider as keyof typeof state.llm] || {};
    },
    
    getVideoSourceConfig: (state) => (source: string) => {
      if (source === 'pexels') {
        return state.videoSources.pexelsApiKeys;
      } else if (source === 'pixabay') {
        return state.videoSources.pixabayApiKeys;
      }
      return [];
    }
  },
  
  actions: {
    updateAppSetting<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
      this.app[key] = value;
    },
    
    updateLLMSetting<P extends keyof LLMConfigs, K extends keyof LLMConfig>(provider: P, key: K, value: LLMConfig[K]) {
      if (this.llm[provider]) {
        this.llm[provider][key] = value;
      }
    },
    
    updateVideoSourceSetting(source: string, keys: string[]) {
      if (source === 'pexels') {
        this.videoSources.pexelsApiKeys = keys;
      } else if (source === 'pixabay') {
        this.videoSources.pixabayApiKeys = keys;
      }
    },
    
    updateWhisperSetting<K extends keyof WhisperSettings>(key: K, value: WhisperSettings[K]) {
      this.whisper[key] = value;
    },
    
    updateUISetting<K extends keyof UISettings>(key: K, value: UISettings[K]) {
      this.ui[key] = value;
    },
    
    loadFromLocalStorage() {
      const savedSettings = localStorage.getItem('moneyprinter-settings');
      if (savedSettings) {
        try {
          const parsed = JSON.parse(savedSettings);
          Object.assign(this, parsed);
        } catch (e) {
          console.error('Failed to load settings from localStorage:', e);
        }
      }
    },
    
    saveToLocalStorage() {
      localStorage.setItem('moneyprinter-settings', JSON.stringify(this));
    },
    
    async fetchVersion() {
      try {
        const versionInfo = await apiService.getVersion();
        this.version = {
          name: versionInfo.name || 'MoneyPrinterCN',
          version: versionInfo.version || '0.0.0'
        };
      } catch (error) {
        console.error('Failed to fetch version:', error);
        this.version = {
          name: 'MoneyPrinterCN',
          version: '0.0.0'
        };
      }
    },

    async fetchConfig() {
      try {
        console.log('Fetching config from backend...');
        const response = await apiService.getConfig();
        console.log('Config response:', response);
        if (response.status === 200 && response.data) {
          const data = response.data;
          console.log('Config data:', data);

          if (data.ui) {
            if (data.ui.language) {
              this.ui.language = data.ui.language;
              console.log('Updated language:', this.ui.language);
            }
            if (typeof data.ui.hide_log === 'boolean') {
              this.ui.hideLog = data.ui.hide_log;
              console.log('Updated hideLog:', this.ui.hideLog);
            }
          }

          if (data.app) {
            if (data.app.llm_provider) {
              this.app.llmProvider = data.app.llm_provider;
              console.log('Updated llmProvider:', this.app.llmProvider);
            }
            if (data.app.video_source) {
              this.app.videoSource = data.app.video_source;
              console.log('Updated videoSource:', this.app.videoSource);
            }
            if (typeof data.app.hide_config === 'boolean') {
              this.app.hideConfig = data.app.hide_config;
              console.log('Updated hideConfig:', this.app.hideConfig);
            }
            if (typeof data.app.use_gpu === 'boolean') {
              this.app.useGpu = data.app.use_gpu;
              console.log('Updated useGpu:', this.app.useGpu);
            }
            if (Array.isArray(data.app.pexels_api_keys)) {
              this.videoSources.pexelsApiKeys = data.app.pexels_api_keys;
              console.log('Updated pexelsApiKeys:', this.videoSources.pexelsApiKeys);
            }
            if (Array.isArray(data.app.pixabay_api_keys)) {
              this.videoSources.pixabayApiKeys = data.app.pixabay_api_keys;
              console.log('Updated pixabayApiKeys:', this.videoSources.pixabayApiKeys);
            }

            // Update LLM configs
            if (data.app.openai_api_key) {
              this.llm.openai = this.llm.openai || { apiKey: '', baseUrl: '', modelName: '' };
              this.llm.openai.apiKey = data.app.openai_api_key;
              if (data.app.openai_base_url) {
                this.llm.openai.baseUrl = data.app.openai_base_url;
              }
              if (data.app.openai_model_name) {
                this.llm.openai.modelName = data.app.openai_model_name;
              }
              console.log('Updated openai config:', this.llm.openai);
            }

            if (data.app.moonshot_api_key) {
              this.llm.moonshot = this.llm.moonshot || { apiKey: '', baseUrl: '', modelName: '' };
              this.llm.moonshot.apiKey = data.app.moonshot_api_key;
              if (data.app.moonshot_base_url) {
                this.llm.moonshot.baseUrl = data.app.moonshot_base_url;
              }
              if (data.app.moonshot_model_name) {
                this.llm.moonshot.modelName = data.app.moonshot_model_name;
              }
              console.log('Updated moonshot config:', this.llm.moonshot);
            }

            if (data.app.deepseek_api_key) {
              this.llm.deepseek = this.llm.deepseek || { apiKey: '', baseUrl: '', modelName: '' };
              this.llm.deepseek.apiKey = data.app.deepseek_api_key;
              if (data.app.deepseek_base_url) {
                this.llm.deepseek.baseUrl = data.app.deepseek_base_url;
              }
              if (data.app.deepseek_model_name) {
                this.llm.deepseek.modelName = data.app.deepseek_model_name;
              }
              console.log('Updated deepseek config:', this.llm.deepseek);
            }
          }

          if (data.whisper && data.whisper.device) {
            this.whisper.device = data.whisper.device;
            console.log('Updated whisper device:', this.whisper.device);
          }

          if (data.azure) {
            if (data.azure.speech_region) {
              this.llm.azure = this.llm.azure || { apiKey: '', baseUrl: '', modelName: '' };
              this.llm.azure.baseUrl = data.azure.speech_region;
            }
            if (data.azure.speech_key) {
              this.llm.azure = this.llm.azure || { apiKey: '', baseUrl: '', modelName: '' };
              this.llm.azure.apiKey = data.azure.speech_key;
            }
            console.log('Updated azure config:', this.llm.azure);
          }

          if (data.siliconflow && data.siliconflow.api_key) {
            this.llm.siliconflow = this.llm.siliconflow || { apiKey: '', baseUrl: '', modelName: '' };
            this.llm.siliconflow.apiKey = data.siliconflow.api_key;
            console.log('Updated siliconflow config:', this.llm.siliconflow);
          }

          if (data.coze && data.coze.api_key) {
            this.llm.coze = this.llm.coze || { apiKey: '', baseUrl: '', modelName: '' };
            this.llm.coze.apiKey = data.coze.api_key;
            console.log('Updated coze config:', this.llm.coze);
          }

          this.saveToLocalStorage();
          console.log('Config saved to localStorage');
        }
      } catch (error) {
        console.error('Failed to fetch config:', error);
      }
    }
  }
});