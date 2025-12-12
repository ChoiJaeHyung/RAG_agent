"""
Centralized logging configuration for RAG Agent system.
Provides structured logging with rotation and formatting.
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime
from config.settings import settings


def setup_logger(name: str = "rag_agent") -> logging.Logger:
    """
    Set up logger with console and file handlers.

    Args:
        name: Logger name (default: "rag_agent")

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Create logs directory
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(exist_ok=True)

    # Format: [2025-10-28 10:30:45.123] [INFO] [module] Message
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler - general logs (rotating)
    today = datetime.now().strftime("%Y-%m-%d")
    file_handler = RotatingFileHandler(
        log_dir / f"agent_{today}.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # File handler - error logs only (rotating)
    error_handler = RotatingFileHandler(
        log_dir / f"error_{today}.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    return logger


# Global logger instance
logger = setup_logger()


def log_iteration(iteration: int, thought: str, action: str, result_count: int) -> None:
    """
    Log Agent iteration details.

    Args:
        iteration: Current iteration number
        thought: Agent's thought process
        action: Tool action taken
        result_count: Number of documents retrieved
    """
    logger.info(f"[Iter {iteration}] Thought: {thought}")
    logger.info(f"[Iter {iteration}] Action: {action}")
    logger.info(f"[Iter {iteration}] Result: {result_count} documents")


def log_validation(iteration: int, relevance: bool, novelty: bool,
                   sufficiency: bool, quality: float, decision: str) -> None:
    """
    Log validation results.

    Args:
        iteration: Current iteration number
        relevance: Relevance check result
        novelty: Novelty check result
        sufficiency: Sufficiency check result
        quality: Quality score (0-1)
        decision: Agent's decision based on validation
    """
    logger.info(f"[Iter {iteration}] Validation:")
    logger.info(f"  - Relevance: {'✅' if relevance else '❌'}")
    logger.info(f"  - Novelty: {'✅' if novelty else '❌'}")
    logger.info(f"  - Sufficiency: {'✅' if sufficiency else '❌'}")
    logger.info(f"  - Quality: {quality:.2f}")
    logger.info(f"  - Decision: {decision}")


def log_tool_execution(tool_name: str, params: dict, execution_time: float) -> None:
    """
    Log tool execution details.

    Args:
        tool_name: Name of the tool executed
        params: Tool parameters
        execution_time: Execution time in seconds
    """
    logger.debug(f"Tool: {tool_name}, Params: {params}, Time: {execution_time:.2f}s")


def log_error(error: Exception, context: str = "") -> None:
    """
    Log error with context.

    Args:
        error: Exception object
        context: Additional context about where error occurred
    """
    logger.error(f"Error in {context}: {type(error).__name__}: {str(error)}", exc_info=True)
