import json
import os
from typing import Dict, List, Optional, Any

class ClonedVoicesConfig:
    """Handles cloned voices configuration stored in a separate JSON file."""
    
    def __init__(self, file_path: str = None):
        self.file_path = file_path or os.path.join(os.path.dirname(__file__), '..', '..', 'cloned_voices.json')
        self.data: Dict[str, Dict[str, List[dict]]] = {}
        self.load()
    
    def load(self):
        """Load cloned voices from JSON file."""
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
            else:
                self.data = {}
        except Exception as e:
            print(f"Error loading cloned voices config: {e}")
            self.data = {}
    
    def save(self):
        """Save cloned voices to JSON file."""
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving cloned voices config: {e}")
    
    def get_voices(self, provider: str = None, model: str = None) -> List[dict]:
        """
        Get cloned voices filtered by provider and/or model.
        
        Args:
            provider: Filter by provider (e.g., "qwen", "cosyvoice")
            model: Filter by model (e.g., "qwen3-tts-vc-2026-01-22")
        
        Returns:
            List of voice dictionaries
        """
        voices = []
        
        if provider:
            if provider in self.data:
                if model:
                    if model in self.data[provider]:
                        voices.extend(self.data[provider][model])
                else:
                    for model_voices in self.data[provider].values():
                        voices.extend(model_voices)
        else:
            for provider_data in self.data.values():
                for model_voices in provider_data.values():
                    voices.extend(model_voices)
        
        return voices
    
    def add_voice(self, voice_data: dict):
        """
        Add or update a cloned voice.
        
        Args:
            voice_data: Dictionary containing voice information
                Must include: voiceId, displayName, model, provider
        """
        provider = voice_data.get('provider', 'unknown').lower()
        model = voice_data.get('model', 'unknown')
        
        if provider not in self.data:
            self.data[provider] = {}
        
        if model not in self.data[provider]:
            self.data[provider][model] = []
        
        existing_index = next(
            (i for i, v in enumerate(self.data[provider][model]) 
             if v.get('voiceId') == voice_data.get('voiceId')), 
            None
        )
        
        if existing_index is not None:
            self.data[provider][model][existing_index] = voice_data
        else:
            self.data[provider][model].append(voice_data)
        
        self.save()
    
    def delete_voice(self, voice_id: str) -> bool:
        """
        Delete a cloned voice by voiceId.
        
        Returns:
            True if voice was deleted, False otherwise
        """
        for provider in self.data.values():
            for model_voices in provider.values():
                for i, voice in enumerate(model_voices):
                    if voice.get('voiceId') == voice_id:
                        del model_voices[i]
                        self.save()
                        return True
        
        return False
    
    def import_voices(self, voices_data: List[dict]):
        """
        Import multiple voices from a list.
        
        Args:
            voices_data: List of voice dictionaries
        """
        for voice_data in voices_data:
            self.add_voice(voice_data)
    
    def get_providers(self) -> List[str]:
        """Get list of available providers."""
        return list(self.data.keys())
    
    def get_models(self, provider: str) -> List[str]:
        """Get list of models for a specific provider."""
        return list(self.data.get(provider, {}).keys())

cloned_voices_config = ClonedVoicesConfig()