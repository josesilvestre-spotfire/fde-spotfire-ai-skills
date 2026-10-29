<#
.SYNOPSIS
  Dump the public Spotfire API (Core module assemblies) to a JSON ground-truth index,
  extract the embedded property documentation, and copy any shipped XML doc files.

.DESCRIPTION
  Static reflection only: assemblies are loaded into THIS PowerShell process with
  Assembly.LoadFrom; Spotfire itself is never started and no running process is touched.

  Public members only: the index lists public types and their public members, the API that
  IronPython scripts and builders may use. Run it once per Spotfire version on your own machine;
  the index is not shipped with the skill.

  Outputs (in -OutDir, default $env:DXP_WORKSPACE\api):
    spotfire-api-<coreBuild>.json      public API of every managed Spotfire.Dxp.*.dll in Core_*
                                       (+ the external base types / interfaces they inherit from)
    spotfire-property-docs.json        docs embedded in Spotfire.Dxp.ExtensionBridge.dll
    Spotfire.Dxp.Data.Formats.Sbdf.xml copied if a shipped XML doc file is found

  sfapi.py, lint_ipy.py and dxpgen.py read the newest spotfire-api-*.json in $DXP_WORKSPACE\api, or
  the file SFAPI_INDEX names.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dump_api.ps1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dump_api.ps1 -SpotfireRoot "<Spotfire install folder>" -OutDir "<folder>"
#>
[CmdletBinding()]
param(
  [string]$SpotfireRoot = '',
  [string]$OutDir = '',
  [string]$ProductVersion = '',
  [string[]]$ExtraAssembly = @(),
  [switch]$SkipDocs
)

$ErrorActionPreference = 'Stop'
$sw = [Diagnostics.Stopwatch]::StartNew()

# Spotfire install: -SpotfireRoot, else SPOTFIRE_HOME, else the newest %LOCALAPPDATA%\Spotfire\<version>
# folder that holds Spotfire.Dxp.exe
if (-not $SpotfireRoot) { $SpotfireRoot = $env:SPOTFIRE_HOME }
if (-not $SpotfireRoot -and $env:LOCALAPPDATA) {
  $base = Join-Path $env:LOCALAPPDATA 'Spotfire'
  if (Test-Path -LiteralPath $base) {
    $found = @(Get-ChildItem -LiteralPath $base -Directory |
      Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'Spotfire.Dxp.exe') } |
      Sort-Object @{ Expression = { $v = $null; if ([Version]::TryParse($_.Name, [ref]$v)) { $v } else { [Version]'0.0' } } } -Descending)
    if ($found.Count -gt 0) { $SpotfireRoot = $found[0].FullName }
  }
}
if (-not $SpotfireRoot) {
  [Console]::Error.WriteLine("dump_api: Spotfire install not found: set SPOTFIRE_HOME or pass -SpotfireRoot <folder that holds Spotfire.Dxp.exe>")
  exit 2
}
# Output folder: -OutDir, else $env:DXP_WORKSPACE\api (DXP_BUILDER_HOME is accepted as an older name)
if (-not $OutDir) {
  $ws = if ($env:DXP_WORKSPACE) { $env:DXP_WORKSPACE } else { $env:DXP_BUILDER_HOME }
  if (-not $ws) {
    [Console]::Error.WriteLine("dump_api: set DXP_WORKSPACE or pass -OutDir <folder>")
    exit 2
  }
  $OutDir = Join-Path $ws 'api'
}
if (-not (Test-Path -LiteralPath $SpotfireRoot)) {
  [Console]::Error.WriteLine("dump_api: Spotfire root not found: $SpotfireRoot (set SPOTFIRE_HOME or pass -SpotfireRoot)")
  exit 2
}
$SpotfireRoot = (Resolve-Path -LiteralPath $SpotfireRoot).Path
$modules = Join-Path $SpotfireRoot 'Modules'
if (-not (Test-Path -LiteralPath $modules)) {
  [Console]::Error.WriteLine("dump_api: no Modules folder under $SpotfireRoot")
  exit 2
}
if (-not (Test-Path -LiteralPath $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path

function Get-FolderVersion([string]$name, [string]$prefix) {
  $s = $name.Substring($prefix.Length)
  $v = $null
  if ([Version]::TryParse($s, [ref]$v)) { return $v }
  return [Version]'0.0'
}

# --- locate Core_<build> (highest version wins) ------------------------------------------
$coreDirs = @(Get-ChildItem -LiteralPath $modules -Directory | Where-Object { $_.Name -like 'Core_*' } |
  Sort-Object @{ Expression = { Get-FolderVersion $_.Name 'Core_' } } -Descending)
if ($coreDirs.Count -eq 0) { throw "No Core_* module folder under $modules" }
$coreDir = $coreDirs[0].FullName
$appDll = Join-Path $coreDir 'Spotfire.Dxp.Application.dll'
if (-not (Test-Path -LiteralPath $appDll)) { throw "Spotfire.Dxp.Application.dll not found in $coreDir" }
$coreBuild = [Diagnostics.FileVersionInfo]::GetVersionInfo($appDll).FileVersion
if (-not $coreBuild) { $coreBuild = $coreDirs[0].Name.Substring(5) }

$leaf = Split-Path -Leaf $SpotfireRoot
$productVersionFull = $leaf
if (-not $ProductVersion) {
  if ($leaf -match '^(\d+)\.(\d+)') { $ProductVersion = $Matches[1] + '.' + $Matches[2] } else { $ProductVersion = 'unknown' }
}
$sourceVersion = ''; $sourceRevision = ''
$infoXml = Join-Path $coreDir 'info.xml'
if (Test-Path -LiteralPath $infoXml) {
  try { [xml]$ix = Get-Content -LiteralPath $infoXml -Raw; $sourceVersion = [string]$ix.info.'source-version'; $sourceRevision = [string]$ix.info.'source-revision' } catch { }
}

Write-Host ("Spotfire root : {0}" -f $SpotfireRoot)
Write-Host ("Core module   : {0}" -f $coreDir)
Write-Host ("Product       : {0} ({1}), core build {2}, source {3} {4}" -f $ProductVersion, $productVersionFull, $coreBuild, $sourceVersion, $sourceRevision)
Write-Host ("Host          : PS {0}, CLR {1}, 64-bit={2}" -f $PSVersionTable.PSVersion, [Environment]::Version, [Environment]::Is64BitProcess)

# --- reflection engine (C# 5, compiled by Add-Type) ----------------------------------------
$csharp = @'
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Resources;
using System.Text;

namespace SfApiDump
{
    public sealed class Json
    {
        private readonly StringBuilder _sb;
        private readonly List<bool> _comma = new List<bool>();
        private bool _afterName;
        private int _pendingNl = -1;

        public Json(StringBuilder sb) { _sb = sb; }

        private void Before()
        {
            if (_afterName) { _afterName = false; return; }
            int n = _comma.Count;
            if (n > 0)
            {
                if (_comma[n - 1]) _sb.Append(',');
                _comma[n - 1] = true;
            }
            if (_pendingNl >= 0) { _sb.Append('\n').Append(' ', _pendingNl); _pendingNl = -1; }
        }

        /// <summary>Newline + indent before the next element (emitted after its comma).</summary>
        public Json NL(int indent) { _pendingNl = indent; return this; }
        /// <summary>Immediate newline + indent (use before a closing bracket).</summary>
        public Json Break(int indent) { _sb.Append('\n').Append(' ', indent); return this; }

        public Json BeginObject() { Before(); _sb.Append('{'); _comma.Add(false); return this; }
        public Json EndObject() { _comma.RemoveAt(_comma.Count - 1); _sb.Append('}'); return this; }
        public Json BeginArray() { Before(); _sb.Append('['); _comma.Add(false); return this; }
        public Json EndArray() { _comma.RemoveAt(_comma.Count - 1); _sb.Append(']'); return this; }
        public Json Name(string name) { Before(); Str(name); _sb.Append(':'); _afterName = true; return this; }
        public Json Value(string s) { Before(); if (s == null) _sb.Append("null"); else Str(s); return this; }
        public Json Value(bool b) { Before(); _sb.Append(b ? "true" : "false"); return this; }
        public Json Value(long v) { Before(); _sb.Append(v.ToString(CultureInfo.InvariantCulture)); return this; }
        public Json Raw(string raw) { Before(); _sb.Append(raw); return this; }
        public Json Null() { Before(); _sb.Append("null"); return this; }

        public Json P(string name, string value) { if (value != null) { Name(name); Value(value); } return this; }
        public Json PB(string name, bool value) { Name(name); Value(value); return this; }
        public Json PT(string name, bool value) { if (value) { Name(name); Value(true); } return this; }
        public Json PN(string name, long value) { Name(name); Value(value); return this; }

        public static string Quote(string s) { StringBuilder b = new StringBuilder(); new Json(b).Str(s); return b.ToString(); }

        private void Str(string s)
        {
            _sb.Append('"');
            for (int i = 0; i < s.Length; i++)
            {
                char c = s[i];
                switch (c)
                {
                    case '"': _sb.Append("\\\""); break;
                    case '\\': _sb.Append("\\\\"); break;
                    case '\n': _sb.Append("\\n"); break;
                    case '\r': _sb.Append("\\r"); break;
                    case '\t': _sb.Append("\\t"); break;
                    case '\b': _sb.Append("\\b"); break;
                    case '\f': _sb.Append("\\f"); break;
                    default:
                        if (c < 0x20 || c == '\u2028' || c == '\u2029' || (c >= '\uD800' && c <= '\uDFFF'))
                            _sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        else
                            _sb.Append(c);
                        break;
                }
            }
            _sb.Append('"');
        }
    }

    public static class Names
    {
        public static string Cs(Type t) { return Cs(t, true); }

        public static string Cs(Type t, bool qualify)
        {
            if (t == null) return null;
            if (t.IsByRef) return Cs(t.GetElementType(), qualify);
            if (t.IsPointer) return Cs(t.GetElementType(), qualify) + "*";
            if (t.IsArray)
            {
                int rank = t.GetArrayRank();
                return Cs(t.GetElementType(), qualify) + "[" + new string(',', rank - 1) + "]";
            }
            if (t.IsGenericParameter) return t.Name;
            if (t.IsGenericType && !t.IsGenericTypeDefinition && t.GetGenericTypeDefinition() == typeof(Nullable<>))
                return Cs(t.GetGenericArguments()[0], qualify) + "?";
            Type[] args = t.IsGenericType ? t.GetGenericArguments() : Type.EmptyTypes;
            return Core(t, args, qualify);
        }

        private static string Core(Type t, Type[] args, bool qualify)
        {
            string prefix;
            int consumed = 0;
            if (t.IsNested && t.DeclaringType != null)
            {
                Type decl = t.DeclaringType;
                int declArity = decl.IsGenericType ? decl.GetGenericArguments().Length : 0;
                if (declArity > args.Length) declArity = args.Length;
                Type[] declArgs = new Type[declArity];
                Array.Copy(args, 0, declArgs, 0, declArity);
                prefix = Core(decl, declArgs, qualify) + ".";
                consumed = declArity;
            }
            else
            {
                prefix = (qualify && !string.IsNullOrEmpty(t.Namespace)) ? t.Namespace + "." : "";
            }
            string name = t.Name;
            int tick = name.IndexOf('`');
            if (tick >= 0) name = name.Substring(0, tick);
            if (args.Length - consumed <= 0) return prefix + name;
            StringBuilder sb = new StringBuilder();
            sb.Append(prefix).Append(name).Append('<');
            for (int i = consumed; i < args.Length; i++)
            {
                if (i > consumed) sb.Append(", ");
                sb.Append(Cs(args[i], qualify));
            }
            sb.Append('>');
            return sb.ToString();
        }

        /// <summary>CLR full name of the (generic definition of the) type, used as lookup id.</summary>
        public static string Id(Type t)
        {
            if (t == null) return null;
            while (t.HasElementType) t = t.GetElementType();
            if (t.IsGenericParameter) return null;
            if (t.IsGenericType && !t.IsGenericTypeDefinition) t = t.GetGenericTypeDefinition();
            return t.FullName;
        }
    }

    internal sealed class Attrs
    {
        public string ApiVersion;
        public bool HasObsolete;
        public string ObsoleteMessage;
        public bool ObsoleteIsError;
        public bool EditorNever;
        public bool SpotfireInternal;
        public string InternalJustification;
        public bool DoNotUseOutsideAssembly;
        public bool IsExtension;
        public bool IsFlags;

        public static Attrs Read(MemberInfo m, List<string> errs, string ctx)
        {
            Attrs a = new Attrs();
            if (m == null) return a;
            IList<CustomAttributeData> list;
            try { list = CustomAttributeData.GetCustomAttributes(m); }
            catch (Exception ex) { if (errs != null) errs.Add(ctx + ": attributes: " + ex.GetType().Name + ": " + ex.Message); return a; }
            foreach (CustomAttributeData cad in list)
            {
                string n;
                try { n = cad.AttributeType.FullName; }
                catch (Exception ex) { if (errs != null) errs.Add(ctx + ": attribute type: " + ex.Message); continue; }
                try
                {
                    switch (n)
                    {
                        case "Spotfire.Dxp.Internal.ApiVersionAttribute":
                            a.ApiVersion = (cad.ConstructorArguments.Count > 0 && cad.ConstructorArguments[0].Value != null)
                                ? Convert.ToString(cad.ConstructorArguments[0].Value, CultureInfo.InvariantCulture) : "";
                            break;
                        case "System.ObsoleteAttribute":
                            a.HasObsolete = true;
                            if (cad.ConstructorArguments.Count > 0) a.ObsoleteMessage = cad.ConstructorArguments[0].Value as string;
                            if (cad.ConstructorArguments.Count > 1 && cad.ConstructorArguments[1].Value is bool) a.ObsoleteIsError = (bool)cad.ConstructorArguments[1].Value;
                            break;
                        case "System.ComponentModel.EditorBrowsableAttribute":
                            if (cad.ConstructorArguments.Count > 0 && cad.ConstructorArguments[0].Value != null
                                && Convert.ToInt32(cad.ConstructorArguments[0].Value, CultureInfo.InvariantCulture) == 1) a.EditorNever = true;
                            break;
                        case "Spotfire.Dxp.Internal.SpotfireInternalAttribute":
                            a.SpotfireInternal = true;
                            foreach (CustomAttributeNamedArgument na in cad.NamedArguments)
                                if (na.MemberName == "Justification" && na.TypedValue.Value != null) a.InternalJustification = na.TypedValue.Value as string;
                            break;
                        case "Spotfire.Dxp.Internal.DoNotUseOutsideAssemblyAttribute": a.DoNotUseOutsideAssembly = true; break;
                        case "System.Runtime.CompilerServices.ExtensionAttribute": a.IsExtension = true; break;
                        case "System.FlagsAttribute": a.IsFlags = true; break;
                    }
                }
                catch (Exception ex) { if (errs != null) errs.Add(ctx + ": attribute " + n + ": " + ex.Message); }
            }
            return a;
        }

        public void MergeFrom(Attrs o)
        {
            if (o == null) return;
            if (ApiVersion == null) ApiVersion = o.ApiVersion;
            if (!HasObsolete && o.HasObsolete) { HasObsolete = true; ObsoleteMessage = o.ObsoleteMessage; ObsoleteIsError = o.ObsoleteIsError; }
            EditorNever |= o.EditorNever;
            if (!SpotfireInternal && o.SpotfireInternal) { SpotfireInternal = true; InternalJustification = o.InternalJustification; }
            DoNotUseOutsideAssembly |= o.DoNotUseOutsideAssembly;
        }

        public void Write(Json j)
        {
            if (ApiVersion != null) j.P("apiVersion", ApiVersion);
            if (HasObsolete) { j.P("obsolete", ObsoleteMessage ?? ""); j.PT("obsoleteIsError", ObsoleteIsError); }
            j.PT("editorBrowsableNever", EditorNever);
            if (SpotfireInternal) { j.PB("spotfireInternal", true); j.P("spotfireInternalJustification", InternalJustification); }
            j.PT("doNotUseOutsideAssembly", DoNotUseOutsideAssembly);
        }
    }

    internal sealed class AsmRec
    {
        public string File, Name, FullName, Version, FileVersion, TargetFramework;
        public int ExportedTypeCount;
        public List<string> LoadErrors = new List<string>();
    }

    internal sealed class TypeRec
    {
        public Type T; public string Asm; public bool External;
        public TypeRec(Type t, string asm, bool external) { T = t; Asm = asm; External = external; }
        public TypeRec(Type t, string asm, bool external) { T = t; Asm = asm; External = external; }
    }

    public static class Dumper
    {
        private const BindingFlags DeclaredPublic = BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
        private static BindingFlags MemberFlags { get { return DeclaredPublic; } }   // public members only

        private static bool Generated(string name) { return name != null && name.IndexOf('<') >= 0; }

        private static readonly Dictionary<string, List<string>> Index = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
        private static bool _hooked;
        public static readonly List<string> Resolved = new List<string>();
        public static readonly List<string> Unresolved = new List<string>();
        public static readonly List<string> Log = new List<string>();

        // ---------------------------------------------------------------- assembly resolution
        public static int BuildIndex(string rootDir, string modulesDir, string coreDir)
        {
            Index.Clear();
            AddDir(coreDir, false);        // Core copies first
            // then module folders of the same product build (e.g. "Third Party Products_<coreBuild>"),
            // then every other module folder (sorted) - so shared third-party DLLs come from this build
            string coreName = Path.GetFileName(coreDir.TrimEnd('\\', '/'));
            int us = coreName.IndexOf('_');
            string buildSuffix = us >= 0 ? coreName.Substring(us) : null;
            string[] subs;
            try { subs = Directory.GetDirectories(modulesDir); } catch { subs = new string[0]; }
            Array.Sort(subs, StringComparer.OrdinalIgnoreCase);
            if (buildSuffix != null)
                foreach (string s in subs) if (s.EndsWith(buildSuffix, StringComparison.OrdinalIgnoreCase)) AddDir(s, true);
            AddDir(modulesDir, true);
            if (!string.IsNullOrEmpty(rootDir)) AddDir(rootDir, false);
            if (!_hooked) { AppDomain.CurrentDomain.AssemblyResolve += OnResolve; _hooked = true; }
            return Index.Count;
        }

        private static void AddDir(string dir, bool recurse)
        {
            string[] files;
            try { files = Directory.GetFiles(dir, "*.dll"); } catch { return; }
            Array.Sort(files, StringComparer.OrdinalIgnoreCase);
            foreach (string f in files)
            {
                string bn = Path.GetFileNameWithoutExtension(f);
                List<string> l;
                if (!Index.TryGetValue(bn, out l)) { l = new List<string>(); Index[bn] = l; }
                bool dup = false;
                foreach (string e in l) if (string.Equals(e, f, StringComparison.OrdinalIgnoreCase)) { dup = true; break; }
                if (!dup) l.Add(f);
            }
            if (!recurse) return;
            string[] subs;
            try { subs = Directory.GetDirectories(dir); } catch { return; }
            Array.Sort(subs, StringComparer.OrdinalIgnoreCase);
            foreach (string s in subs) AddDir(s, true);
        }

        private static void Note(List<string> l, string s) { lock (l) { if (!l.Contains(s)) l.Add(s); } }

        private static Assembly OnResolve(object sender, ResolveEventArgs e)
        {
            AssemblyName req;
            try { req = new AssemblyName(e.Name); } catch { return null; }
            string simple = req.Name;
            if (string.IsNullOrEmpty(simple)) return null;
            if (simple.EndsWith(".resources", StringComparison.OrdinalIgnoreCase) || simple.EndsWith(".XmlSerializers", StringComparison.OrdinalIgnoreCase)) return null;
            foreach (Assembly a in AppDomain.CurrentDomain.GetAssemblies())
            {
                try { if (!a.IsDynamic && string.Equals(a.GetName().Name, simple, StringComparison.OrdinalIgnoreCase)) return a; } catch { }
            }
            List<string> cands;
            string requester = "?";
            try { if (e.RequestingAssembly != null) requester = e.RequestingAssembly.GetName().Name; } catch { }
            if (!Index.TryGetValue(simple, out cands)) { Note(Unresolved, e.Name + "  (requested by " + requester + ")"); return null; }
            string exact = null, best = null; Version bestV = null;
            foreach (string c in cands)
            {
                AssemblyName cn;
                try { cn = AssemblyName.GetAssemblyName(c); } catch { continue; }
                if (req.Version != null && cn.Version != null && cn.Version.Equals(req.Version)) { exact = c; break; }
                if (best == null || (cn.Version != null && bestV != null && cn.Version > bestV)) { best = c; bestV = cn.Version; }
            }
            string pick = exact ?? best;
            if (pick == null) { Note(Unresolved, e.Name + "  (no managed candidate; requested by " + requester + ")"); return null; }
            try
            {
                Assembly r = Assembly.LoadFrom(pick);
                Note(Resolved, simple + " " + (req.Version != null ? req.Version.ToString() : "") + " -> " + pick + (exact == null ? "  [version fallback]" : ""));
                return r;
            }
            catch (Exception ex) { Note(Unresolved, e.Name + " -> " + pick + " : " + ex.Message); return null; }
        }

        // ---------------------------------------------------------------- helpers
        private static Type[] Visible(Type[] ts)
        {
            List<Type> l = new List<Type>();
            foreach (Type t in ts) { if (t == null) continue; try { if (t.IsVisible) l.Add(t); } catch { } }
            return l.ToArray();
        }

        private static string Kind(Type t)
        {
            if (t.IsEnum) return "enum";
            if (t.IsInterface) return "interface";
            if (t.IsValueType) return "struct";
            Type b = t.BaseType;
            if (b != null && (b.FullName == "System.MulticastDelegate" || b.FullName == "System.Delegate") && t.FullName != "System.MulticastDelegate")
                return "delegate";
            return "class";
        }

        private static bool IsOverride(MethodInfo m)
        {
            try { MethodInfo b = m.GetBaseDefinition(); return b != null && b.DeclaringType != m.DeclaringType; } catch { return false; }
        }

        private static string ParamSig(ParameterInfo[] ps)
        {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < ps.Length; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append(Names.Cs(ps[i].ParameterType));
                if (ps[i].ParameterType.IsByRef) sb.Append('&');
            }
            return sb.ToString();
        }

        private static bool HasDefault(ParameterInfo p)
        {
            try { return p.HasDefaultValue; } catch { return false; }
        }

        private static string FormatDefault(ParameterInfo p)
        {
            object v;
            try { v = p.RawDefaultValue; } catch { return "?"; }
            Type pt = p.ParameterType;
            if (pt.IsByRef) pt = pt.GetElementType();
            Type nt = Nullable.GetUnderlyingType(pt);
            if (v == null) return (pt.IsValueType && nt == null) ? "default" : "null";
            if (v is DBNull || v == Missing.Value) return "?";
            if (nt != null) pt = nt;
            if (pt.IsEnum)
            {
                try
                {
                    foreach (FieldInfo f in pt.GetFields(BindingFlags.Public | BindingFlags.Static))
                    {
                        if (!f.IsLiteral) continue;
                        object rv = f.GetRawConstantValue();
                        if (Convert.ToString(rv, CultureInfo.InvariantCulture) == Convert.ToString(v, CultureInfo.InvariantCulture))
                            return pt.Name + "." + f.Name;
                    }
                }
                catch { }
                return "(" + pt.Name + ")" + Convert.ToString(v, CultureInfo.InvariantCulture);
            }
            if (v is string) return Json.Quote((string)v);
            if (v is bool) return ((bool)v) ? "true" : "false";
            if (v is char) return "'" + v + "'";
            if (v is double) return ((double)v).ToString("R", CultureInfo.InvariantCulture);
            if (v is float) return ((float)v).ToString("R", CultureInfo.InvariantCulture);
            return Convert.ToString(v, CultureInfo.InvariantCulture);
        }

        private static bool IsParamArray(ParameterInfo p)
        {
            try { return p.IsDefined(typeof(ParamArrayAttribute), false); } catch { return false; }
        }

        private static void WriteParams(Json j, ParameterInfo[] ps)
        {
            j.BeginArray();
            foreach (ParameterInfo p in ps)
            {
                j.BeginObject();
                j.P("name", p.Name ?? ("arg" + p.Position.ToString(CultureInfo.InvariantCulture)));
                Type pt = p.ParameterType;
                j.P("type", Names.Cs(pt));
                if (pt.IsByRef) { if (p.IsOut && !p.IsIn) j.PB("isOut", true); else j.PB("isRef", true); }
                j.PT("isOptional", p.IsOptional);
                if (HasDefault(p)) j.P("default", FormatDefault(p));
                j.PT("isParams", IsParamArray(p));
                j.EndObject();
            }
            j.EndArray();
        }

        private static void WriteTypeRef(Json j, Type t)
        {
            j.BeginObject();
            j.P("cs", Names.Cs(t));
            j.P("id", Names.Id(t));
            if (t.IsGenericType && !t.IsGenericTypeDefinition)
            {
                j.Name("args").BeginArray();
                foreach (Type a in t.GetGenericArguments()) j.Value(Names.Cs(a));
                j.EndArray();
            }
            j.EndObject();
        }

        private static void WriteGenericParams(Json j, Type[] gps)
        {
            j.BeginArray();
            foreach (Type g in gps)
            {
                j.BeginObject();
                j.P("name", g.Name);
                List<string> cons = new List<string>();
                try { foreach (Type c in g.GetGenericParameterConstraints()) cons.Add(Names.Cs(c)); } catch { }
                GenericParameterAttributes ga = g.GenericParameterAttributes;
                if ((ga & GenericParameterAttributes.ReferenceTypeConstraint) != 0) cons.Insert(0, "class");
                if ((ga & GenericParameterAttributes.NotNullableValueTypeConstraint) != 0) cons.Insert(0, "struct");
                else if ((ga & GenericParameterAttributes.DefaultConstructorConstraint) != 0) cons.Add("new()");
                if (cons.Count > 0) { j.Name("constraints").BeginArray(); foreach (string c in cons) j.Value(c); j.EndArray(); }
                if ((ga & GenericParameterAttributes.Covariant) != 0) j.P("variance", "out");
                if ((ga & GenericParameterAttributes.Contravariant) != 0) j.P("variance", "in");
                j.EndObject();
            }
            j.EndArray();
        }

        private static void WriteLiteral(Json j, object v)
        {
            if (v == null) { j.Null(); return; }
            if (v is string) { j.Value((string)v); return; }
            if (v is bool) { j.Value((bool)v); return; }
            if (v is char) { j.Value(v.ToString()); return; }
            if (v is double || v is float)
            {
                double d = Convert.ToDouble(v, CultureInfo.InvariantCulture);
                if (double.IsNaN(d) || double.IsInfinity(d)) { j.Value(d.ToString(CultureInfo.InvariantCulture)); return; }
                j.Raw(v is double ? ((double)v).ToString("R", CultureInfo.InvariantCulture) : ((float)v).ToString("R", CultureInfo.InvariantCulture));
                return;
            }
            if (v is decimal) { j.Raw(((decimal)v).ToString(CultureInfo.InvariantCulture)); return; }
            if (v is sbyte || v is byte || v is short || v is ushort || v is int || v is uint || v is long || v is ulong)
            { j.Raw(Convert.ToString(v, CultureInfo.InvariantCulture)); return; }
            j.Value(Convert.ToString(v, CultureInfo.InvariantCulture));
        }

        private static string MethodKey(MethodBase m)
        {
            string s;
            try { s = m.Name + "(" + ParamSig(m.GetParameters()) + ")"; } catch { s = m.Name + "(?)"; }
            return s;
        }

        // ---------------------------------------------------------------- type writer
        private static void WriteType(Json j, TypeRec tr, List<string> globalErrs)
        {
            Type t = tr.T;
            List<string> errs = new List<string>();
            string kind = Kind(t);
            j.BeginObject();
            j.P("fullName", t.FullName);
            j.P("assembly", tr.Asm);
            j.PT("external", tr.External);
            j.P("csName", Names.Cs(t));
            j.P("namespace", t.Namespace ?? "");
            j.P("name", t.Name);
            j.P("kind", kind);
            j.PB("isAbstract", t.IsAbstract);
            j.PB("isSealed", t.IsSealed);
            j.PB("isStatic", t.IsClass && t.IsAbstract && t.IsSealed);
            if (t.IsNested && t.DeclaringType != null) j.P("declaringType", t.DeclaringType.FullName);
            try { if (t.BaseType != null) { j.Name("baseType"); WriteTypeRef(j, t.BaseType); } }
            catch (Exception ex) { errs.Add("baseType: " + ex.GetType().Name + ": " + ex.Message); }
            try
            {
                Type[] ifs = t.GetInterfaces();
                List<Type> vis = new List<Type>();
                foreach (Type i in ifs) { try { if (i.IsVisible) vis.Add(i); } catch { } }
                if (vis.Count > 0)
                {
                    vis.Sort(delegate (Type a, Type b) { return string.CompareOrdinal(Names.Cs(a), Names.Cs(b)); });
                    j.Name("interfaces").BeginArray();
                    foreach (Type i in vis) WriteTypeRef(j, i);
                    j.EndArray();
                }
            }
            catch (Exception ex) { errs.Add("interfaces: " + ex.GetType().Name + ": " + ex.Message); }
            if (t.IsGenericTypeDefinition) { j.Name("genericParameters"); WriteGenericParams(j, t.GetGenericArguments()); }
            Attrs ta = Attrs.Read(t, errs, "type");
            ta.Write(j);

            if (kind == "enum") WriteEnum(j, t, ta, errs);
            else if (kind == "delegate") WriteDelegate(j, t, errs);
            else
            {
                WriteCtors(j, t, errs);
                WriteProperties(j, t, errs);
                WriteMethods(j, t, errs);
                WriteFields(j, t, errs);
                WriteEvents(j, t, errs);
                if (t.IsClass || t.IsValueType) WriteExplicit(j, t, errs);
            }
            if (errs.Count > 0)
            {
                j.Name("errors").BeginArray();
                foreach (string e in errs) { j.Value(e); globalErrs.Add(t.FullName + ": " + e); }
                j.EndArray();
            }
            j.EndObject();
        }

        private static void WriteEnum(Json j, Type t, Attrs ta, List<string> errs)
        {
            try
            {
                j.Name("enum").BeginObject();
                j.P("underlyingType", Names.Cs(Enum.GetUnderlyingType(t)));
                j.PB("isFlags", ta.IsFlags);
                List<FieldInfo> fs = new List<FieldInfo>();
                foreach (FieldInfo f in t.GetFields(BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly)) if (f.IsLiteral) fs.Add(f);
                fs.Sort(delegate (FieldInfo a, FieldInfo b) { return a.MetadataToken.CompareTo(b.MetadataToken); });
                j.Name("values").BeginArray();
                foreach (FieldInfo f in fs)
                {
                    j.NL(8).BeginObject();
                    j.P("name", f.Name);
                    j.Name("value");
                    WriteLiteral(j, f.GetRawConstantValue());
                    Attrs.Read(f, errs, "enum " + f.Name).Write(j);
                    j.EndObject();
                }
                j.EndArray();
                j.EndObject();
            }
            catch (Exception ex) { errs.Add("enum: " + ex.GetType().Name + ": " + ex.Message); }
        }

        private static void WriteDelegate(Json j, Type t, List<string> errs)
        {
            try
            {
                MethodInfo inv = t.GetMethod("Invoke");
                if (inv == null) return;
                j.Name("invoke").BeginObject();
                j.P("returnType", Names.Cs(inv.ReturnType));
                j.Name("params"); WriteParams(j, inv.GetParameters());
                j.EndObject();
            }
            catch (Exception ex) { errs.Add("invoke: " + ex.GetType().Name + ": " + ex.Message); }
        }

        private static void WriteCtors(Json j, Type t, List<string> errs)
        {
            ConstructorInfo[] cs;
            try { cs = t.GetConstructors(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly); }
            catch (Exception ex) { errs.Add("ctors: " + ex.GetType().Name + ": " + ex.Message); return; }
            if (cs.Length == 0) return;
            List<ConstructorInfo> l = new List<ConstructorInfo>(cs);
            l.Sort(delegate (ConstructorInfo a, ConstructorInfo b)
            {
                int c = a.GetParameters().Length.CompareTo(b.GetParameters().Length);
                return c != 0 ? c : string.CompareOrdinal(MethodKey(a), MethodKey(b));
            });
            j.Name("ctors").BeginArray();
            foreach (ConstructorInfo c in l)
            {
                try
                {
                    j.NL(6).BeginObject();
                    j.Name("params"); WriteParams(j, c.GetParameters());
                    Attrs.Read(c, errs, "ctor").Write(j);
                    j.EndObject();
                }
                catch (Exception ex) { errs.Add("ctor " + MethodKey(c) + ": " + ex.Message); }
            }
            j.EndArray();
        }

        private static void WriteProperties(Json j, Type t, List<string> errs)
        {
            PropertyInfo[] ps;
            try { ps = t.GetProperties(MemberFlags); }
            catch (Exception ex) { errs.Add("properties: " + ex.GetType().Name + ": " + ex.Message); return; }
            if (ps.Length == 0) return;
            List<PropertyInfo> l = new List<PropertyInfo>(ps);
            l.Sort(delegate (PropertyInfo a, PropertyInfo b)
            {
                int c = string.CompareOrdinal(a.Name, b.Name);
                if (c != 0) return c;
                string sa = "", sb = "";
                try { sa = ParamSig(a.GetIndexParameters()); sb = ParamSig(b.GetIndexParameters()); } catch { }
                return string.CompareOrdinal(sa, sb);
            });
            j.Name("properties").BeginArray();
            foreach (PropertyInfo p in l)
            {
                try
                {
                    if (Generated(p.Name)) continue;
                    MethodInfo g = p.GetGetMethod(false);
                    MethodInfo s = p.GetSetMethod(false);
                    if (g == null && s == null) continue;
                    MethodInfo acc = g ?? s;
                    j.NL(6).BeginObject();
                    j.P("name", p.Name);
                    j.P("type", Names.Cs(p.PropertyType));
                    j.PB("canRead", g != null);
                    j.PB("hasPublicSetter", s != null && s.IsPublic);
                    j.PB("isStatic", acc.IsStatic);
                    if (acc.IsAbstract) j.PB("isAbstract", true);
                    else if (acc.IsVirtual && !acc.IsFinal) j.PB("isVirtual", true);
                    j.PT("isOverride", IsOverride(acc));
                    ParameterInfo[] ip = p.GetIndexParameters();
                    if (ip.Length > 0) { j.Name("indexParams"); WriteParams(j, ip); }
                    Attrs pa = Attrs.Read(p, errs, "property " + p.Name);
                    Attrs ga = g != null ? Attrs.Read(g, errs, "get_" + p.Name) : null;
                    Attrs sa = s != null ? Attrs.Read(s, errs, "set_" + p.Name) : null;
                    pa.MergeFrom(ga);
                    pa.MergeFrom(sa);
                    pa.Write(j);
                    if (sa != null && sa.ApiVersion != null && sa.ApiVersion != pa.ApiVersion) j.P("setApiVersion", sa.ApiVersion);
                    j.EndObject();
                }
                catch (Exception ex) { errs.Add("property " + p.Name + ": " + ex.GetType().Name + ": " + ex.Message); }
            }
            j.EndArray();
        }

        private static void WriteMethodBody(Json j, MethodInfo m, List<string> errs)
        {
            j.P("name", m.Name);
            j.P("returnType", Names.Cs(m.ReturnType));
            j.Name("params"); WriteParams(j, m.GetParameters());
            j.PB("isStatic", m.IsStatic);
            j.PB("isAbstract", m.IsAbstract);
            j.PB("isVirtual", m.IsVirtual && !m.IsFinal);
            j.PT("isOverride", IsOverride(m));
            if (m.IsGenericMethodDefinition) { j.Name("genericParameters"); WriteGenericParams(j, m.GetGenericArguments()); }
            Attrs ma = Attrs.Read(m, errs, "method " + m.Name);
            j.PT("isExtension", ma.IsExtension);
            ma.Write(j);
        }

        private static void WriteMethods(Json j, Type t, List<string> errs)
        {
            MethodInfo[] ms;
            try { ms = t.GetMethods(MemberFlags); }
            catch (Exception ex) { errs.Add("methods: " + ex.GetType().Name + ": " + ex.Message); return; }
            List<MethodInfo> methods = new List<MethodInfo>(), ops = new List<MethodInfo>();
            foreach (MethodInfo m in ms)
            {
                if (Generated(m.Name)) continue;
                if (m.IsSpecialName) { if (m.Name.StartsWith("op_", StringComparison.Ordinal)) ops.Add(m); continue; }
                methods.Add(m);
            }
            Comparison<MethodInfo> cmp = delegate (MethodInfo a, MethodInfo b)
            {
                int c = string.CompareOrdinal(a.Name, b.Name);
                if (c != 0) return c;
                c = a.GetParameters().Length.CompareTo(b.GetParameters().Length);
                return c != 0 ? c : string.CompareOrdinal(MethodKey(a), MethodKey(b));
            };
            methods.Sort(cmp);
            ops.Sort(cmp);
            if (methods.Count > 0)
            {
                j.Name("methods").BeginArray();
                foreach (MethodInfo m in methods)
                {
                    try { j.NL(6).BeginObject(); WriteMethodBody(j, m, errs); j.EndObject(); }
                    catch (Exception ex) { errs.Add("method " + MethodKey(m) + ": " + ex.GetType().Name + ": " + ex.Message); }
                }
                j.EndArray();
            }
            if (ops.Count > 0)
            {
                j.Name("operators").BeginArray();
                foreach (MethodInfo m in ops)
                {
                    try { j.NL(6).BeginObject(); WriteMethodBody(j, m, errs); j.EndObject(); }
                    catch (Exception ex) { errs.Add("operator " + MethodKey(m) + ": " + ex.GetType().Name + ": " + ex.Message); }
                }
                j.EndArray();
            }
        }

        private static void WriteFields(Json j, Type t, List<string> errs)
        {
            FieldInfo[] fs;
            try { fs = t.GetFields(MemberFlags); }
            catch (Exception ex) { errs.Add("fields: " + ex.GetType().Name + ": " + ex.Message); return; }
            if (fs.Length == 0) return;
            List<FieldInfo> l = new List<FieldInfo>(fs);
            l.Sort(new Comparison<FieldInfo>(delegate (FieldInfo a, FieldInfo b) { return string.CompareOrdinal(a.Name, b.Name); }));
            j.Name("fields").BeginArray();
            foreach (FieldInfo f in l)
            {
                try
                {
                    if (Generated(f.Name)) continue;
                    j.NL(6).BeginObject();
                    j.P("name", f.Name);
                    j.P("type", Names.Cs(f.FieldType));
                    j.PB("isStatic", f.IsStatic);
                    j.PB("isLiteral", f.IsLiteral);
                    j.PT("isInitOnly", f.IsInitOnly);
                    if (f.IsLiteral) { j.Name("value"); WriteLiteral(j, f.GetRawConstantValue()); }
                    Attrs.Read(f, errs, "field " + f.Name).Write(j);
                    j.EndObject();
                }
                catch (Exception ex) { errs.Add("field " + f.Name + ": " + ex.GetType().Name + ": " + ex.Message); }
            }
            j.EndArray();
        }

        private static void WriteEvents(Json j, Type t, List<string> errs)
        {
            EventInfo[] es;
            try { es = t.GetEvents(MemberFlags); }
            catch (Exception ex) { errs.Add("events: " + ex.GetType().Name + ": " + ex.Message); return; }
            if (es.Length == 0) return;
            List<EventInfo> l = new List<EventInfo>(es);
            l.Sort(new Comparison<EventInfo>(delegate (EventInfo a, EventInfo b) { return string.CompareOrdinal(a.Name, b.Name); }));
            j.Name("events").BeginArray();
            foreach (EventInfo e in l)
            {
                try
                {
                    MethodInfo add = e.GetAddMethod(false);
                    j.NL(6).BeginObject();
                    j.P("name", e.Name);
                    j.P("type", Names.Cs(e.EventHandlerType));
                    j.PB("isStatic", add != null && add.IsStatic);
                    Attrs.Read(e, errs, "event " + e.Name).Write(j);
                    j.EndObject();
                }
                catch (Exception ex) { errs.Add("event " + e.Name + ": " + ex.GetType().Name + ": " + ex.Message); }
            }
            j.EndArray();
        }

        /// <summary>Interface members implemented explicitly (non-public target) by this type itself.</summary>
        private static void WriteExplicit(Json j, Type t, List<string> errs)
        {
            if (t.IsGenericTypeDefinition) return;
            SortedDictionary<string, bool> names = new SortedDictionary<string, bool>(StringComparer.Ordinal);
            Type[] ifs;
            try { ifs = t.GetInterfaces(); } catch { return; }
            foreach (Type i in ifs)
            {
                try
                {
                    if (!i.IsVisible) continue;
                    InterfaceMapping map = t.GetInterfaceMap(i);
                    for (int k = 0; k < map.TargetMethods.Length; k++)
                    {
                        MethodInfo target = map.TargetMethods[k];
                        if (target == null || target.IsPublic || target.DeclaringType != t) continue;
                        string n = map.InterfaceMethods[k].Name;
                        if (n.StartsWith("get_", StringComparison.Ordinal) || n.StartsWith("set_", StringComparison.Ordinal)) n = n.Substring(4);
                        else if (n.StartsWith("add_", StringComparison.Ordinal)) n = n.Substring(4);
                        else if (n.StartsWith("remove_", StringComparison.Ordinal)) n = n.Substring(7);
                        names[Names.Cs(i) + "." + n] = true;
                    }
                }
                catch (Exception ex) { errs.Add("interface map " + i.Name + ": " + ex.GetType().Name + ": " + ex.Message); }
            }
            if (names.Count == 0) return;
            j.Name("explicitImplementations").BeginArray();
            foreach (string n in names.Keys) j.Value(n);
            j.EndArray();
        }

        // ---------------------------------------------------------------- main entry
        public static string Run(string rootDir, string modulesDir, string coreDir, string outFile,
                                 string productVersion, string productVersionFull, string coreBuild,
                                 string sourceVersion, string sourceRevision, string[] extraFiles, string[] notes)
        {
            Stopwatch sw = Stopwatch.StartNew();
            Log.Clear();
            int idx = BuildIndex(rootDir, modulesDir, coreDir);
            Log.Add("dll index: " + idx + " distinct file names under Modules (+root)");

            List<string> files = new List<string>(Directory.GetFiles(coreDir, "Spotfire.Dxp.*.dll"));
            files.Sort(StringComparer.OrdinalIgnoreCase);
            if (extraFiles != null) foreach (string x in extraFiles) if (!string.IsNullOrEmpty(x)) files.Add(Path.GetFullPath(x));

            List<AsmRec> asms = new List<AsmRec>();
            List<string[]> skipped = new List<string[]>();
            Dictionary<string, TypeRec> types = new Dictionary<string, TypeRec>(StringComparer.Ordinal);
            HashSet<string> dumped = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            foreach (string f in files)
            {
                AssemblyName an;
                try { an = AssemblyName.GetAssemblyName(f); }
                catch (BadImageFormatException) { skipped.Add(new string[] { Path.GetFileName(f), "native image (no CLR manifest)" }); continue; }
                catch (Exception ex) { skipped.Add(new string[] { Path.GetFileName(f), ex.GetType().Name + ": " + ex.Message }); continue; }
                Assembly asm;
                try { asm = Assembly.LoadFrom(f); }
                catch (Exception ex) { skipped.Add(new string[] { Path.GetFileName(f), "load failed: " + ex.GetType().Name + ": " + ex.Message }); continue; }
                AsmRec ar = new AsmRec();
                ar.File = Path.GetFileName(f); ar.Name = an.Name; ar.FullName = an.FullName;
                ar.Version = an.Version != null ? an.Version.ToString() : null;
                try { ar.FileVersion = FileVersionInfo.GetVersionInfo(f).FileVersion; } catch { }
                try
                {
                    foreach (CustomAttributeData cad in CustomAttributeData.GetCustomAttributes(asm))
                        if (cad.AttributeType.FullName == "System.Runtime.Versioning.TargetFrameworkAttribute" && cad.ConstructorArguments.Count > 0)
                            ar.TargetFramework = cad.ConstructorArguments[0].Value as string;
                }
                catch { }
                Type[] exported;
                try { exported = asm.GetExportedTypes(); }
                catch (Exception ex)
                {
                    ar.LoadErrors.Add("GetExportedTypes: " + ex.GetType().Name + ": " + ex.Message);
                    try { exported = Visible(asm.GetTypes()); }
                    catch (ReflectionTypeLoadException rtle)
                    {
                        exported = Visible(rtle.Types);
                        HashSet<string> seen = new HashSet<string>();
                        foreach (Exception le in rtle.LoaderExceptions)
                        {
                            if (le == null) continue;
                            string m = le.GetType().Name + ": " + le.Message;
                            if (seen.Add(m) && seen.Count <= 50) ar.LoadErrors.Add("loader: " + m);
                        }
                        ar.LoadErrors.Add("ReflectionTypeLoadException: kept " + exported.Length + " loadable public types");
                    }
                    catch (Exception ex2) { ar.LoadErrors.Add("GetTypes: " + ex2.GetType().Name + ": " + ex2.Message); exported = new Type[0]; }
                }
                ar.ExportedTypeCount = exported.Length;
                if (exported.Length == 0)
                {
                    skipped.Add(new string[] { ar.File, "managed, but no exported types" + (ar.LoadErrors.Count > 0 ? " (" + string.Join(" | ", ar.LoadErrors.ToArray()) + ")" : "") });
                    continue;
                }
                asms.Add(ar);
                dumped.Add(an.Name);
                foreach (Type t in exported)
                {
                    string key = t.FullName ?? t.Name;
                    if (!types.ContainsKey(key)) types[key] = new TypeRec(t, an.Name, false);
                }
            }

            // closure of inherited base types / interfaces that live outside the dumped assemblies
            Queue<Type> q = new Queue<Type>();
            foreach (TypeRec tr in types.Values) q.Enqueue(tr.T);
            int external = 0;
            while (q.Count > 0)
            {
                Type t = q.Dequeue();
                List<Type> rel = new List<Type>();
                try { if (t.BaseType != null) rel.Add(t.BaseType); } catch { }
                try { rel.AddRange(t.GetInterfaces()); } catch { }
                foreach (Type r0 in rel)
                {
                    try
                    {
                        Type r = (r0.IsGenericType && !r0.IsGenericTypeDefinition) ? r0.GetGenericTypeDefinition() : r0;
                        string k = r.FullName;
                        if (k == null || types.ContainsKey(k) || !r.IsVisible) continue;
                        string asmName = r.Assembly.GetName().Name;
                        types[k] = new TypeRec(r, asmName, !dumped.Contains(asmName));
                        external++;
                        q.Enqueue(r);
                    }
                    catch { }
                }
            }

            List<string> keys = new List<string>(types.Keys);
            keys.Sort(StringComparer.Ordinal);
            Dictionary<string, int> perAsm = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            foreach (TypeRec tr in types.Values) { int c; perAsm.TryGetValue(tr.Asm, out c); perAsm[tr.Asm] = c + 1; }

            StringBuilder sb = new StringBuilder(48 * 1024 * 1024);
            Json j = new Json(sb);
            List<string> globalErrs = new List<string>();
            j.BeginObject();
            j.NL(2).P("schema", "sfapi-index/1");
            j.NL(2).P("product", "Spotfire Analyst");
            j.NL(2).P("productVersion", productVersion);
            j.NL(2).P("productVersionFull", productVersionFull);
            j.NL(2).P("coreBuild", coreBuild);
            j.NL(2).P("coreModule", Path.GetFileName(coreDir.TrimEnd('\\', '/')));
            j.NL(2).P("sourceVersion", sourceVersion);
            j.NL(2).P("sourceRevision", sourceRevision);
            j.NL(2).P("generated", DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture));
            j.NL(2).P("generator", "scripts/dump_api.ps1 (SfApiDump, Assembly.LoadFrom + reflection, DeclaredOnly members)");
            j.NL(2).P("host", "CLR " + Environment.Version + ", 64-bit=" + Environment.Is64BitProcess);
            j.NL(2).Name("conventions").BeginObject()
                .P("typeNames", "csName/type strings are fully-qualified C#-style (System.String, IList<T>, T[], Nullable as T?); byref shown via isOut/isRef")
                .P("members", "declared-only per type; inherited members come from baseType/interfaces chain (resolve via 'id' = CLR full name of the generic definition)")
                .P("apiVersion", "value of Spotfire.Dxp.Internal.ApiVersionAttribute; for properties taken from the property or its accessors (setApiVersion when the setter differs)")
                .P("external", "true for inherited base types/interfaces from assemblies that were not dumped (mscorlib, System, ...)")
                .EndObject();
            if (notes != null && notes.Length > 0)
            {
                j.NL(2).Name("notes").BeginArray();
                foreach (string n in notes) j.Value(n);
                j.EndArray();
            }
            j.NL(2).Name("assemblies").BeginArray();
            foreach (AsmRec ar in asms)
            {
                int tc; perAsm.TryGetValue(ar.Name, out tc);
                j.NL(4).BeginObject();
                j.P("name", ar.Name).P("file", ar.File).P("fullName", ar.FullName).P("version", ar.Version).P("fileVersion", ar.FileVersion).P("targetFramework", ar.TargetFramework);
                j.PN("exportedTypes", ar.ExportedTypeCount);
                j.PN("dumpedTypes", tc);
                j.Name("loadErrors").BeginArray(); foreach (string e in ar.LoadErrors) j.Value(e); j.EndArray();
                j.EndObject();
            }
            j.Break(2).EndArray();
            j.NL(2).Name("externalAssemblies").BeginArray();
            List<string> extNames = new List<string>();
            foreach (KeyValuePair<string, int> kv in perAsm) if (!dumped.Contains(kv.Key)) extNames.Add(kv.Key);
            extNames.Sort(StringComparer.Ordinal);
            foreach (string n in extNames) { j.NL(4).BeginObject().P("name", n).PN("types", perAsm[n]).EndObject(); }
            j.Break(2).EndArray();
            j.NL(2).Name("skipped").BeginArray();
            foreach (string[] s in skipped) { j.NL(4).BeginObject().P("file", s[0]).P("reason", s[1]).EndObject(); }
            j.Break(2).EndArray();

            int written = 0;
            j.NL(2).Name("types").BeginArray();
            foreach (string k in keys)
            {
                TypeRec tr = types[k];
                j.NL(4);
                try { WriteType(j, tr, globalErrs); written++; }
                catch (Exception ex) { globalErrs.Add(k + ": FATAL " + ex.GetType().Name + ": " + ex.Message); }
            }
            j.Break(2).EndArray();

            j.NL(2).Name("resolver").BeginObject();
            j.Name("resolved").BeginArray(); foreach (string s in Resolved) j.NL(6).Value(s); j.Break(4).EndArray();
            j.Name("unresolved").BeginArray(); foreach (string s in Unresolved) j.NL(6).Value(s); j.Break(4).EndArray();
            j.EndObject();
            j.NL(2).Name("memberErrors").BeginArray(); foreach (string s in globalErrs) j.NL(4).Value(s); j.Break(2).EndArray();
            j.Break(0).EndObject();
            sb.Append('\n');

            File.WriteAllText(outFile, sb.ToString(), new UTF8Encoding(false));

            Log.Add("assemblies dumped: " + asms.Count + ", skipped: " + skipped.Count);
            foreach (AsmRec ar in asms) { int tc; perAsm.TryGetValue(ar.Name, out tc); Log.Add("  " + ar.Name + ": " + tc + " types" + (ar.LoadErrors.Count > 0 ? "  (" + ar.LoadErrors.Count + " load errors)" : "")); }
            foreach (string[] s in skipped) Log.Add("  skipped " + s[0] + ": " + s[1]);
            Log.Add("external inherited types added: " + external);
            Log.Add("types written: " + written + ", member errors: " + globalErrs.Count);
            Log.Add("resolver: " + Resolved.Count + " resolved, " + Unresolved.Count + " unresolved");
            Log.Add("json chars: " + sb.Length + ", elapsed ms: " + sw.ElapsedMilliseconds);
            return string.Join("\n", Log.ToArray());
        }

        // ---------------------------------------------------------------- property docs
        public static string ExtractDocs(string dllPath, string outFile)
        {
            Assembly a = Assembly.ReflectionOnlyLoadFrom(dllPath);
            string resName = null;
            foreach (string n in a.GetManifestResourceNames())
                if (n.IndexOf("PropertyDocumentation", StringComparison.OrdinalIgnoreCase) >= 0) { resName = n; break; }
            if (resName == null) return "no *PropertyDocumentation* manifest resource in " + dllPath;

            SortedDictionary<string, string> entries = new SortedDictionary<string, string>(StringComparer.Ordinal);
            string format;
            using (Stream s = a.GetManifestResourceStream(resName))
            {
                if (resName.EndsWith(".resources", StringComparison.OrdinalIgnoreCase))
                {
                    format = "System.Resources (.resources) string table";
                    using (ResourceReader rr = new ResourceReader(s))
                    {
                        IDictionaryEnumerator e = rr.GetEnumerator();
                        while (e.MoveNext())
                            entries[Convert.ToString(e.Key, CultureInfo.InvariantCulture)] = e.Value == null ? null : Convert.ToString(e.Value, CultureInfo.InvariantCulture);
                    }
                }
                else
                {
                    format = "raw stream (UTF-8 text)";
                    using (StreamReader sr = new StreamReader(s, Encoding.UTF8)) entries["_raw"] = sr.ReadToEnd();
                }
            }

            SortedDictionary<string, string> members = new SortedDictionary<string, string>(StringComparer.Ordinal);
            SortedDictionary<string, string> enumValues = new SortedDictionary<string, string>(StringComparer.Ordinal);
            SortedDictionary<string, string> meta = new SortedDictionary<string, string>(StringComparer.Ordinal);
            foreach (KeyValuePair<string, string> kv in entries)
            {
                if (kv.Key.StartsWith("_", StringComparison.Ordinal)) meta[kv.Key] = kv.Value;
                else if (kv.Key.EndsWith(".EnumValues", StringComparison.Ordinal)) enumValues[kv.Key.Substring(0, kv.Key.Length - ".EnumValues".Length)] = kv.Value;
                else members[kv.Key] = kv.Value;
            }

            StringBuilder sb = new StringBuilder();
            Json j = new Json(sb);
            j.BeginObject();
            j.NL(2).Name("_meta").BeginObject();
            j.P("sourceAssembly", a.FullName).P("sourceFile", Path.GetFileName(dllPath)).P("resource", resName).P("resourceFormat", format);
            j.P("extracted", DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture));
            j.P("extractedBy", "scripts/dump_api.ps1");
            j.PN("entryCount", entries.Count).PN("memberCount", members.Count).PN("enumValuesCount", enumValues.Count);
            j.P("layout", "entries = original flat key/value table, unchanged; members = entries keyed 'Full.Type.Name.Member' (doc text); enumValues = '<Full.Type.Name.Member>.EnumValues' entries keyed without the suffix, value split on ','");
            j.Name("resourceHeader").BeginObject();
            foreach (KeyValuePair<string, string> kv in meta) j.P(kv.Key, kv.Value);
            j.EndObject();
            j.EndObject();
            j.NL(2).Name("members").BeginObject();
            foreach (KeyValuePair<string, string> kv in members) { j.NL(4).Name(kv.Key); j.Value(kv.Value); }
            j.Break(2).EndObject();
            j.NL(2).Name("enumValues").BeginObject();
            foreach (KeyValuePair<string, string> kv in enumValues)
            {
                j.NL(4).Name(kv.Key).BeginArray();
                if (kv.Value != null) foreach (string v in kv.Value.Split(',')) j.Value(v.Trim());
                j.EndArray();
            }
            j.Break(2).EndObject();
            j.NL(2).Name("entries").BeginObject();
            foreach (KeyValuePair<string, string> kv in entries) { j.NL(4).Name(kv.Key); j.Value(kv.Value); }
            j.Break(2).EndObject();
            j.Break(0).EndObject();
            sb.Append('\n');
            File.WriteAllText(outFile, sb.ToString(), new UTF8Encoding(false));
            return "property docs: " + entries.Count + " entries (" + members.Count + " member docs, " + enumValues.Count + " enum value lists, " + meta.Count + " header keys) from " + resName;
        }
    }
}
'@

if (-not ('SfApiDump.Dumper' -as [type])) {
  Add-Type -TypeDefinition $csharp -Language CSharp
}

# --- shipped XML doc files (copied verbatim; provenance recorded in the index notes) -------
$notes = New-Object System.Collections.Generic.List[string]
$xmlDocs = @(Get-ChildItem -LiteralPath $modules -Recurse -Filter 'Spotfire.Dxp.*.xml' -ErrorAction SilentlyContinue |
  Where-Object { Test-Path -LiteralPath ([IO.Path]::ChangeExtension($_.FullName, '.dll')) })
foreach ($x in $xmlDocs) {
  $head =Get-Content -LiteralPath $x.FullName -TotalCount 3 -ErrorAction SilentlyContinue
  if (-not ($head -join ' ' -match '<doc>|<\?xml')) { continue }
  $siblingDll = [IO.Path]::ChangeExtension($x.FullName, '.dll')
  $docVer = try { [Reflection.AssemblyName]::GetAssemblyName($siblingDll).Version.ToString() } catch { '?' }
  $coreCopy = Join-Path $coreDir ([IO.Path]::GetFileName($siblingDll))
  $coreVer = if (Test-Path -LiteralPath $coreCopy) { try { [Reflection.AssemblyName]::GetAssemblyName($coreCopy).Version.ToString() } catch { '?' } } else { 'n/a' }
  $dest = Join-Path $OutDir $x.Name
  Copy-Item -LiteralPath $x.FullName -Destination $dest -Force
  $rel = $x.FullName.Substring($modules.Length).TrimStart('\')
  $msg = "XML doc '{0}' copied from Modules\{1}; it documents assembly version {2} (Core copy is {3})" -f $x.Name, $rel, $docVer, $coreVer
  $notes.Add($msg)
  Write-Host $msg
}

# --- API dump --------------------------------------------------------------------------------
$outFile = Join-Path $OutDir ("spotfire-api-{0}.json" -f $coreBuild)
$summary = [SfApiDump.Dumper]::Run($SpotfireRoot, $modules, $coreDir, $outFile, $ProductVersion, $productVersionFull,
  $coreBuild, $sourceVersion, $sourceRevision, [string[]]$ExtraAssembly, $notes.ToArray())
Write-Host $summary
Write-Host ("wrote {0} ({1:N1} MB)" -f $outFile, ((Get-Item -LiteralPath $outFile).Length / 1MB))

# --- embedded property documentation ---------------------------------------------------------
if (-not $SkipDocs) {
  $bridge = @(Get-ChildItem -LiteralPath $modules -Directory | Where-Object { $_.Name -like 'Spotfire.Dxp.ExtensionBridge_*' } |
    Sort-Object @{ Expression = { Get-FolderVersion $_.Name 'Spotfire.Dxp.ExtensionBridge_' } } -Descending)
  if ($bridge.Count -gt 0 -and (Test-Path -LiteralPath (Join-Path $bridge[0].FullName 'Spotfire.Dxp.ExtensionBridge.dll'))) {
    $docsOut = Join-Path $OutDir 'spotfire-property-docs.json'
    $r = [SfApiDump.Dumper]::ExtractDocs((Join-Path $bridge[0].FullName 'Spotfire.Dxp.ExtensionBridge.dll'), $docsOut)
    Write-Host $r
    Write-Host ("wrote {0}" -f $docsOut)
  } else {
    Write-Host 'Spotfire.Dxp.ExtensionBridge module not found; property docs not extracted.'
  }
}
Write-Host ("total elapsed: {0:N1} s" -f $sw.Elapsed.TotalSeconds)
