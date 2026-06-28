"""音频转录与总结工具 - 入口"""
import multiprocessing
import sys

from audio_recorder.app.application import main

if __name__ == "__main__":
    # PyInstaller 打包后使用 multiprocessing 必须调用 freeze_support()
    multiprocessing.freeze_support()
    sys.exit(main())
