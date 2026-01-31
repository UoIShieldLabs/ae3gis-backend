"""AI-powered log analysis using OpenAI."""

from __future__ import annotations

import os
import logging
from datetime import datetime

from openai import OpenAI

logger = logging.getLogger(__name__)

# Default model - can be overridden via OPENAI_MODEL env var
DEFAULT_MODEL = "gpt-5.2"

SYSTEM_PROMPT = """You are a cybersecurity lab instructor analyzing student command history logs from a network security lab session.

The logs contain commands executed by the student on various network nodes (servers, clients, PLCs, HMIs) in an industrial control system (ICS) environment. The lab typically involves IT (Information Technology) and OT (Operational Technology) networks.

Your task is to:
1. Summarize what the student did during the lab session
2. Identify key actions
3. Note any potential mistakes, security issues, or misconfigurations

Be very concise.
"""


class AIAnalyzer:
    """Service for analyzing student logs using OpenAI."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """Initialize the AI analyzer.
        
        Args:
            api_key: OpenAI API key. If not provided, uses OPENAI_API_KEY env var.
            model: Model to use. If not provided, uses OPENAI_MODEL env var or default.
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided and OPENAI_API_KEY env var not set")
        
        self.model = model or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
        self.client = OpenAI(api_key=self.api_key)

    def analyze_logs(
        self,
        it_logs: str | None,
        ot_logs: str | None,
        student_name: str,
        project_name: str | None = None,
    ) -> tuple[str, str]:
        """Analyze student logs and generate a summary.
        
        Args:
            it_logs: Logs from IT-side collector.
            ot_logs: Logs from OT-side collector.
            student_name: Name of the student.
            project_name: Optional project/lab name.
        
        Returns:
            Tuple of (analysis_text, model_used).
        """
        # Build the user message with logs
        user_message_parts = [f"Student: {student_name}"]
        
        if project_name:
            user_message_parts.append(f"Lab/Project: {project_name}")
        
        user_message_parts.append("\n--- IT Network Logs ---")
        if it_logs and it_logs.strip():
            user_message_parts.append(it_logs)
        else:
            user_message_parts.append("(No commands logged from IT network)")
        
        user_message_parts.append("\n--- OT Network Logs ---")
        if ot_logs and ot_logs.strip():
            user_message_parts.append(ot_logs)
        else:
            user_message_parts.append("(No commands logged from OT network)")
        
        user_message = "\n".join(user_message_parts)
        
        # Check if we have any logs to analyze
        if (not it_logs or not it_logs.strip()) and (not ot_logs or not ot_logs.strip()):
            return (
                "No commands were logged from either IT or OT networks. "
                "The student may not have executed any commands, or logging was not properly configured.",
                self.model,
            )
        
        try:
            logger.info(f"Analyzing logs for {student_name} using {self.model}")
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,  # Lower temperature for more consistent analysis
                max_completion_tokens=1000,
            )
            
            analysis = response.choices[0].message.content or "No analysis generated."
            logger.info(f"Successfully analyzed logs for {student_name}")
            
            return analysis, self.model
            
        except Exception as e:
            logger.error(f"Failed to analyze logs for {student_name}: {e}")
            raise RuntimeError(f"AI analysis failed: {e}") from e


def get_ai_analyzer() -> AIAnalyzer:
    """Get an AI analyzer instance using environment configuration."""
    return AIAnalyzer()
