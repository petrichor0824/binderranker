"""用户可见错误事实与内部技术诊断的边界。"""

from __future__ import annotations


class UserFacingError(RuntimeError):
    """领域错误可显式提供安全的用户可见事实。

    ``str(error)`` 保留完整技术诊断语义；
    ``public_message`` 只包含允许展示给普通用户的
    已确认事实。

    未显式提供 public_message 时，默认不公开
    原始异常文本。
    """

    def __init__(
        self,
        message: str,
        *,
        public_message: str | None = None,
    ) -> None:
        super().__init__(message)

        clean_public_message = (
            public_message.strip()
            if isinstance(public_message, str)
            else None
        )

        self.public_message = (
            clean_public_message
            if clean_public_message
            else None
        )
