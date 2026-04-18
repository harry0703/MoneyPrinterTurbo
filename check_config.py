import toml
import os

# 尝试加载配置文件
try:
    config = toml.load('config.toml')
    print("配置文件加载成功！")
    print("\n配置内容:")
    print(config)
    
    # 检查 LLM 相关配置
    print("\nLLM 相关配置:")
    app_config = config.get('app', {})
    print("llm_provider:", app_config.get('llm_provider'))
    print("deepseek_api_key:", app_config.get('deepseek_api_key'))
    print("moonshot_api_key:", app_config.get('moonshot_api_key'))
    print("openai_api_key:", app_config.get('openai_api_key'))
    
except Exception as e:
    print(f"配置文件加载失败: {e}")
