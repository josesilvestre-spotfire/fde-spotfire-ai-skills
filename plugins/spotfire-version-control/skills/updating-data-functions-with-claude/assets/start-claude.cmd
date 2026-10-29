@echo off
rem Starts Claude Code in this folder in auto permission mode.
rem Optional: pass the request as text, for example
rem   start-claude.cmd "Add the sample standard deviation to Calculate Column Statistics"
cd /d "%~dp0"
if "%DXP_WORKSPACE%"=="" (
  echo Set DXP_WORKSPACE to the folder that holds the Spotfire runner first.
  exit /b 1
)
claude --permission-mode auto %*
