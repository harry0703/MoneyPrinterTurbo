import { defineStore } from 'pinia';

interface Scene {
  id: string;
  title: string;
  duration: number;
  visual_requirement: string;
  keywords: string;
  script: string;
  introVideo?: string;
  introVideoOriginalPath?: string;
  introVideoDuration?: number;
}

interface ScriptSettings {
  videoSubject: string;
  videoScript: string;
  language: string;
  videoTitle: string;
  scenes: Scene[];
}

export const useScriptStore = defineStore('script', {
  state: (): ScriptSettings => ({
    videoSubject: '',
    videoScript: '',
    language: 'auto',
    videoTitle: '',
    scenes: []
  }),
  
  actions: {
    updateVideoSubject(value: string) {
      this.videoSubject = value;
      this.saveToLocalStorage();
    },
    
    updateVideoScript(value: string) {
      this.videoScript = value;
      this.saveToLocalStorage();
    },
    
    updateLanguage(value: string) {
      this.language = value;
      this.saveToLocalStorage();
    },
    
    updateVideoTitle(value: string) {
      this.videoTitle = value;
      this.saveToLocalStorage();
    },
    
    updateScenes(value: Scene[]) {
      this.scenes = value;
      this.saveToLocalStorage();
    },
    
    addScene(scene: Scene) {
      this.scenes.push(scene);
      this.saveToLocalStorage();
    },
    
    removeScene(index: number) {
      this.scenes.splice(index, 1);
      this.saveToLocalStorage();
    },
    
    updateScene(index: number, scene: Scene) {
      this.scenes[index] = scene;
      this.saveToLocalStorage();
    },
    
    loadFromLocalStorage() {
      const savedScript = localStorage.getItem('moneyprinter-script');
      if (savedScript) {
        try {
          const parsed = JSON.parse(savedScript);
          Object.assign(this, parsed);
        } catch (e) {
          console.error('Failed to load script from localStorage:', e);
        }
      }
    },
    
    saveToLocalStorage() {
      const data = {
        videoSubject: this.videoSubject,
        videoScript: this.videoScript,
        language: this.language,
        videoTitle: this.videoTitle,
        scenes: JSON.parse(JSON.stringify(this.scenes))
      };
      localStorage.setItem('coiner-script', JSON.stringify(data));
    }
  }
});
