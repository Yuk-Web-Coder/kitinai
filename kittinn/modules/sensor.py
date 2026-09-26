"""
modules/sensor.py - ドア開閉センサー監視

本番モード : RPi.GPIO でピン27の立下りエッジを検出
モックモード: Enterキー入力でドア開閉をシミュレーション
"""
import threading
import sys
from config import MOCK_MODE, DOOR_SENSOR_PIN

# GPIO の条件付きインポート
_gpio_available = False
GPIO = None

if not MOCK_MODE:
    try:
        import RPi.GPIO as _GPIO
        GPIO = _GPIO
        _gpio_available = True
    except (ImportError, RuntimeError):
        print("⚠️  RPi.GPIO が利用できません → モックモードにフォールバックします")


class DoorSensor:
    """
    ドア開閉センサー管理クラス。

    callback: ドアが開いたときに呼び出される関数 (引数なし)
    """

    def __init__(self, callback):
        self.callback = callback
        self._running = False
        self._thread = None

        if _gpio_available:
            self._setup_gpio()

    # ------------------------------------------------------------------
    # 本番 GPIO モード
    # ------------------------------------------------------------------
    def _setup_gpio(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(DOOR_SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(
            DOOR_SENSOR_PIN,
            GPIO.FALLING,
            callback=self._gpio_callback,
            bouncetime=300,
        )
        print(f"🔌 GPIO センサー初期化完了 (ピン: {DOOR_SENSOR_PIN})")

    def _gpio_callback(self, channel):
        print(f"🚪 ドア開閉検知 (GPIO {channel})")
        self.callback()

    # ------------------------------------------------------------------
    # モック（Enterキー）モード
    # ------------------------------------------------------------------
    def _mock_loop(self):
        """バックグラウンドスレッドで Enter キーを待機する"""
        print("\n" + "=" * 50)
        print("🖥️  シミュレーションモード")
        print("  [Enter] キーでドア開閉をシミュレーション")
        print("  [Ctrl+C] で終了")
        print("=" * 50 + "\n")

        while self._running:
            try:
                sys.stdin.readline()  # Enter 待機
                if self._running:
                    print("🚪 [MOCK] ドア開閉シミュレーション発生")
                    self.callback()
            except EOFError:
                break

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------
    def start(self):
        """センサー監視を開始する"""
        self._running = True

        if _gpio_available:
            # GPIO は割り込みベースなので別途スレッド不要
            print("🔌 GPIO センサー監視開始")
        else:
            # モック: バックグラウンドスレッドで Enter 待機
            self._thread = threading.Thread(
                target=self._mock_loop, daemon=True
            )
            self._thread.start()

    def stop(self):
        """センサー監視を停止する"""
        self._running = False

        if _gpio_available:
            try:
                GPIO.remove_event_detect(DOOR_SENSOR_PIN)
                GPIO.cleanup()
            except Exception:
                pass

        print("🔒 センサー停止")
