# Coze TTS Service Integration Report

## 1. Integration Overview

This report documents the integration of Coze TTS service into the Coiner project. Coze TTS is now available as a new voice provider alongside existing TTS services (Azure TTS V1/V2, SiliconFlow TTS, and Google Gemini TTS).

## 2. Changes Made

### 2.1 Voice Service Implementation

**File: `app/services/voice.py`**
- Added `get_coze_voices()` function to retrieve available Coze voices from API
- Added `is_coze_voice()` function to detect Coze voice format
- Added `coze_tts()` function to implement Coze TTS synthesis
- Updated main `tts()` dispatcher to handle Coze voices

### 2.2 Configuration Updates

**File: `app/config/config.py`**
- Added `coze` configuration section
- Updated `save_config()` function to include Coze settings

**File: `config.example.toml`**
- Added `[coze]` section with API key field

### 2.3 UI Integration

**File: `webui/Main.py`**
- Added "Coze TTS" to TTS server selection options
- Added Coze voice loading logic
- Added Coze API key input field in UI
- Added Coze TTS settings information

## 3. Coze TTS Features

### 3.1 Supported Voices

Coze TTS provides 10 voices with different genders and characteristics:

| Voice ID | Voice Name | Gender | Description |
|----------|------------|--------|-------------|
| 7426720361732915209 | xiaoyi   | Female | Standard female voice |
| 7426720361732915210 | daming   | Male   | Standard male voice |
| 7426720361732915211 | lili     | Female | Gentle female voice |
| 7426720361732915212 | zhiwei   | Male   | Professional male voice |
| 7426720361732915213 | nana     | Female | Sweet female voice |
| 7426720361732915214 | erica    | Female | English female voice |
| 7426720361732915215 | david    | Male   | English male voice |
| 7426720361732915216 | sophie   | Female | Elegant female voice |
| 7426720361732915217 | leo      | Male   | Energetic male voice |
| 7426720361732915218 | luna     | Female | Soft female voice |

### 3.2 Voice Naming Convention

Coze voices follow the format: `coze:voice_id:voice_name-gender`

Example: `coze:7426720361732915209:xiaoyi-Female`

The voice_id is a numeric identifier used for API calls, while voice_name is a human-readable name for display purposes.

### 3.3 Configuration Requirements

- **API Key**: Required from Coze platform
- **Voice List Endpoint**: `https://api.coze.cn/v1/audio/voices`
- **Speech Synthesis Endpoint**: `https://api.coze.cn/v1/audio/speech`
- **Authentication**: Bearer token in Authorization header

### 3.4 Parameters

- **text**: Text to synthesize
- **voice**: Voice ID (e.g., "xiaoyi")
- **speed**: Voice rate (0.5-2.0, default: 1.0)
- **volume**: Voice volume (0.1-2.0, default: 1.0)

## 4. Integration Flow

1. **User selects Coze TTS** from the TTS server dropdown
2. **API key is entered** in the Coze API Key field
3. **Voice list is fetched** from Coze API (or uses default list if API key not set)
4. **Voice is selected** from the Coze voice list
5. **TTS synthesis** is performed using Coze API
6. **Audio file** is generated and saved
7. **Subtitles** are created using the returned audio duration

## 5. Error Handling

- **API Key Validation**: Checks if API key is provided
- **Voice List Fetching**: Falls back to default voice list if API call fails
- **Network Errors**: Implements error handling for network failures
- **Response Validation**: Validates API responses
- **Audio Processing**: Handles different audio formats

## 6. Dependencies

- **requests**: For API calls
- **pydub**: For audio processing

## 7. Usage Instructions

1. **Obtain Coze API Key** from https://www.coze.cn
2. **Add API Key** to config.toml under [coze] section
3. **Select Coze TTS** in the web UI
4. **Choose a voice** from the Coze voice list
5. **Adjust speed and volume** as needed
6. **Click "Play Voice"** to test the selected voice
7. **Generate video** with Coze TTS narration

## 8. Testing

- **Voice List**: Verify Coze voices appear in the dropdown (either from API or default list)
- **API Key**: Test with valid/invalid API keys
- **Text Synthesis**: Test with different text lengths and languages
- **Audio Quality**: Verify audio quality and subtitle synchronization
- **Error Handling**: Test network failures and invalid parameters

## 9. Troubleshooting

- **API Key Issues**: Ensure API key is valid and has TTS permissions
- **Network Errors**: Check internet connectivity and firewall settings
- **Audio Issues**: Verify pydub is installed (`pip install pydub`)
- **Configuration**: Ensure config.toml has correct Coze API key

## 10. Conclusion

The Coze TTS integration follows the same design pattern as other TTS providers in the project. It provides users with additional voice options and maintains consistency with the existing codebase architecture. The integration is complete and ready for use with proper API key configuration.