#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证voice_name参数修复
检查前端验证和后端验证是否都已正确实现
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def check_frontend_validation() -> bool:
    """检查前端是否添加了voice_name验证"""
    print("\n=== 检查前端验证 ===")
    
    with open("webui/Main.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # 检查是否有voice_name验证
    if "if not params.voice_name:" in content:
        print("✓ 前端已添加voice_name验证")
        
        # 检查是否有错误提示
        if 'tr("Please Select a Voice/TTS Server")' in content:
            print("✓ 前端已添加正确的错误提示")
        else:
            print("✗ 前端缺少错误提示文本")
            return False
    else:
        print("✗ 前端缺少voice_name验证")
        return False
    
    return True

def check_backend_validation() -> bool:
    """检查后端是否添加了voice_name验证"""
    print("\n=== 检查后端验证 ===")
    
    with open("app/services/task.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # 检查是否有voice_name验证
    if "if not params.voice_name:" in content:
        print("✓ 后端已添加voice_name验证")
        
        # 检查是否有错误日志
        if "voice_name is empty" in content:
            print("✓ 后端已添加错误日志")
        else:
            print("⚠ 后端缺少错误日志")
    else:
        print("✗ 后端缺少voice_name验证")
        return False
    
    return True

def check_language_strings() -> bool:
    """检查是否添加了多语言字符串"""
    print("\n=== 检查多语言支持 ===")
    
    # 检查中文
    with open("webui/i18n/zh.json", "r", encoding="utf-8") as f:
        zh_content = f.read()
    
    if "Please Select a Voice/TTS Server" in zh_content:
        print("✓ 中文i18n已添加字符串")
    else:
        print("✗ 中文i18n缺少字符串")
        return False
    
    # 检查英文
    with open("webui/i18n/en.json", "r", encoding="utf-8") as f:
        en_content = f.read()
    
    if "Please Select a Voice/TTS Server" in en_content:
        print("✓ 英文i18n已添加字符串")
    else:
        print("✗ 英文i18n缺少字符串")
        return False
    
    return True

def main() -> int:
    print("=" * 60)
    print("voice_name参数修复验证")
    print("=" * 60)
    
    results = []
    results.append(("前端验证", check_frontend_validation()))
    results.append(("后端验证", check_backend_validation()))
    results.append(("多语言支持", check_language_strings()))
    
    print("\n" + "=" * 60)
    print("验证总结:")
    print("=" * 60)
    
    all_passed = True
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{status}: {name}")
        if not result:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ 所有验证通过！修复完成。")
        print("\n修复内容:")
        print("1. 前端添加了voice_name验证")
        print("2. 后端generate_audio()添加了voice_name验证")
        print("3. 添加了多语言错误提示")
        print("\n修复效果:")
        print("- 用户如果没有选择语音就尝试生成视频，会看到错误提示")
        print("- 避免了因voice_name为空导致的TypeError")
        print("- 改善了用户体验")
        return 0
    else:
        print("✗ 有些验证未通过，请检查修改。")
        return 1

if __name__ == "__main__":
    sys.exit(main())
