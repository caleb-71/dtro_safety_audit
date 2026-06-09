# main.py
# DTRO 자체종합안전심사 AI 분석 시스템
# PyCharm Run 버튼으로 Streamlit 자동 실행

import subprocess
import sys
import os


def main():
    # 프로젝트 루트로 이동
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 50)
    print("  DTRO 자체종합안전심사 AI 시스템 시작")
    print("  브라우저에서 http://localhost:8501 열림")
    print("=" * 50)

    subprocess.run([
        sys.executable, "-m", "streamlit",
        "run", "app.py",
        "--server.port", "8501",
        "--browser.gatherUsageStats", "false"
    ])


if __name__ == "__main__":
    main()