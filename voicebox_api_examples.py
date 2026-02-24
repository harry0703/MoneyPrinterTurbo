"""
Voicebox API 调用示例代码
这个模块展示了如何直接调用Voicebox API和使用MoneyPrinterTurbo集成
"""

import requests
import json
from dataclasses import dataclass
from typing import Dict, List, Optional

# ============================================================================
# 基础配置
# ============================================================================

VOICEBOX_BASE_URL = "http://localhost:8000"
TIMEOUT = 10  # 秒

# ============================================================================
# 1. 低级API调用示例 (直接HTTP请求)
# ============================================================================

@dataclass(slots=True)
class VoiceboxAPIClient:
    """原生Voicebox API客户端"""
    
    base_url: str = VOICEBOX_BASE_URL
    timeout: int = TIMEOUT
    
    def health_check(self) -> bool:
        """检查Voicebox服务健康状态"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=self.timeout)
            return response.status_code == 200
        except Exception as e:
            print(f"健康检查失败: {e}")
            return False
    
    def list_profiles(self) -> List[Dict]:
        """获取所有语音配置文件"""
        try:
            response = requests.get(
                f"{self.base_url}/profiles",
                timeout=self.timeout
            )
            if response.status_code == 200:
                profiles = response.json()
                return profiles if isinstance(profiles, list) else []
            else:
                print(f"获取配置文件列表失败: {response.status_code}")
                return []
        except Exception as e:
            print(f"获取配置文件异常: {e}")
            return []
    
    def get_profile(self, profile_id: str) -> Optional[Dict]:
        """获取单个语音配置文件详情"""
        try:
            response = requests.get(
                f"{self.base_url}/profiles/{profile_id}",
                timeout=self.timeout
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"获取配置文件详情失败: {e}")
            return None
    
    def generate_speech(
        self,
        text: str,
        profile_id: str,
        language: str = "en",
        sample_rate: int = 32000
    ) -> Optional[bytes]:
        """生成语音"""
        try:
            payload = {
                "text": text,
                "profile_id": profile_id,
                "language": language,
                "sample_rate": sample_rate
            }
            
            response = requests.post(
                f"{self.base_url}/generate",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=60  # 生成可能需要更长时间
            )
            
            if response.status_code == 200:
                return response.content  # 二进制音频数据
            else:
                print(f"生成语音失败: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"生成语音异常: {e}")
            return None
    
    def create_profile(self, name: str, language: str = "en") -> Optional[str]:
        """创建新的语音配置文件"""
        try:
            payload = {
                "name": name,
                "language": language
            }
            
            response = requests.post(
                f"{self.base_url}/profiles",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout
            )
            
            if response.status_code == 200 or response.status_code == 201:
                result = response.json()
                return result.get("id")
            return None
        except Exception as e:
            print(f"创建配置文件失败: {e}")
            return None


# ============================================================================
# 2. MoneyPrinterTurbo集成示例
# ============================================================================

def example_with_mpt_services() -> None:
    """使用MoneyPrinterTurbo服务进行调用"""
    from app.services import voice
    from app.config import config
    
    print("\n=== 使用MoneyPrinterTurbo服务 ===")
    
    # 获取Voicebox语音列表
    print("1. 获取语音列表:")
    voices = voice.get_voicebox_voices()
    print(f"   可用语音数: {len(voices)}")
    for v in voices[:3]:
        print(f"   - {v}")
    
    # 检查语音类型
    print("\n2. 检查语音类型:")
    test_voice = "voicebox:abc123:My Voice"
    is_voicebox = voice.is_voicebox_voice(test_voice)
    print(f"   '{test_voice}' 是Voicebox语音: {is_voicebox}")
    
    # 生成语音
    if voices:
        print("\n3. 生成语音:")
        profile_id = voices[0].split(":")[1]
        text = "Hello, this is a test voice from Voicebox."
        output_file = "test_output.mp3"
        
        sub_maker = voice.voicebox_tts(
            text=text,
            profile_id=profile_id,
            voice_rate=1.0,
            voice_file=output_file,
            voice_volume=1.0
        )
        
        if sub_maker:
            print(f"   ✓ 生成成功: {output_file}")
            print(f"   字幕条数: {len(sub_maker.subs)}")
        else:
            print(f"   ✗ 生成失败")
    
    # 使用统一TTS函数
    print("\n4. 使用统一tts()函数:")
    if voices:
        voice_name = voices[0]
        sub_maker = voice.tts(
            text="Test text",
            voice_name=voice_name,
            voice_rate=1.0,
            voice_file="test_unified.mp3",
            voice_volume=1.0
        )
        print(f"   统一调用成功: {sub_maker is not None}")


# ============================================================================
# 3. 完整工作流示例
# ============================================================================

def complete_workflow_example() -> None:
    """完整的Voicebox使用工作流"""
    
    print("\n=== 完整工作流示例 ===")
    
    client = VoiceboxAPIClient()
    
    # 步骤1: 检查服务健康
    print("\n步骤1: 检查Voicebox服务")
    if client.health_check():
        print("   ✓ Voicebox服务正常")
    else:
        print("   ✗ Voicebox服务不可用")
        return
    
    # 步骤2: 获取可用的语音配置
    print("\n步骤2: 获取可用语音")
    profiles = client.list_profiles()
    if not profiles:
        print("   ⚠ 未找到任何语音配置")
        print("   请在Voicebox应用中创建语音配置文件")
        return
    
    print(f"   找到 {len(profiles)} 个语音配置:")
    for profile in profiles[:3]:
        print(f"   - {profile.get('name')} (ID: {profile.get('id')})")
    
    # 步骤3: 选择第一个语音配置
    print("\n步骤3: 选择语音配置")
    profile_id = profiles[0]["id"]
    profile_name = profiles[0]["name"]
    print(f"   选中: {profile_name} (ID: {profile_id})")
    
    # 步骤4: 准备文本内容
    print("\n步骤4: 准备文本内容")
    text_content = """
    Hello! This is a test message.
    This demonstrates how to use Voicebox for text-to-speech generation.
    You can use this for video voiceovers, podcasts, and more.
    """
    print(f"   文本长度: {len(text_content)} 字符")
    
    # 步骤5: 生成语音
    print("\n步骤5: 生成语音")
    print("   正在处理... (这可能需要几秒钟)")
    
    audio_data = client.generate_speech(
        text=text_content,
        profile_id=profile_id,
        language="en"
    )
    
    if audio_data:
        print(f"   ✓ 生成成功")
        print(f"   音频大小: {len(audio_data)} 字节")
        
        # 保存音频文件
        output_path = "generated_speech.mp3"
        with open(output_path, "wb") as f:
            f.write(audio_data)
        print(f"   ✓ 已保存: {output_path}")
    else:
        print(f"   ✗ 生成失败")


# ============================================================================
# 4. 错误处理最佳实践
# ============================================================================

def error_handling_example() -> None:
    """展示错误处理的最佳实践"""
    
    print("\n=== 错误处理示例 ===")
    
    client = VoiceboxAPIClient()
    
    # 示例1: 连接超时处理
    print("\n1. 连接超时处理")
    try:
        # 尝试连接到一个无效的地址
        bad_client = VoiceboxAPIClient(base_url="http://invalid:9999")
        bad_client.list_profiles()
    except requests.exceptions.Timeout:
        print("   查获: 连接超时，增加timeout值或检查网络")
    except requests.exceptions.ConnectionError:
        print("   查获: 连接失败，检查服务器地址和网络")
    except Exception as e:
        print(f"   查获: {type(e).__name__} - {e}")
    
    # 示例2: 重试机制
    print("\n2. 重试机制")
    max_retries = 3
    for attempt in range(max_retries):
        try:
            profiles = client.list_profiles()
            if profiles:
                print(f"   ✓ 第{attempt+1}次尝试成功")
                break
        except Exception as e:
            print(f"   ✗ 第{attempt+1}次尝试失败: {e}")
            if attempt >= max_retries - 1:
                print("   已达最大重试次数")
    
    # 示例3: 验证响应数据
    print("\n3. 验证响应数据")
    profiles = client.list_profiles()
    if isinstance(profiles, list) and len(profiles) > 0:
        profile = profiles[0]
        required_fields = ["id", "name"]
        missing_fields = [f for f in required_fields if f not in profile]
        if missing_fields:
            print(f"   警告: 缺少字段 {missing_fields}")
        else:
            print(f"   ✓ 数据字段完整")


# ============================================================================
# 5. 配置与监控
# ============================================================================

def configuration_example() -> None:
    """配置与监控示例"""
    
    print("\n=== 配置与监控示例 ===")
    
    try:
        from app.config import config
        from app.services import voice
        
        print("\n1. 当前Voicebox配置:")
        print(f"   base_url: {config.voicebox.get('base_url')}")
        print(f"   default_profile_id: {config.voicebox.get('default_profile_id')}")
        
        print("\n2. 获取可用语音:")
        voices = voice.get_voicebox_voices()
        print(f"   共 {len(voices)} 个语音可用")
        
        if voices:
            print("\n3. 测试生成:")
            first_voice = voices[0]
            print(f"   使用语音: {first_voice}")
            
            # 提取profile_id
            parts = first_voice.split(":")
            if len(parts) >= 2:
                profile_id = parts[1]
                
                # 尝试生成
                sub_maker = voice.voicebox_tts(
                    text="Configuration test",
                    profile_id=profile_id,
                    voice_rate=1.0,
                    voice_file="config_test.mp3"
                )
                
                if sub_maker:
                    print(f"   ✓ 生成测试成功")
                else:
                    print(f"   ✗ 生成测试失败")
    
    except ImportError:
        print("   无法导入MoneyPrinterTurbo模块，请检查环境设置")


# ============================================================================
# 主程序
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Voicebox API 调用示例")
    print("=" * 70)
    
    # 运行示例
    try:
        # 低级API示例
        print("\n### 低级API示例 ###")
        client = VoiceboxAPIClient()
        if client.health_check():
            profiles = client.list_profiles()
            print(f"✓ 连接成功，找到 {len(profiles)} 个语音")
        
        # 高级服务示例
        print("\n### MoneyPrinterTurbo服务示例 ###")
        example_with_mpt_services()
        
        # 完整工作流
        print("\n### 完整工作流 ###")
        complete_workflow_example()
        
        # 错误处理
        print("\n### 错误处理 ###")
        error_handling_example()
        
        # 配置与监控
        print("\n### 配置与监控 ###")
        configuration_example()
        
    except KeyboardInterrupt:
        print("\n\n中断执行")
    except Exception as e:
        print(f"\n错误: {e}")
    
    print("\n" + "=" * 70)
    print("示例完成")
    print("=" * 70)
