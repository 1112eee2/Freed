# PowerShell script to launch Thai Makhos Web GUI
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir
python server.py
