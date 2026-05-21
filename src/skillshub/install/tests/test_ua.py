"""UA 猜 OS 测试 (T10)."""
from skillshub.install.ua import guess_os


def test_macos_ua():
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    assert guess_os(ua) == "macos"


def test_windows_ua():
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    assert guess_os(ua) == "windows"


def test_linux_ua():
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    assert guess_os(ua) == "linux"


def test_empty_ua_falls_back_to_linux():
    assert guess_os("") == "linux"


def test_android_ua_falls_back_to_linux():
    ua = "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36"
    assert guess_os(ua) == "linux"
