"""验证 FunASR Paraformer-large 中文转录功能"""
import io
import os
import sys

from funasr import AutoModel

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

def test_transcribe(audio_file="test_recording.wav"):
    """测试 FunASR 转录"""
    if not os.path.exists(audio_file):
        print(f"错误：音频文件不存在: {audio_file}")
        return False

    file_size = os.path.getsize(audio_file)
    print(f"音频文件: {audio_file}")
    print(f"文件大小: {file_size/1024:.1f} KB")

    print("\n正在加载 Paraformer-large 模型（CPU 模式）...")

    try:
        model = AutoModel(
            model="paraformer-zh",
            model_revision="v2.0.4",
            vad_model="fsmn-vad",
            vad_model_revision="v2.0.4",
            punc_model="ct-punc-c",
            punc_model_revision="v2.0.4",
            device="cpu",
        )

        print("模型加载完成，开始转录...\n")

        result = model.generate(input=audio_file)

        if result and len(result) > 0:
            text = result[0].get("text", "")
            print("转录结果:")
            print("---")
            print(text)
            print("---")
            print(f"\n转录成功！文字长度: {len(text)} 字符")
            return True
        else:
            print("转录结果为空")
            return False

    except Exception as e:
        print(f"转录失败: {e}")
        return False


if __name__ == "__main__":
    print("=== FunASR Paraformer-large 转录验证 ===\n")

    success = test_transcribe()

    if success:
        print("\n结果：FunASR 转录正常工作。")
    else:
        print("\n结果：转录验证未通过。")
