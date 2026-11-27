"""集成异常类型。"""

from __future__ import annotations


class VattiError(Exception):
    """集成内所有异常的基类。"""


class VattiConnectionError(VattiError):
    """网络不可达、超时或响应无法解析。"""


class VattiApiError(VattiError):
    """云端返回业务错误。"""

    def __init__(self, message: str, code: object | None = None) -> None:
        super().__init__(message)
        self.code = code


class VattiAuthError(VattiApiError):
    """token 失效、被顶号或未授权。"""


class VattiLoginError(VattiApiError):
    """短信验证码错误或登录接口拒绝。"""


class VattiSmsError(VattiApiError):
    """短信发送失败（滑块票据无效、频率限制等）。"""


class VattiCaptchaError(VattiError):
    """滑块票据缺失或格式不正确。"""


class VattiDeviceOfflineError(VattiApiError):
    """设备离线，指令无法下发。"""
