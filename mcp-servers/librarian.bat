@echo off
set PYTHONPATH={{FEYNMAN_LIBRARY}}\.trae
{{FEYNMAN_LIBRARY}}\.venv\Scripts\python.exe -m librarian_mcp.server
