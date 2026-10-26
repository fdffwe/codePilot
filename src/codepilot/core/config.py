"""应用配置（pydantic-settings）。

来源优先级：环境变量 > .env > 默认值。见规范 §9。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from codepilot.domain.approval import ApprovalMode


class Settings(BaseSettings):
    """全局配置。敏感项用 SecretStr，禁止入库/进日志明文。"""

    model_config = SettingsConfigDict(
        env_prefix="CODEPILOT_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "codePilot"
    log_level: str = "INFO"
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".codepilot")

    # 允许绑定为 workspace 的根目录集合（默认仅用户主目录，可收紧）
    workspace_allowlist: list[Path] = Field(
        default_factory=lambda: [Path.home()],
    )

    # --- LLM（P1 起启用；此处先声明契约）---
    llm_provider: str = "openai"
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_api_key: SecretStr | None = None

    # --- 审批 ---
    # plan：只读；default：写/执行询问；auto-edit：编辑放行；yolo：全部放行
    approval_mode: ApprovalMode = ApprovalMode.DEFAULT

    # --- 执行与编排 ---
    command_timeout_s: int = 120
    command_max_output_bytes: int = 1_000_000
    agent_max_iterations: int = 5

    # --- 派生路径 ---
    @property
    def db_path(self) -> Path:
        return self.data_dir / "codepilot.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def checkpoints_path(self) -> Path:
        return self.data_dir / "checkpoints.sqlite"

    @property
    def permissions_path(self) -> Path:
        """用户级权限白名单；工作区级文件由 agent 每次 run 自行读取。"""
        return self.data_dir / "permissions.json"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def config_file(self) -> Path:
        return self.data_dir / "config.toml"

    def ensure_dirs(self) -> None:
        """确保运行时目录存在。"""
        for d in (self.data_dir, self.logs_dir, self.backups_dir):
            d.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """进程级单例。"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
