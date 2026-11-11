"""One import-safe task manager shared by the API and TrueConf ChatOps.

Do not import from main.py inside ChatOps: when the server starts as
"python main.py", importing "main" loads the application a second time.
"""
from core.agent_task_manager import AgentTaskManager

agent_task_mgr = AgentTaskManager()
