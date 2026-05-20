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

interface VideoSettings {
  source: string;
  concatMode: string;
  transitionMode: string;
  aspect: string;
  clipDuration: number;
  count: number;
  style: string;
  quality: string;
  bitrate: string;
  brightness: number;
  contrast: number;
  localFiles: Array<{ name: string; url?: string; status?: string; uid: string }>;
}

interface AudioSettings {
  ttsServer: string;
  speechSynthesis: string;
  speechRegion: string;
  speechKey: string;
  siliconflowApiKey: string;
  cozeApiKey: string;
  voiceEmotion: string;
  speechVolume: string;
  speechRate: string;
  backgroundMusic: string;
  backgroundMusicVolume: string;
}

interface SubtitleSettings {
  enable: boolean;
  font: string;
  position: string;
  customPosition: string;
  color: string;
  fontSize: number;
  outlineColor: string;
  outlineWidth: number;
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

type BackendStatus = 'unknown' | 'checking' | 'online' | 'offline';

export const useSettingsStore = defineStore('settings', {
  state: (): {
    app: AppSettings;
    llm: LLMConfigs;
    videoSources: VideoSources;
    whisper: WhisperSettings;
    ui: UISettings;
    video: VideoSettings;
    audio: AudioSettings;
    subtitle: SubtitleSettings;
    version: VersionInfo | null;
    backendStatus: BackendStatus;
    lastHealthCheck: number;
  } => ({
    // Version information
    version: null,
    // Backend health status
    backendStatus: 'unknown',
    lastHealthCheck: 0,
    // App settings
    app: {
      llmProvider: 'openai',
      videoSource: 'pexels',
      useGpu: false,
      hideConfig: false
    },
    
    // Video settings
    video: {
      source: 'pexels',
      concatMode: 'sequential',
      transitionMode: 'none',
      aspect: 'landscape',
      clipDuration: 3,
      count: 1,
      style: 'none',
      quality: 'ultra',
      bitrate: '20M',
      brightness: 1.0,
      contrast: 1.0,
      localFiles: []
    },
    
    // Audio settings
    audio: {
      ttsServer: 'azure-tts-v1',
      speechSynthesis: '',
      speechRegion: '',
      speechKey: '',
      siliconflowApiKey: '',
      cozeApiKey: '',
      voiceEmotion: '',
      speechVolume: '1.0',
      speechRate: '1.0',
      backgroundMusic: 'none',
      backgroundMusicVolume: '0.2'
    },
    
    // Subtitle settings
    subtitle: {
      enable: true,
      font: 'MicrosoftYaHeiBold.ttc',
      position: 'custom',
      customPosition: '80.0',
      color: '#FFFF00',
      fontSize: 60,
      outlineColor: '#000000',
      outlineWidth: 1.5
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
    
    updateVideoSetting<K extends keyof VideoSettings>(key: K, value: VideoSettings[K]) {
      this.video[key] = value;
      this.saveToLocalStorage();
    },
    
    updateAudioSetting<K extends keyof AudioSettings>(key: K, value: AudioSettings[K]) {
      this.audio[key] = value;
      this.saveToLocalStorage();
    },
    
    async updateSubtitleSetting<K extends keyof SubtitleSettings>(key: K, value: SubtitleSettings[K]) {
      this.subtitle[key] = value;
      this.saveToLocalStorage();
      await this.saveSubtitleToBackend();
    },
    
    async saveSubtitleToBackend() {
      console.log('[SettingsStore] Saving subtitle settings to backend...');
      try {
        const subtitleConfig = {
          ui: {
            subtitle_enabled: this.subtitle.enable,
            subtitle_position: this.subtitle.position,
            subtitle_custom_position: parseFloat(this.subtitle.customPosition) || 70.0,
            font_name: this.subtitle.font,
            text_fore_color: this.subtitle.color,
            font_size: this.subtitle.fontSize,
            stroke_color: this.subtitle.outlineColor,
            stroke_width: this.subtitle.outlineWidth,
          }
        };
        console.log('[SettingsStore] Sending config:', JSON.stringify(subtitleConfig, null, 2));
        const response = await apiService.updateConfig(subtitleConfig);
        console.log('[SettingsStore] Subtitle settings saved successfully:', response);
      } catch (error) {
        console.error('[SettingsStore] Failed to save subtitle settings to backend:', error);
        throw error;
      }
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
      const dataToSave = {
        app: this.app,
        llm: this.llm,
        videoSources: this.videoSources,
        whisper: this.whisper,
        ui: this.ui,
        video: this.video,
        audio: this.audio,
        subtitle: this.subtitle,
        version: this.version
      };
      localStorage.setItem('moneyprinter-settings', JSON.stringify(dataToSave));
    },

    async checkBackendHealth(): Promise<boolean> {
      this.backendStatus = 'checking';
      try {
        console.log('Checking backend health at:', new Date().toLocaleString());
        const response = await apiService.ping();
        console.log('Backend ping response:', response);
        this.backendStatus = 'online';
        this.lastHealthCheck = Date.now();
        console.log('Backend is online');
        return true;
      } catch (error: any) {
        console.error('Backend health check failed:', error);
        console.error('Error details:', {
          message: error.message,
          stack: error.stack,
          response: error.response,
          request: error.request,
          status: error.response?.status
        });
        this.backendStatus = 'offline';
        console.warn('Backend is offline');
        return false;
      }
    },

    async ensureBackendOnline(): Promise<boolean> {
      if (this.backendStatus === 'online') {
        return true;
      }
      return await this.checkBackendHealth();
    },
    
    async fetchVersion() {
      if (!(await this.ensureBackendOnline())) {
        console.warn('Backend is offline, skipping fetchVersion');
        return;
      }
      try {
        const versionInfo = await apiService.getVersion();
        this.version = {
          name: versionInfo.name || 'MoneyPrinterCN',
          version: versionInfo.version || '0.0.0'
        };
      } catch (error: any) {
        console.error('Failed to fetch version:', error);
        if (error.response?.status === 404) {
          this.backendStatus = 'offline';
        }
        this.version = {
          name: 'MoneyPrinterCN',
          version: '0.0.0'
        };
      }
    },

    async fetchConfig() {
      console.log('[SettingsStore] fetchConfig called');
      if (!(await this.ensureBackendOnline())) {
        console.warn('Backend is offline, skipping fetchConfig');
        return;
      }
      try {
        console.log('[SettingsStore] Fetching config from backend...');
        console.log('[SettingsStore] API Base URL:', 'http://localhost:8081/api/v1');
        const response = await apiService.getConfig();
        console.log('[SettingsStore] Config response status:', response.status);
        console.log('[SettingsStore] Config response data:', response.data);
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
            console.log('[SettingsStore] === Config UI Data ===');
            console.log('[SettingsStore] config.ui:', data.ui);
            
            if (data.ui.tts_server) {
              this.audio.ttsServer = data.ui.tts_server;
              console.log('[SettingsStore] Updated ttsServer from config.ui:', this.audio.ttsServer);
            } else {
              console.log('[SettingsStore] tts_server not found in config.ui');
            }
            if (data.ui.voice_name) {
              this.audio.speechSynthesis = data.ui.voice_name;
              console.log('[SettingsStore] Updated speechSynthesis from config.ui:', this.audio.speechSynthesis.substring(0, 100) + '...');
            } else {
              console.log('[SettingsStore] voice_name not found in config.ui');
            }
            if (data.ui.voice_volume !== undefined) {
              this.audio.speechVolume = String(data.ui.voice_volume);
              console.log('[SettingsStore] Updated speechVolume from config.ui:', this.audio.speechVolume);
            }
            if (data.ui.voice_rate !== undefined) {
              this.audio.speechRate = String(data.ui.voice_rate);
              console.log('[SettingsStore] Updated speechRate from config.ui:', this.audio.speechRate);
            }
            if (data.ui.bgm_type !== undefined) {
              const bgmType = data.ui.bgm_type === '' ? 'none' : data.ui.bgm_type;
              this.audio.backgroundMusic = bgmType;
              console.log('[SettingsStore] Updated backgroundMusic from config.ui:', this.audio.backgroundMusic);
            }
            if (data.ui.bgm_volume !== undefined) {
              this.audio.backgroundMusicVolume = String(data.ui.bgm_volume);
              console.log('[SettingsStore] Updated backgroundMusicVolume from config.ui:', this.audio.backgroundMusicVolume);
            }
            
            // Load subtitle settings from config.ui
            if (typeof data.ui.subtitle_enabled === 'boolean') {
              this.subtitle.enable = data.ui.subtitle_enabled;
              console.log('[SettingsStore] Updated subtitle.enable from config.ui:', this.subtitle.enable);
            }
            if (data.ui.subtitle_position) {
              this.subtitle.position = data.ui.subtitle_position;
              console.log('[SettingsStore] Updated subtitle.position from config.ui:', this.subtitle.position);
            }
            if (data.ui.subtitle_custom_position !== undefined) {
              this.subtitle.customPosition = String(data.ui.subtitle_custom_position);
              console.log('[SettingsStore] Updated subtitle.customPosition from config.ui:', this.subtitle.customPosition);
            }
            if (data.ui.subtitle_margin !== undefined) {
              console.log('[SettingsStore] subtitle_margin from config.ui:', data.ui.subtitle_margin);
            }
            if (data.ui.font_name) {
              this.subtitle.font = data.ui.font_name;
              console.log('[SettingsStore] Updated subtitle.font from config.ui:', this.subtitle.font);
            }
            if (data.ui.text_fore_color) {
              this.subtitle.color = data.ui.text_fore_color;
              console.log('[SettingsStore] Updated subtitle.color from config.ui:', this.subtitle.color);
            }
            if (typeof data.ui.text_background_color !== 'undefined') {
              console.log('[SettingsStore] text_background_color from config.ui:', data.ui.text_background_color);
            }
            if (data.ui.font_size !== undefined) {
              this.subtitle.fontSize = Number(data.ui.font_size);
              console.log('[SettingsStore] Updated subtitle.fontSize from config.ui:', this.subtitle.fontSize);
            }
            if (data.ui.stroke_color) {
              this.subtitle.outlineColor = data.ui.stroke_color;
              console.log('[SettingsStore] Updated subtitle.outlineColor from config.ui:', this.subtitle.outlineColor);
            }
            if (data.ui.stroke_width !== undefined) {
              this.subtitle.outlineWidth = Number(data.ui.stroke_width);
              console.log('[SettingsStore] Updated subtitle.outlineWidth from config.ui:', this.subtitle.outlineWidth);
            }
          }

          if (data.app) {
            if (data.app.llm_provider) {
              this.app.llmProvider = data.app.llm_provider;
              console.log('Updated llmProvider:', this.app.llmProvider);
            }
            if (data.app.video_source) {
              this.app.videoSource = data.app.video_source;
              this.video.source = data.app.video_source;
              console.log('Updated videoSource:', this.app.videoSource);
            }
            if (data.app.video_quality) {
              this.video.quality = data.app.video_quality;
              console.log('Updated video.quality:', this.video.quality);
            }
            if (data.app.video_bitrate) {
              this.video.bitrate = data.app.video_bitrate;
              console.log('Updated video.bitrate:', this.video.bitrate);
            }
            if (data.app.video_brightness !== undefined) {
              this.video.brightness = Number(data.app.video_brightness);
              console.log('Updated video.brightness:', this.video.brightness);
            }
            if (data.app.video_contrast !== undefined) {
              this.video.contrast = Number(data.app.video_contrast);
              console.log('Updated video.contrast:', this.video.contrast);
            }
            if (data.app.video_concat_mode) {
              this.video.concatMode = data.app.video_concat_mode;
              console.log('Updated video.concatMode:', this.video.concatMode);
            }
            if (data.app.video_transition_mode) {
              this.video.transitionMode = data.app.video_transition_mode;
              console.log('Updated video.transitionMode:', this.video.transitionMode);
            }
            if (data.app.video_aspect) {
              this.video.aspect = data.app.video_aspect;
              console.log('Updated video.aspect:', this.video.aspect);
            }
            if (data.app.video_clip_duration !== undefined) {
              this.video.clipDuration = Number(data.app.video_clip_duration);
              console.log('Updated video.clipDuration:', this.video.clipDuration);
            }
            if (data.app.video_count !== undefined) {
              this.video.count = Number(data.app.video_count);
              console.log('Updated video.count:', this.video.count);
            }
            if (data.app.video_style) {
              this.video.style = data.app.video_style;
              console.log('Updated video.style:', this.video.style);
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
        } else {
          console.error('Invalid config response:', response);
        }
      } catch (error: any) {
        console.error('Failed to fetch config:', error);
        console.error('Error details:', error.message);
        if (error.response) {
          console.error('Error response:', error.response);
        } else if (error.request) {
          console.error('Error request:', error.request);
        }
      }
    }
  }
});