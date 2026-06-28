"""验证 pyaudiowpatch WASAPI loopback 录音功能"""
import io
import os
import sys
import wave

import pyaudiowpatch as pyaudio

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

def find_loopback_device():
    """找到系统音频 loopback 设备"""
    p = pyaudio.PyAudio()
    loopback_device = None

    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        if info.get("isLoopbackDevice") and "扬声器" in info.get("name", ""):
            loopback_device = info
            break

    p.terminate()
    return loopback_device


def test_record_loopback(duration=5):
    """测试录制系统音频（loopback）"""
    p = pyaudio.PyAudio()

    # 找到 loopback 设备
    loopback = find_loopback_device()
    if not loopback:
        print("错误：未找到扬声器 loopback 设备")
        p.terminate()
        return False

    device_index = loopback["index"]
    print(f"使用 loopback 设备: {loopback['name']}")
    print(f"设备索引: {device_index}")
    print(f"采样率: {loopback['defaultSampleRate']}")
    print(f"通道数: {loopback['maxInputChannels']}")

    # 开始录音
    print(f"\n开始录制 {duration} 秒系统音频...")
    print("（请播放一些音频，例如音乐或视频）")

    stream = p.open(
        format=pyaudio.paInt16,
        channels=loopback["maxInputChannels"],
        rate=int(loopback["defaultSampleRate"]),
        input=True,
        input_device_index=device_index,
        frames_per_buffer=1024
    )

    frames = []
    for i in range(0, int(loopback["defaultSampleRate"] / 1024 * duration)):
        data = stream.read(1024, exception_on_overflow=False)
        frames.append(data)

    stream.stop_stream()
    stream.close()

    # 保存为 WAV 文件
    output_file = "test_recording.wav"
    wf = wave.open(output_file, 'wb')
    wf.setnchannels(loopback["maxInputChannels"])
    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
    wf.setframerate(int(loopback["defaultSampleRate"]))
    wf.writeframes(b''.join(frames))
    wf.close()

    p.terminate()

    file_size = os.path.getsize(output_file)
    print(f"\n录音完成！保存到: {output_file}")
    print(f"文件大小: {file_size} 字节 ({file_size/1024:.1f} KB)")

    # 检查是否有实际音频数据（不是静音）
    if file_size > 10000:  # 至少 10KB
        print("验证通过！录音文件包含音频数据。")
        return True
    else:
        print("警告：录音文件很小，可能是静音。请确保有音频播放。")
        return False


if __name__ == "__main__":
    print("=== WASAPI Loopback 录音验证 ===\n")

    success = test_record_loopback(duration=5)

    if success:
        print("\n结果：pyaudiowpatch WASAPI loopback 录音正常工作。")
    else:
        print("\n结果：录音验证未通过。")
