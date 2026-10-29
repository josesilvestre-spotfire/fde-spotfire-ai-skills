# ipy_parse.ps1 - compile an IronPython file with the IronPython 3.4 engine that ships with Spotfire
# Analyst (the Script Support module), without running it. Prints "PARSE OK (IronPython <version>)" or
# "ERROR <type>: <message>" with the line ("NOT RUN: ..." when no Analyst is installed). Spotfire itself
# is never started.
# The Analyst install folder: SPOTFIRE_HOME, else the newest %LOCALAPPDATA%\Spotfire\<version> folder
# that holds Spotfire.Dxp.exe.
param([string]$File)
$home_ = $env:SPOTFIRE_HOME
if (-not $home_ -and $env:LOCALAPPDATA) {
  $base = Join-Path $env:LOCALAPPDATA 'Spotfire'
  if (Test-Path -LiteralPath $base) {
    $home_ = @(Get-ChildItem -LiteralPath $base -Directory |
      Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'Spotfire.Dxp.exe') } |
      Sort-Object @{ Expression = { $v = $null; if ([Version]::TryParse($_.Name, [ref]$v)) { $v } else { [Version]'0.0' } } } -Descending |
      Select-Object -First 1 | ForEach-Object { $_.FullName })
  }
}
if (-not $home_) { "NOT RUN: Spotfire Analyst not found (set SPOTFIRE_HOME)"; exit 2 }
$mods = Join-Path $home_ 'Modules'
$support = @(Get-ChildItem -LiteralPath $mods -Directory -Filter 'Script Support_*' -ErrorAction SilentlyContinue |
  Sort-Object Name -Descending | Select-Object -First 1)
if ($support.Count -eq 0) { "NOT RUN: no Script Support module under $mods"; exit 2 }
$dir = Join-Path $support[0].FullName 'IronPython-3'
$index = @{}
Get-ChildItem -Path $mods -Recurse -Filter *.dll -ErrorAction SilentlyContinue | ForEach-Object { if (-not $index.ContainsKey($_.BaseName)) { $index[$_.BaseName] = $_.FullName } }
[AppDomain]::CurrentDomain.add_AssemblyResolve({ param($s, $e); $n = (New-Object Reflection.AssemblyName($e.Name)).Name; if ($index.ContainsKey($n)) { return [Reflection.Assembly]::LoadFrom($index[$n]) }; return $null })
$ipy = [Reflection.Assembly]::LoadFrom((Join-Path $dir 'IronPython.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $dir 'Microsoft.Scripting.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $dir 'Microsoft.Dynamic.dll'))
$python = $ipy.GetType('IronPython.Hosting.Python')
$engine = $python.GetMethod('CreateEngine', [Type[]]@()).Invoke($null, $null)
$code = [IO.File]::ReadAllText($File)
$kind = [Enum]::Parse($engine.GetType().Assembly.GetType('Microsoft.Scripting.SourceCodeKind', $false) -as [Type], 'File') 2>$null
$sck = [AppDomain]::CurrentDomain.GetAssemblies() | ForEach-Object { $_.GetType('Microsoft.Scripting.SourceCodeKind', $false) } | Where-Object { $_ } | Select-Object -First 1
$src = $engine.CreateScriptSourceFromString($code, [Enum]::Parse($sck, 'File'))
try {
  [void]$src.Compile()
  "PARSE OK (IronPython " + $engine.LanguageVersion + ")"
} catch {
  $e = $_.Exception
  while ($e.InnerException -ne $null) { $e = $e.InnerException }
  "ERROR " + $e.GetType().Name + ": " + $e.Message
  if ($e.PSObject.Properties['Line']) { "line " + $e.Line + " col " + $e.Column; "LINE TEXT: " + ($code -split "`n")[$e.Line - 1] }
}
