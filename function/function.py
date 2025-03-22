import os
import requests
import json
import time
from tiktokautouploader import upload_tiktok

api_base_url = os.getenv("API_URL")
headers = {"Content-Type": "application/json"}

video_subject = os.getenv("VIDEO_SUBJECT")
video_language = "en-US"
subtitle_font = "STHeitiMedium.ttc"
subtitle_position = "bottom"
subtitle_font_color = "#FFFFFF"
subtitle_outline_color = "#000000"
subtitle_font_size = 60
subtitle_outline_width = 1.5
video_source = "pexels"
video_concat_mode = "random"
video_transition_mode = "None"
video_aspect_ratio = "9:16"
video_clip_duration = 3
video_count = 1
speech_voice = "en-US-GuyNeural-Male"
speech_volume = 1.0
speech_rate = 1.0
song_file_path = "./music.mp3"
bgm_file_path = "../resource/songs/music.mp3"
bgm_volume = 0.2

def function(request):

    upload_music_url = f"{api_base_url}/musics"
    files = {'file': open(song_file_path, 'rb')}
    response = requests.post(upload_music_url, files=files)
    bgm_file = response.json()['data']['file']

    generate_script_url = f"{api_base_url}/scripts"
    script_payload = {
        "video_subject": video_subject,
        "video_language": video_language,
        "paragraph_number": 1
    }
    response = requests.post(generate_script_url, headers=headers, data=json.dumps(script_payload))
    video_script = response.json()['data']['video_script']

    generate_keywords_url = f"{api_base_url}/terms"
    keywords_payload = {
        "video_subject": video_subject,
        "video_script": video_script,
        "amount": 5
    }
    response = requests.post(generate_keywords_url, headers=headers, data=json.dumps(keywords_payload))
    video_terms = response.json()['data']['video_terms']

    generate_video_url = f"{api_base_url}/videos"
    video_payload = {
        "video_subject": video_subject,
        "video_script": video_script,
        "video_terms": video_terms,
        "video_aspect": video_aspect_ratio,
        "video_concat_mode": video_concat_mode,
        "video_transition_mode": video_transition_mode,
        "video_clip_duration": video_clip_duration,
        "video_count": video_count,
        "video_source": video_source,
        "video_language": video_language,
        "voice_name": speech_voice,
        "voice_volume": speech_volume,
        "voice_rate": speech_rate,
        "bgm_type": "custom",
        "bgm_file": bgm_file,
        "bgm_volume": bgm_volume,
        "subtitle_enabled": False,
    }

    response = requests.post(generate_video_url, headers=headers, data=json.dumps(video_payload))
    print(response.json())

    task_id = response.json()['data']['task_id']

    time.sleep(float(os.getenv("TIME_BEFORE_DOWNLOAD")))

    download_url = f"{api_base_url}/download/{task_id}/final-1.mp4"
    response = requests.get(download_url, headers=headers)
    with open('output_video.mp4', 'wb') as f:
        f.write(response.content)

    video_path = "output_video.mp4"
    description = os.getenv("VIDEO_DESCRIPTION")
    account_name = os.getenv("ACCOUNT_NAME")
    hashtags = ['fyp']

    upload_tiktok(video=video_path, description=description, accountname=account_name)

    return "Function executed successfully"