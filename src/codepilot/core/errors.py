"""统一领域异常层级。

约定：基础设施异常在边界转译为 DomainError；用户可见消息友好，细节只进日志。
见 docs/DEVELOPMENT_GUIDELINES.md §7。
"""

from __future__ import annotations


class DomainError(Exception):
    """所有领域异常的基类。"""

    code: str = "DOMAIN_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def __str__(self) -> str:
        return self.message


class NotFoundError(DomainError):
    code = "NOT_FOUND"


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"


class PermissionDeniedError(DomainError):
    """越权访问：路径越界、命令黑名单等。"""

    code = "PERMISSION_DENIED"


class ProviderError(DomainError):
    """LLM 上游错误。"""

    code = "PROVIDER_ERROR"


class ExecError(DomainError):
    """命令执行 / IO 错误。"""

    code = "EXEC_ERROR"
