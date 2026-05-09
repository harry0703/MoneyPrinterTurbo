import { defineStore } from 'pinia';

interface Scene {
  id: string;
  duration: number;
  visual_requirement: string;
  keywords: string;
  script: string;
  introVideo?: string;
  introVideoDuration?: number;
}

interface ScriptSettings {
  videoSubject: string;
  videoScript: string;
  language: string;
  scenes: Scene[];
}

export const useScriptStore = defineStore('script', {
  state: (): ScriptSettings => ({
    videoSubject: '',
    videoScript: '',
    language: 'auto',
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
        scenes: JSON.parse(JSON.stringify(this.scenes))
      };
      localStorage.setItem('moneyprinter-script', JSON.stringify(data));
    }
  }
});
