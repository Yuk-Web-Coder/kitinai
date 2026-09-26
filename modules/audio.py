"""
modules/audio.py - 音声入出力

本番モード : PyAudio + SpeechRecognition でマイク録音, gTTS + playsound で読み上げ
モックモード: input() でテキスト入力, print() で読み上げ代替
"""
import os
import sys
import tempfile
from config import MOCK_MODE

# 本番用ライブラリの条件付きインポート
_sr_available = False
_gtts_available = False
_play_available = False

sr = None
gTTS = None

if not MOCK_MODE:
    try:
        import speech_recognition as _sr
        sr = _sr
        _sr_available = True
    except ImportError:
        print("⚠️  SpeechRecognition が利用できません → テキスト入力にフォールバック")

    try:
        from gtts import gTTS as _gTTS
        gTTS = _gTTS
        _gtts_available = True
    except ImportError:
        print("⚠️  gTTS が利用できません → print 読み上げにフォールバック")

    try:
        from playsound import playsound as _playsound
        _play_func = _playsound
        _play_available = True
    except ImportError:
        print("⚠️  playsound が利用できません → print 読み上げにフォールバック")
        _play_func = None
else:
    _play_func = None


class AudioManager:
    """
    音声入出力管理クラス。
    MOCK_MODE またはハードウェア不在時はコンソール I/O にフォールバック。
    """

    def __init__(self):
        self._use_mic = _sr_available and not MOCK_MODE
        self._use_tts = _gtts_available and _play_available and not MOCK_MODE

        if self._use_mic:
            self._recognizer = sr.Recognizer()
            self._mic = sr.Microphone()
            # 環境ノイズ調整
            with self._mic as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=1)
            print("🎤 マイク初期化完了")
        else:
            print("🖥️  音声入力: テキスト入力モード")

        if self._use_tts:
            print("🔊 TTS: gTTS モード")
        else:
            print("🖥️  音声出力: テキスト表示モード")

    # ------------------------------------------------------------------
    # 音声入力
    # ------------------------------------------------------------------
    def listen(self) -> str:
        """
        音声またはテキスト入力を取得する。
        Returns:
            認識されたテキスト（空文字列の場合は再入力を促す）
        """
        if self._use_mic:
            return self._listen_mic()
        else:
            return self._listen_text()

    def _listen_mic(self) -> str:
        print("🎤 話しかけてください...")
        try:
            with self._mic as source:
                audio = self._recognizer.listen(source, timeout=5, phrase_time_limit=10)
            text = self._recognizer.recognize_google(audio, language="ja-JP")
            print(f"📝 認識結果: {text}")
            return text
        except sr.WaitTimeoutError:
            print("⏱️  タイムアウト: 音声が検出されませんでした")
            return ""
        except sr.UnknownValueError:
            print("❓ 音声を認識できませんでした")
            return ""
        except sr.RequestError as e:
            print(f"❌ 音声認識エラー: {e}")
            return ""

    def _listen_text(self) -> str:
        try:
            text = input("💬 入力してください（Enterで送信）: ").strip()
            return text
        except (KeyboardInterrupt, EOFError):
            return ""

    # ------------------------------------------------------------------
    # 音声出力
    # ------------------------------------------------------------------
    def speak(self, text: str):
        """
        テキストを読み上げる（またはターミナルに表示する）。
        Args:
            text: 読み上げるテキスト
        """
        if self._use_tts:
            self._speak_tts(text)
        else:
            self._speak_print(text)

    def _speak_tts(self, text: str):
        try:
            tts = gTTS(text=text, lang="ja", slow=False)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                tmp_path = f.name
            tts.save(tmp_path)
            _play_func(tmp_path)
            os.unlink(tmp_path)
        except Exception as e:
            print(f"⚠️  TTS エラー ({e}): {text}")

    def _speak_print(self, text: str):
        print(f"\n🤖 AI: {text}\n")
