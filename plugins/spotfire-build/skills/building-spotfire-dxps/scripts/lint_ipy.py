#!/usr/bin/env python3
"""lint_ipy - lint IronPython 3.4 code destined for Spotfire Analyst (CPython 3.10+, stdlib only).

    python scripts/lint_ipy.py <file.py> [<file.py> ...] [--min-version 14.6] [--document-script]
                               [--globals page,visual] [--check-names] [--persisted] [--json]

Lints document scripts (IronPython action/trigger scripts), postScripts, lib/*.py modules and the
generated builder (build/build_<App>.py). Static only: nothing is executed, Spotfire is never started.

Rules
  1. Syntax subset (errors): f-strings and t-strings, walrus ':=', annotations (parameter, return,
     variable), async/await, PEP 448 unpacking (several */** in a call, positional after *, keyword
     after **, * or ** inside list/tuple/set/dict displays), numeric literals with '_', positional-only
     parameters '/', matrix multiply '@', tab characters, attribute access named None/True/False
     ('X.None' is a syntax error in IronPython 3: use getattr(X, "None")). Also newer-than-3.4 syntax
     CPython 3.14 accepts: match, except*, type aliases/parameters, relaxed decorators (3.9),
     'continue' inside 'finally' (3.8), unparenthesized 'except A, B:' (3.14).
     print(...) is an error with --document-script, a warning otherwise.
     BindingFlags.NonPublic is an error: the builders and scripts use Spotfire's public API only.
  2. API members (warnings): every attribute name that starts with an uppercase letter and is not
     defined in the file itself must be a member name of some type in the Spotfire public index
     (spotfire-api-<build>.json from dump_api.ps1: SFAPI_INDEX, else $DXP_WORKSPACE/api/) or the
     explicit BCL allowlist below (System.String, DateTime, IO, Drawing, Reflection, collections, ...).
     Otherwise: "unknown member". Without an index the API checks are skipped with a note. Chains
     rooted at an imported .NET namespace (System.IO.Path.Combine, Spotfire.Dxp.Data.DataType) are
     resolved segment by segment. Attributes of Python modules (json, re, ...) are not checked.
     Two-level check: for X.B.C (and X.B(...).C) the linter collects every type that a member named B
     returns anywhere in the public index, plus all their subclasses/implementers; when none of them
     has a member C the access cannot work ("'C' is not a member of any type returned by '.B'").
  3. Imports: "from Spotfire.X import Y" requires Y to be a public type (or sub-namespace) of namespace
     Spotfire.X per the index (error otherwise, with a hint where Y lives).
  4. Version level: a member name whose every definition is [api] newer than --min-version (default
     14.6) gets "requires Spotfire <version>". Same for imported types. Names whose every public
     definition is [Obsolete] get an "obsolete" warning.
  With --document-script (or --check-names) names that are never bound, imported, star-imported,
  built in or script globals (Document, Application, --globals) are reported as undefined.

Output: one line per finding "file:line:col: error|warning: message [rule]", then a summary line.
Exit code 1 when any error was reported, else 0 (2 for usage errors).
Suppress a finding on one line with "# noqa" or "# noqa: rule1,rule2".
--persisted decodes Spotfire's persisted-string escapes (_x09 = tab) of scripts extracted from a
decompiled DXP before linting.

Limitations (read before trusting a clean result)
  - The member check is name-level: a name that exists on ANY type passes, even when the object at
    hand is a different type. The corpus bug `sp.YAxis.ShowLabels = False` (ShowLabels lives on
    ScaleAxis.Scale, i.e. ScaleBase) passes the name check because ScaleBase/Treemap declare
    ShowLabels; only the two-level check above catches it, and only because every type a member
    named YAxis returns lacks ShowLabels. Deeper chains through variables, indexers, generic
    methods (As[T]()), Object-typed members or BCL objects are not type-checked at all; settability
    (has --set) and overloads are not checked either. Use `scripts/sfapi.py has`/`chain` for that.
  - BCL coverage is the explicit allowlist (BCL_ALLOWLIST): a valid .NET member outside it is
    reported as unknown; add it to the allowlist when that happens.
  - Undefined-name detection is scope-insensitive (a name bound anywhere counts as bound).
  - Python 3.4 runtime library differences (json.JSONDecodeError, str.format_map details, ...) are
    not checked; only syntax.

Python API (used by scripts/dxpgen.py):
  lint_source(source, path="<string>", min_version="14.6", document_script=False,
              script_globals=(), check_names=None, persisted=False) -> [Finding]
  lint_file(path, **same options) -> [Finding];  format_finding(f) -> str;  load_api() -> ApiIndex
  Finding = namedtuple(path, line, col, severity, code, message); line/col are 1-based.
"""
import argparse
import ast
import builtins
import difflib
import glob
import io
import json
import os
import re
import sys
import tokenize
import warnings
from collections import defaultdict, namedtuple
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))
import sfenv  # noqa: E402  (SFAPI_INDEX, $DXP_WORKSPACE/api)
DEFAULT_MIN_VERSION = "14.6"

Finding = namedtuple("Finding", "path line col severity code message")

# Rule codes (shown in brackets, usable in "# noqa: <code>")
R_SYNTAX = "syntax"                # newer-than-3.4 syntax (f-strings, walrus, ...)
R_PARSE = "parse-error"            # the file does not parse at all
R_TAB = "tab"
R_PRINT = "print"
R_NONE_ATTR = "none-attr"          # X.None / X.True / X.False
R_UNKNOWN = "unknown-member"
R_INTERNAL = "internal-member"     # only a non-public member of that name exists
R_RESULT = "member-of-result"      # X.B.C where no type returned by B has C
R_VERSION = "version"
R_OBSOLETE = "obsolete"
R_IMPORT = "import"
R_NONPUBLIC = "non-public-api"     # BindingFlags.NonPublic: reflection into non-public members
R_UNDEFINED = "undefined-name"
R_ENCODING = "encoding"

# ------------------------------------------------------------------------------------------------
# BCL allowlist (explicit). "Namespace.Type" (nested: "Namespace.Outer+Inner") -> member names.
# Only names that really exist on these .NET Framework 4.x types belong here. The type names also
# make namespace chains such as System.IO.Path.Combine resolvable. Extend when a valid member of a
# type Spotfire scripts use is reported as unknown.
# ------------------------------------------------------------------------------------------------
_NAMED_COLORS = (
    "AliceBlue AntiqueWhite Aqua Aquamarine Azure Beige Bisque Black BlanchedAlmond Blue BlueViolet "
    "Brown BurlyWood CadetBlue Chartreuse Chocolate Coral CornflowerBlue Cornsilk Crimson Cyan "
    "DarkBlue DarkCyan DarkGoldenrod DarkGray DarkGreen DarkKhaki DarkMagenta DarkOliveGreen "
    "DarkOrange DarkOrchid DarkRed DarkSalmon DarkSeaGreen DarkSlateBlue DarkSlateGray "
    "DarkTurquoise DarkViolet DeepPink DeepSkyBlue DimGray DodgerBlue Firebrick FloralWhite "
    "ForestGreen Fuchsia Gainsboro GhostWhite Gold Goldenrod Gray Green GreenYellow Honeydew HotPink "
    "IndianRed Indigo Ivory Khaki Lavender LavenderBlush LawnGreen LemonChiffon LightBlue LightCoral "
    "LightCyan LightGoldenrodYellow LightGray LightGreen LightPink LightSalmon LightSeaGreen "
    "LightSkyBlue LightSlateGray LightSteelBlue LightYellow Lime LimeGreen Linen Magenta Maroon "
    "MediumAquamarine MediumBlue MediumOrchid MediumPurple MediumSeaGreen MediumSlateBlue "
    "MediumSpringGreen MediumTurquoise MediumVioletRed MidnightBlue MintCream MistyRose Moccasin "
    "NavajoWhite Navy OldLace Olive OliveDrab Orange OrangeRed Orchid PaleGoldenrod PaleGreen "
    "PaleTurquoise PaleVioletRed PapayaWhip PeachPuff Peru Pink Plum PowderBlue Purple Red RosyBrown "
    "RoyalBlue SaddleBrown Salmon SandyBrown SeaGreen SeaShell Sienna Silver SkyBlue SlateBlue "
    "SlateGray Snow SpringGreen SteelBlue Tan Teal Thistle Tomato Transparent Turquoise Violet Wheat "
    "White WhiteSmoke Yellow YellowGreen")

_NUMERIC = "CompareTo Equals GetTypeCode MaxValue MinValue Parse ToString TryParse"
_FLOATING = _NUMERIC + " Epsilon IsInfinity IsNaN IsNegativeInfinity IsPositiveInfinity NaN NegativeInfinity PositiveInfinity"
_RECT = ("Bottom Ceiling Contains Empty FromLTRB Height Inflate Intersect IntersectsWith IsEmpty Left "
         "Location Offset Right Round Size Top Truncate Union Width X Y")

BCL_ALLOWLIST = {
    # ---- System ---------------------------------------------------------------------------------
    "System.Object": "Equals GetHashCode GetType MemberwiseClone ReferenceEquals ToString",
    "System.String": (
        "Chars Clone Compare CompareOrdinal CompareTo Concat Contains Copy CopyTo Empty EndsWith Equals "
        "Format GetEnumerator GetHashCode GetTypeCode IndexOf IndexOfAny Insert Intern IsInterned "
        "IsNormalized IsNullOrEmpty IsNullOrWhiteSpace Join LastIndexOf LastIndexOfAny Length Normalize "
        "PadLeft PadRight Remove Replace Split StartsWith Substring ToCharArray ToLower "
        "ToLowerInvariant ToString ToUpper ToUpperInvariant Trim TrimEnd TrimStart"),
    "System.StringComparison": ("CurrentCulture CurrentCultureIgnoreCase InvariantCulture "
                                "InvariantCultureIgnoreCase Ordinal OrdinalIgnoreCase"),
    "System.StringComparer": "CurrentCulture CurrentCultureIgnoreCase InvariantCulture InvariantCultureIgnoreCase Ordinal OrdinalIgnoreCase",
    "System.StringSplitOptions": "RemoveEmptyEntries",
    "System.Math": ("Abs Acos Asin Atan Atan2 BigMul Ceiling Cos Cosh DivRem E Exp Floor IEEERemainder "
                    "Log Log10 Max Min PI Pow Round Sign Sin Sinh Sqrt Tan Tanh Truncate"),
    "System.MidpointRounding": "AwayFromZero ToEven",
    "System.DateTime": (
        "Add AddDays AddHours AddMilliseconds AddMinutes AddMonths AddSeconds AddTicks AddYears Compare "
        "CompareTo Date Day DayOfWeek DayOfYear DaysInMonth Equals FromBinary FromFileTime "
        "FromFileTimeUtc FromOADate GetDateTimeFormats Hour IsDaylightSavingTime IsLeapYear Kind "
        "MaxValue Millisecond MinValue Minute Month Now Parse ParseExact Second SpecifyKind Subtract "
        "Ticks TimeOfDay ToBinary ToFileTime ToFileTimeUtc ToLocalTime ToLongDateString "
        "ToLongTimeString ToOADate ToShortDateString ToShortTimeString ToString ToUniversalTime Today "
        "TryParse TryParseExact UtcNow Year"),
    "System.DateTimeKind": "Local Unspecified Utc",
    "System.DayOfWeek": "Friday Monday Saturday Sunday Thursday Tuesday Wednesday",
    "System.DateTimeOffset": (
        "AddDays AddHours AddMinutes AddSeconds Date DateTime FromUnixTimeMilliseconds "
        "FromUnixTimeSeconds LocalDateTime MaxValue MinValue Now Offset Parse ToLocalTime ToString "
        "ToUniversalTime ToUnixTimeMilliseconds ToUnixTimeSeconds TryParse UtcDateTime UtcNow"),
    "System.TimeSpan": (
        "Add Compare CompareTo Days Duration Equals FromDays FromHours FromMilliseconds FromMinutes "
        "FromSeconds FromTicks Hours MaxValue Milliseconds MinValue Minutes Negate Parse ParseExact "
        "Seconds Subtract Ticks TicksPerDay TicksPerHour TicksPerMillisecond TicksPerMinute "
        "TicksPerSecond TotalDays TotalHours TotalMilliseconds TotalMinutes TotalSeconds TryParse "
        "TryParseExact Zero"),
    "System.TimeZoneInfo": (
        "BaseUtcOffset ConvertTime ConvertTimeBySystemTimeZoneId ConvertTimeFromUtc ConvertTimeToUtc "
        "DisplayName FindSystemTimeZoneById GetSystemTimeZones GetUtcOffset Id IsDaylightSavingTime "
        "Local StandardName SupportsDaylightSavingTime Utc"),
    "System.Guid": "CompareTo Empty Equals NewGuid Parse ParseExact ToByteArray ToString TryParse TryParseExact",
    "System.Array": (
        "AsReadOnly BinarySearch Clear Clone ConstrainedCopy ConvertAll Copy CopyTo CreateInstance Empty "
        "Exists Find FindAll FindIndex FindLast FindLastIndex ForEach GetEnumerator GetLength "
        "GetLongLength GetLowerBound GetUpperBound GetValue IndexOf Initialize IsFixedSize IsReadOnly "
        "IsSynchronized LastIndexOf Length LongLength Rank Resize Reverse SetValue Sort SyncRoot "
        "TrueForAll"),
    "System.Enum": "CompareTo Format GetName GetNames GetTypeCode GetUnderlyingType GetValues HasFlag IsDefined Parse ToObject ToString TryParse",
    "System.Type": (
        "Assembly AssemblyQualifiedName Attributes BaseType ContainsGenericParameters DeclaringType "
        "EmptyTypes FullName GenericTypeArguments GetConstructor GetConstructors GetCustomAttributes "
        "GetDefaultMembers GetElementType GetEnumName GetEnumNames GetEnumUnderlyingType GetEnumValues "
        "GetEvent GetEvents GetField GetFields GetGenericArguments GetGenericTypeDefinition GetInterface "
        "GetInterfaces GetMember GetMembers GetMethod GetMethods GetNestedType GetNestedTypes "
        "GetProperties GetProperty GetType GetTypeCode GetTypeFromHandle GUID HasElementType "
        "InvokeMember IsAbstract IsArray IsAssignableFrom IsByRef IsClass IsEnum IsGenericParameter "
        "IsGenericType IsGenericTypeDefinition IsInstanceOfType IsInterface IsNested IsNestedPublic "
        "IsNotPublic IsPrimitive IsPublic IsSealed IsSerializable IsSubclassOf IsValueType IsVisible "
        "MakeArrayType MakeByRefType MakeGenericType Missing Module Name Namespace ReflectedType "
        "TypeHandle UnderlyingSystemType"),
    "System.Activator": "CreateComInstanceFrom CreateInstance CreateInstanceFrom GetObject",
    "System.Convert": (
        "ChangeType DBNull FromBase64CharArray FromBase64String GetTypeCode IsDBNull ToBase64CharArray "
        "ToBase64String ToBoolean ToByte ToChar ToDateTime ToDecimal ToDouble ToInt16 ToInt32 ToInt64 "
        "ToSByte ToSingle ToString ToUInt16 ToUInt32 ToUInt64"),
    "System.Environment": (
        "CommandLine CurrentDirectory Exit ExpandEnvironmentVariables GetCommandLineArgs "
        "GetEnvironmentVariable GetEnvironmentVariables GetFolderPath GetLogicalDrives "
        "Is64BitOperatingSystem Is64BitProcess MachineName NewLine OSVersion ProcessorCount "
        "SetEnvironmentVariable StackTrace SystemDirectory TickCount UserDomainName UserInteractive "
        "UserName Version WorkingSet"),
    "System.Environment+SpecialFolder": (
        "ApplicationData CommonApplicationData CommonDocuments Desktop DesktopDirectory Favorites "
        "LocalApplicationData MyDocuments MyMusic MyPictures Personal ProgramFiles ProgramFilesX86 "
        "Programs Recent Startup System Templates UserProfile Windows"),
    "System.Boolean": "CompareTo Equals FalseString Parse ToString TrueString TryParse",
    "System.Char": (
        "ConvertFromUtf32 ConvertToUtf32 GetNumericValue IsControl IsDigit IsLetter IsLetterOrDigit "
        "IsLower IsNumber IsPunctuation IsSeparator IsSymbol IsUpper IsWhiteSpace MaxValue MinValue "
        "Parse ToLower ToLowerInvariant ToString ToUpper ToUpperInvariant TryParse"),
    "System.Byte": _NUMERIC,
    "System.Int16": _NUMERIC,
    "System.Int32": _NUMERIC,
    "System.Int64": _NUMERIC,
    "System.UInt32": _NUMERIC,
    "System.UInt64": _NUMERIC,
    "System.Single": _FLOATING,
    "System.Double": _FLOATING,
    "System.Decimal": (_NUMERIC + " Add Ceiling Compare Divide Floor GetBits MinusOne Multiply Negate "
                       "One Remainder Round Subtract ToDouble ToInt32 ToInt64 ToSingle Truncate Zero"),
    "System.Nullable": "Compare Equals GetUnderlyingType GetValueOrDefault HasValue Value",
    "System.DBNull": "Value",
    "System.Random": "Next NextBytes NextDouble",
    "System.Uri": (
        "AbsolutePath AbsoluteUri EscapeDataString EscapeUriString Fragment Host IsAbsoluteUri "
        "IsWellFormedUriString LocalPath OriginalString PathAndQuery Port Query Scheme Segments "
        "TryCreate UnescapeDataString UriSchemeHttp UriSchemeHttps"),
    "System.Version": "Build CompareTo Major MajorRevision Minor MinorRevision Parse Revision ToString TryParse",
    "System.Tuple": "Create Item1 Item2 Item3 Item4 Item5 Item6 Item7 Rest",
    "System.Console": "Error Out Write WriteLine",
    "System.GC": "Collect GetTotalMemory WaitForPendingFinalizers",
    "System.BitConverter": "GetBytes IsLittleEndian ToBoolean ToDouble ToInt16 ToInt32 ToInt64 ToSingle ToString",
    "System.IntPtr": "Size ToInt32 ToInt64 Zero",
    "System.AppDomain": "BaseDirectory CurrentDomain FriendlyName GetAssemblies",
    "System.Delegate": "BeginInvoke Clone Combine CreateDelegate DynamicInvoke EndInvoke Invoke Method Remove Target",
    "System.EventArgs": "Empty",
    "System.Action": "BeginInvoke EndInvoke Invoke",
    "System.Func": "BeginInvoke EndInvoke Invoke",
    "System.Lazy": "IsValueCreated Value",
    "System.Exception": "Data GetBaseException HResult HelpLink InnerException Message Source StackTrace TargetSite",
    "System.AggregateException": "Flatten Handle InnerExceptions",
    "System.ArgumentException": "ParamName",
    "System.ArgumentNullException": "",
    "System.ArgumentOutOfRangeException": "ActualValue",
    "System.ApplicationException": "",
    "System.DivideByZeroException": "",
    "System.FormatException": "",
    "System.IndexOutOfRangeException": "",
    "System.InvalidCastException": "",
    "System.InvalidOperationException": "",
    "System.NotImplementedException": "",
    "System.NotSupportedException": "",
    "System.NullReferenceException": "",
    "System.OperationCanceledException": "CancellationToken",
    "System.OverflowException": "",
    "System.TimeoutException": "",
    "System.UnauthorizedAccessException": "",
    # ---- System.IO ------------------------------------------------------------------------------
    "System.IO.File": (
        "AppendAllLines AppendAllText AppendText Copy Create CreateText Delete Exists GetAttributes "
        "GetCreationTime GetLastAccessTime GetLastWriteTime Move Open OpenRead OpenText OpenWrite "
        "ReadAllBytes ReadAllLines ReadAllText ReadLines Replace SetAttributes SetLastWriteTime "
        "WriteAllBytes WriteAllLines WriteAllText"),
    "System.IO.Path": (
        "AltDirectorySeparatorChar ChangeExtension Combine DirectorySeparatorChar GetDirectoryName "
        "GetExtension GetFileName GetFileNameWithoutExtension GetFullPath GetInvalidFileNameChars "
        "GetInvalidPathChars GetPathRoot GetRandomFileName GetTempFileName GetTempPath HasExtension "
        "IsPathRooted PathSeparator VolumeSeparatorChar"),
    "System.IO.Directory": (
        "CreateDirectory Delete EnumerateDirectories EnumerateFiles EnumerateFileSystemEntries Exists "
        "GetCreationTime GetCurrentDirectory GetDirectories GetDirectoryRoot GetFiles "
        "GetFileSystemEntries GetLastAccessTime GetLastWriteTime GetLogicalDrives GetParent Move "
        "SetCurrentDirectory"),
    "System.IO.FileInfo": (
        "AppendText CopyTo Create CreateText Delete Directory DirectoryName Exists Extension FullName "
        "IsReadOnly LastAccessTime LastWriteTime Length MoveTo Name Open OpenRead OpenText OpenWrite "
        "Refresh Replace"),
    "System.IO.DirectoryInfo": (
        "Create CreateSubdirectory Delete EnumerateDirectories EnumerateFiles Exists Extension FullName "
        "GetDirectories GetFiles GetFileSystemInfos LastWriteTime MoveTo Name Parent Refresh Root"),
    "System.IO.Stream": (
        "BeginRead BeginWrite CanRead CanSeek CanTimeout CanWrite Close CopyTo CopyToAsync Dispose "
        "EndRead EndWrite Flush FlushAsync Length Null Position Read ReadAsync ReadByte ReadTimeout Seek "
        "SetLength Write WriteAsync WriteByte WriteTimeout"),
    "System.IO.MemoryStream": "Capacity GetBuffer ToArray TryGetBuffer WriteTo",
    "System.IO.FileStream": "Handle IsAsync Name SafeFileHandle",
    "System.IO.TextReader": "Close Dispose Null Peek Read ReadAsync ReadBlock ReadLine ReadLineAsync ReadToEnd ReadToEndAsync",
    "System.IO.StreamReader": "BaseStream CurrentEncoding DiscardBufferedData EndOfStream",
    "System.IO.StringReader": "",
    "System.IO.TextWriter": "Close Dispose Encoding Flush FlushAsync FormatProvider NewLine Null Write WriteAsync WriteLine WriteLineAsync",
    "System.IO.StreamWriter": "AutoFlush BaseStream",
    "System.IO.StringWriter": "GetStringBuilder",
    "System.IO.BinaryReader": "BaseStream Close ReadBoolean ReadByte ReadBytes ReadChars ReadDouble ReadInt16 ReadInt32 ReadInt64 ReadSingle ReadString",
    "System.IO.BinaryWriter": "BaseStream Close Flush Seek Write",
    "System.IO.SeekOrigin": "Begin Current End",
    "System.IO.FileMode": "Append Create CreateNew Open OpenOrCreate Truncate",
    "System.IO.FileAccess": "Read ReadWrite Write",
    "System.IO.FileShare": "Delete Inheritable Read ReadWrite Write",
    "System.IO.SearchOption": "AllDirectories TopDirectoryOnly",
    "System.IO.IOException": "",
    "System.IO.FileNotFoundException": "FileName FusionLog",
    "System.IO.DirectoryNotFoundException": "",
    # ---- System.Text ----------------------------------------------------------------------------
    "System.Text.Encoding": (
        "ASCII BigEndianUnicode BodyName CodePage Convert Default EncodingName GetByteCount GetBytes "
        "GetCharCount GetChars GetDecoder GetEncoder GetEncoding GetEncodings GetMaxByteCount "
        "GetMaxCharCount GetPreamble GetString HeaderName IsSingleByte Unicode UTF32 UTF7 UTF8 WebName"),
    "System.Text.UTF8Encoding": "",
    "System.Text.UnicodeEncoding": "",
    "System.Text.ASCIIEncoding": "",
    "System.Text.StringBuilder": "Append AppendFormat AppendLine Capacity Chars Clear CopyTo EnsureCapacity Insert Length MaxCapacity Remove Replace ToString",
    "System.Text.RegularExpressions.Regex": "CacheSize Escape GetGroupNames GetGroupNumbers IsMatch Match Matches Options Replace RightToLeft Split Unescape",
    "System.Text.RegularExpressions.Match": "Captures Empty Groups Index Length NextMatch Result Success Value",
    "System.Text.RegularExpressions.Group": "Captures Index Length Name Success Value",
    "System.Text.RegularExpressions.MatchCollection": "Count Item",
    "System.Text.RegularExpressions.GroupCollection": "Count Item",
    "System.Text.RegularExpressions.RegexOptions": ("Compiled CultureInvariant ECMAScript ExplicitCapture IgnoreCase "
                                                    "IgnorePatternWhitespace Multiline RightToLeft Singleline"),
    # ---- System.Drawing -------------------------------------------------------------------------
    "System.Drawing.Color": ("A B G R Empty FromArgb FromKnownColor FromName GetBrightness GetHue "
                             "GetSaturation IsEmpty IsKnownColor IsNamedColor IsSystemColor Name ToArgb "
                             "ToKnownColor " + _NAMED_COLORS),
    "System.Drawing.ColorTranslator": "FromHtml FromOle FromWin32 ToHtml ToOle ToWin32",
    "System.Drawing.Image": (
        "Clone Dispose Flags FromFile FromHbitmap FromStream GetBounds GetThumbnailImage Height "
        "HorizontalResolution Palette PhysicalDimension PixelFormat RawFormat RotateFlip Save Size Tag "
        "VerticalResolution Width"),
    "System.Drawing.Bitmap": "GetPixel LockBits MakeTransparent SetPixel SetResolution UnlockBits",
    "System.Drawing.Graphics": (
        "Clear Clip ClipBounds CompositingMode CompositingQuality Dispose DpiX DpiY DrawArc DrawBezier "
        "DrawCurve DrawEllipse DrawIcon DrawImage DrawImageUnscaled DrawLine DrawLines DrawPath DrawPie "
        "DrawPolygon DrawRectangle DrawRectangles DrawString FillClosedCurve FillEllipse FillPath "
        "FillPie FillPolygon FillRectangle FillRectangles FillRegion Flush FromHdc FromHwnd FromImage "
        "InterpolationMode MeasureString PageScale PageUnit PixelOffsetMode ResetClip ResetTransform "
        "Restore RotateTransform Save ScaleTransform SetClip SmoothingMode TextRenderingHint Transform "
        "TranslateTransform VisibleClipBounds"),
    "System.Drawing.Rectangle": _RECT,
    "System.Drawing.RectangleF": _RECT,
    "System.Drawing.Size": "Add Ceiling Empty Height IsEmpty Round Subtract Truncate Width",
    "System.Drawing.SizeF": "Add Empty Height IsEmpty Subtract ToPointF ToSize Width",
    "System.Drawing.Point": "Add Ceiling Empty IsEmpty Offset Round Subtract Truncate X Y",
    "System.Drawing.PointF": "Add Empty IsEmpty Subtract X Y",
    "System.Drawing.Font": "Bold Clone Dispose FontFamily GetHeight Height Italic Name Size SizeInPoints Strikeout Style Underline Unit",
    "System.Drawing.FontFamily": "Families GenericMonospace GenericSansSerif GenericSerif Name",
    "System.Drawing.FontStyle": "Bold Italic Regular Strikeout Underline",
    "System.Drawing.GraphicsUnit": "Display Document Inch Millimeter Pixel Point World",
    "System.Drawing.Brush": "Clone Dispose",
    "System.Drawing.SolidBrush": "Color",
    "System.Drawing.Pen": "Alignment Brush Clone Color DashStyle Dispose EndCap LineJoin StartCap Width",
    "System.Drawing.Brushes": _NAMED_COLORS,
    "System.Drawing.Pens": _NAMED_COLORS,
    "System.Drawing.StringFormat": "Alignment FormatFlags GenericDefault GenericTypographic LineAlignment Trimming",
    "System.Drawing.StringAlignment": "Center Far Near",
    "System.Drawing.Imaging.ImageFormat": "Bmp Emf Exif Gif Guid Icon Jpeg MemoryBmp Png Tiff Wmf",
    "System.Drawing.Imaging.PixelFormat": "Format16bppRgb565 Format24bppRgb Format32bppArgb Format32bppPArgb Format32bppRgb Format8bppIndexed",
    "System.Drawing.Drawing2D.SmoothingMode": "AntiAlias Default HighQuality HighSpeed Invalid",
    "System.Drawing.Drawing2D.InterpolationMode": "Bicubic Bilinear Default High HighQualityBicubic HighQualityBilinear Low NearestNeighbor",
    "System.Drawing.Drawing2D.DashStyle": "Custom Dash DashDot DashDotDot Dot Solid",
    "System.Drawing.Text.TextRenderingHint": "AntiAlias AntiAliasGridFit ClearTypeGridFit SingleBitPerPixel SingleBitPerPixelGridFit SystemDefault",
    # ---- System.Reflection (reflection members used by lib/00_core.py) ------------------------
    "System.Reflection.BindingFlags": (
        "CreateInstance DeclaredOnly Default ExactBinding FlattenHierarchy GetField "
        "GetProperty IgnoreCase IgnoreReturn Instance InvokeMethod NonPublic OptionalParamBinding Public "
        "PutDispProperty PutRefDispProperty SetField SetProperty Static SuppressChangeType"),
    "System.Reflection.MemberInfo": "DeclaringType GetCustomAttributes IsDefined MemberType MetadataToken Module Name ReflectedType",
    "System.Reflection.PropertyInfo": "CanRead CanWrite GetAccessors GetGetMethod GetIndexParameters GetMethod GetSetMethod GetValue PropertyType SetMethod SetValue",
    "System.Reflection.MethodInfo": (
        "GetBaseDefinition GetGenericArguments GetParameters Invoke IsAbstract IsGenericMethod "
        "IsGenericMethodDefinition IsPrivate IsPublic IsStatic IsVirtual MakeGenericMethod "
        "ReturnParameter ReturnType"),
    "System.Reflection.ConstructorInfo": "GetParameters Invoke",
    "System.Reflection.FieldInfo": "FieldType GetRawConstantValue GetValue IsInitOnly IsLiteral IsPublic IsStatic SetValue",
    "System.Reflection.ParameterInfo": "DefaultValue HasDefaultValue IsOptional IsOut Name ParameterType Position",
    "System.Reflection.Assembly": (
        "CodeBase CreateInstance EntryPoint FullName GetAssembly GetCallingAssembly GetCustomAttributes "
        "GetEntryAssembly GetExecutingAssembly GetExportedTypes GetManifestResourceNames "
        "GetManifestResourceStream GetName GetReferencedAssemblies GetType GetTypes "
        "ImageRuntimeVersion Load LoadFile LoadFrom Location"),
    "System.Reflection.AssemblyName": "CultureInfo FullName GetPublicKeyToken Name Version",
    "System.Reflection.TargetInvocationException": "",
    # ---- System.Collections ---------------------------------------------------------------------
    "System.Collections.Generic.List": (
        "Add AddRange AsReadOnly BinarySearch Capacity Clear Contains ConvertAll CopyTo Count Exists "
        "Find FindAll FindIndex FindLast FindLastIndex ForEach GetEnumerator GetRange IndexOf Insert "
        "InsertRange Item LastIndexOf Remove RemoveAll RemoveAt RemoveRange Reverse Sort ToArray "
        "TrimExcess TrueForAll"),
    "System.Collections.Generic.Dictionary": "Add Clear Comparer ContainsKey ContainsValue Count GetEnumerator Item Keys Remove TryGetValue Values",
    "System.Collections.Generic.KeyValuePair": "Key Value",
    "System.Collections.Generic.HashSet": (
        "Add Clear Contains CopyTo Count ExceptWith IntersectWith IsProperSubsetOf IsProperSupersetOf "
        "IsSubsetOf IsSupersetOf Overlaps Remove RemoveWhere SetEquals SymmetricExceptWith UnionWith"),
    "System.Collections.Generic.Queue": "Clear Contains Count Dequeue Enqueue Peek ToArray",
    "System.Collections.Generic.Stack": "Clear Contains Count Peek Pop Push ToArray",
    "System.Collections.Generic.SortedDictionary": "Add Clear ContainsKey ContainsValue Count Item Keys Remove TryGetValue Values",
    "System.Collections.Generic.IEnumerable": "GetEnumerator",
    "System.Collections.Generic.IEnumerator": "Current Dispose MoveNext Reset",
    "System.Collections.Generic.KeyNotFoundException": "",
    "System.Collections.ArrayList": "Add AddRange Clear Contains Count IndexOf Insert Item Remove RemoveAt Reverse Sort ToArray",
    "System.Collections.Hashtable": "Add Clear Contains ContainsKey ContainsValue Count Item Keys Remove Values",
    # ---- System.Globalization -------------------------------------------------------------------
    "System.Globalization.CultureInfo": (
        "Calendar ClearCachedData CompareInfo CreateSpecificCulture CurrentCulture CurrentUICulture "
        "DateTimeFormat DefaultThreadCurrentCulture DefaultThreadCurrentUICulture DisplayName "
        "EnglishName GetCultureInfo GetCultures InstalledUICulture InvariantCulture IsNeutralCulture "
        "LCID Name NativeName NumberFormat Parent TextInfo ThreeLetterISOLanguageName "
        "TwoLetterISOLanguageName"),
    "System.Globalization.NumberFormatInfo": (
        "CurrencyDecimalSeparator CurrencyGroupSeparator CurrencySymbol CurrentInfo InvariantInfo "
        "NaNSymbol NegativeSign NumberDecimalDigits NumberDecimalSeparator NumberGroupSeparator "
        "PercentSymbol PositiveSign"),
    "System.Globalization.DateTimeFormatInfo": (
        "AbbreviatedDayNames AbbreviatedMonthNames CurrentInfo DayNames FirstDayOfWeek "
        "FullDateTimePattern GetAbbreviatedMonthName GetDayName GetMonthName InvariantInfo "
        "LongDatePattern LongTimePattern MonthNames ShortDatePattern ShortTimePattern"),
    "System.Globalization.NumberStyles": (
        "AllowCurrencySymbol AllowDecimalPoint AllowExponent AllowHexSpecifier AllowLeadingSign "
        "AllowLeadingWhite AllowParentheses AllowThousands AllowTrailingSign AllowTrailingWhite Any "
        "Currency Float HexNumber Integer Number"),
    "System.Globalization.DateTimeStyles": (
        "AdjustToUniversal AllowInnerWhite AllowLeadingWhite AllowTrailingWhite AllowWhiteSpaces "
        "AssumeLocal AssumeUniversal NoCurrentDateDefault RoundtripKind"),
    "System.Globalization.TextInfo": "ToLower ToTitleCase ToUpper",
    "System.Globalization.CompareInfo": "Compare IndexOf IsPrefix IsSuffix",
    "System.Globalization.CompareOptions": "IgnoreCase IgnoreNonSpace Ordinal OrdinalIgnoreCase",
    "System.Globalization.Calendar": "GetDayOfWeek GetWeekOfYear",
    "System.Globalization.CalendarWeekRule": "FirstDay FirstFourDayWeek FirstFullWeek",
    # ---- System.Threading / System.Diagnostics --------------------------------------------------
    "System.Threading.Thread": "CurrentCulture CurrentThread CurrentUICulture IsAlive IsBackground Join ManagedThreadId Name Sleep Start",
    "System.Threading.Tasks.Task": "ContinueWith Factory IsCompleted Result Run Start Wait WaitAll",
    "System.Diagnostics.Stopwatch": "Elapsed ElapsedMilliseconds ElapsedTicks Frequency GetTimestamp IsHighResolution IsRunning Reset Restart Start StartNew Stop",
    "System.Diagnostics.Process": "ExitCode GetCurrentProcess GetProcessesByName HasExited Id Kill ProcessName Start StartInfo WaitForExit",
    "System.Diagnostics.ProcessStartInfo": "Arguments CreateNoWindow FileName RedirectStandardOutput UseShellExecute WorkingDirectory",
    "System.Diagnostics.Debug": "Assert Fail Print Write WriteLine",
    "System.Diagnostics.Trace": "Flush TraceError TraceInformation TraceWarning Write WriteLine",
    # ---- System.Net / System.Web ----------------------------------------------------------------
    "System.Net.WebClient": (
        "BaseAddress Credentials Dispose DownloadData DownloadFile DownloadString Encoding Headers Proxy "
        "QueryString UploadData UploadFile UploadString UploadValues UseDefaultCredentials"),
    "System.Net.WebRequest": "ContentLength ContentType Create Credentials DefaultWebProxy GetRequestStream GetResponse Headers Method PreAuthenticate Proxy Timeout UseDefaultCredentials",
    "System.Net.HttpWebRequest": "Accept KeepAlive UserAgent",
    "System.Net.WebResponse": "Close ContentLength ContentType GetResponseStream Headers ResponseUri",
    "System.Net.HttpWebResponse": "StatusCode StatusDescription",
    "System.Net.ServicePointManager": "SecurityProtocol ServerCertificateValidationCallback",
    "System.Net.SecurityProtocolType": "Ssl3 SystemDefault Tls Tls11 Tls12 Tls13",
    "System.Net.CredentialCache": "DefaultCredentials DefaultNetworkCredentials",
    "System.Net.NetworkCredential": "Domain Password UserName",
    "System.Net.WebUtility": "HtmlDecode HtmlEncode UrlDecode UrlEncode",
    "System.Net.WebException": "Response Status",
    "System.Net.HttpStatusCode": "Accepted BadRequest Created Forbidden InternalServerError NoContent NotFound OK Unauthorized",
    "System.Web.HttpUtility": "HtmlAttributeEncode HtmlDecode HtmlEncode JavaScriptStringEncode ParseQueryString UrlDecode UrlEncode UrlPathEncode",
    # ---- System.Windows.Forms (Analyst only) ----------------------------------------------------
    "System.Windows.Forms.MessageBox": "Show",
    "System.Windows.Forms.MessageBoxButtons": "AbortRetryIgnore OK OKCancel RetryCancel YesNo YesNoCancel",
    "System.Windows.Forms.MessageBoxIcon": "Asterisk Error Exclamation Hand Information Question Stop Warning",
    "System.Windows.Forms.DialogResult": "Abort Cancel Ignore No OK Retry Yes",
    "System.Windows.Forms.Clipboard": "Clear ContainsText GetDataObject GetText SetDataObject SetText",
    "System.Windows.Forms.OpenFileDialog": "CheckFileExists DefaultExt FileName FileNames Filter FilterIndex InitialDirectory Multiselect ShowDialog Title",
    "System.Windows.Forms.SaveFileDialog": "DefaultExt FileName Filter FilterIndex InitialDirectory OverwritePrompt ShowDialog Title",
    "System.Windows.Forms.FolderBrowserDialog": "Description SelectedPath ShowDialog ShowNewFolderButton",
    # ---- System.Linq (after clr.ImportExtensions(System.Linq)) / System.Xml ---------------------
    "System.Linq.Enumerable": (
        "Aggregate All Any AsEnumerable Average Cast Concat Contains Count DefaultIfEmpty Distinct "
        "ElementAt ElementAtOrDefault Empty Except First FirstOrDefault GroupBy GroupJoin Intersect Join "
        "Last LastOrDefault LongCount Max Min OfType OrderBy OrderByDescending Range Repeat Reverse "
        "Select SelectMany SequenceEqual Single SingleOrDefault Skip SkipWhile Sum Take TakeWhile ThenBy "
        "ThenByDescending ToArray ToDictionary ToList ToLookup Union Where Zip"),
    "System.Xml.XmlDocument": "CreateAttribute CreateElement CreateTextNode DocumentElement GetElementsByTagName Load LoadXml Save",
    "System.Xml.XmlNode": (
        "AppendChild Attributes ChildNodes FirstChild InnerText InnerXml LastChild LocalName Name "
        "NextSibling NodeType OuterXml ParentNode PreviousSibling RemoveChild SelectNodes "
        "SelectSingleNode Value"),
    "System.Xml.XmlElement": "GetAttribute HasAttribute RemoveAttribute SetAttribute",
}

# IronPython-provided members (not types in a namespace).
IRONPYTHON_ALLOWLIST = {
    "clr module": (
        "AddReference AddReferenceByName AddReferenceByPartialName AddReferenceToFile "
        "AddReferenceToFileAndPath ClearProfilerData CompileModules CompileSubclassTypes Convert Deref "
        "Dir DirClr EnableProfiler GetBytes GetClrType GetCurrentRuntime GetProfilerData GetPythonType "
        "GetString GetSubclassedTypes ImportExtensions IsNetCoreApp LoadAssemblyByName "
        "LoadAssemblyByPartialName LoadAssemblyFromFile LoadAssemblyFromFileWithPath Reference "
        "References SetCommandDispatcher StrongBox Use"),
    "method objects": "Overloads Targets",
}

DOTNET_ROOTS = frozenset(("System", "Spotfire", "Microsoft", "IronPython", "Newtonsoft"))
SCRIPT_GLOBALS = ("Document", "Application")
EXTRA_BUILTINS = frozenset(("__file__", "__builtins__", "__name__", "__doc__"))
_KEYWORD_ATTRS = ("None", "True", "False")
_NOQA_RE = re.compile(r"#\s*noqa\b(?::\s*([A-Za-z0-9_\-, ]+))?", re.IGNORECASE)
_PERSISTED_RE = re.compile(r"_x([0-1][0-9A-Fa-f]|7[Ff]|5[Ff])")


# ------------------------------------------------------------------------------------------------
# versions
# ------------------------------------------------------------------------------------------------
def parse_version(text):
    """'14.6' / '14.6.0' / '15' -> (14, 6, 0); None/'' -> None."""
    if not text:
        return None
    parts = []
    for p in str(text).strip().split("."):
        if not p.isdigit():
            raise ValueError("bad version: %r" % text)
        parts.append(int(p))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def format_version(v):
    if not v:
        return "?"
    return "%d.%d" % v[:2] if v[2] == 0 else "%d.%d.%d" % v


_ZERO = (0, 0, 0)


# ------------------------------------------------------------------------------------------------
# API index (loaded once per process, cached)
# ------------------------------------------------------------------------------------------------
def _build_key(p):
    m = re.search(r"-([\d.]+)\.json$", p.name)
    return tuple(int(x) for x in m.group(1).split(".") if x) if m else ()


def find_index_files(public=None, internal=None):
    """(public index path or None, None). The internal argument is accepted and ignored: the linter
    reads the public index only."""
    if public is None:
        public = sfenv.api_index()      # SFAPI_INDEX, else the newest one in $DXP_WORKSPACE/api/
    public = Path(public) if public else None
    return public, None


def _short(name):
    return name.split("`")[0]


def _ns_prefixes(ns):
    parts = ns.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts) + 1)]


class _TypeGraph(object):
    """Public-index type graph for the two-level (X.B.C) check. Built lazily."""

    def __init__(self, types):
        self.by_id = {}
        self.by_cs = {}
        self.children = defaultdict(list)
        self.declared = defaultdict(set)
        self.results = defaultdict(list)       # member name -> [(kind, type string or type id)]
        for t in types:
            self.by_id[t["fullName"]] = t
            self.by_cs.setdefault(t.get("csName") or t["fullName"], t)
        for t in types:
            full = t["fullName"]
            base = t.get("baseType")
            if base and base.get("id"):
                self.children[base["id"]].append(full)
            for i in t.get("interfaces", []):
                if i.get("id"):
                    self.children[i["id"]].append(full)
            names = self.declared[full]
            for p in t.get("properties", []):
                names.add(p["name"])
                self.results[p["name"]].append(("property", p.get("type")))
            for f in t.get("fields", []):
                names.add(f["name"])
                self.results[f["name"]].append(("field", f.get("type")))
            for m in t.get("methods", []):
                names.add(m["name"])
                self.results[m["name"]].append(("method", m.get("returnType")))
            for e in t.get("events", []):
                names.add(e["name"])
                self.results[e["name"]].append(("event", None))
            for v in (t.get("enum") or {}).get("values", []):
                names.add(v["name"])
                self.results[v["name"]].append(("enum", full))
            if t.get("declaringType"):
                short = _short(t["name"])
                self.declared[t["declaringType"]].add(short)
                self.results[short].append(("nested", full))
        self._available = {}
        self._expand = {}

    def resolve(self, kind, ref):
        if ref is None:
            return None
        if kind in ("enum", "nested"):
            return self.by_id.get(ref)
        ref = ref.strip()
        if ref.endswith("?"):
            ref = ref[:-1]
        if "<" in ref or "[" in ref or "`" in ref:
            return None                            # generic or array: element type unknown here
        return self.by_cs.get(ref) or self.by_id.get(ref)

    def available(self, full, _depth=0):
        """Member names reachable on a type (declared + base chain + interfaces); None = unknown."""
        if full in self._available:
            return self._available[full]
        t = self.by_id.get(full)
        if t is None or _depth > 60:
            return None
        self._available[full] = None               # cycle guard
        names = set(self.declared.get(full, ()))
        refs = []
        if t.get("baseType") and t["baseType"].get("id"):
            refs.append(t["baseType"]["id"])
        refs.extend(i["id"] for i in t.get("interfaces", []) if i.get("id"))
        for ref in refs:
            sub = self.available(ref, _depth + 1)
            if sub is None:
                self._available.pop(full, None)
                return None
            names |= sub
        self._available[full] = names
        return names

    def expand(self, full):
        """The type plus every subclass / implementer (transitively)."""
        if full in self._expand:
            return self._expand[full]
        seen, stack = {full}, [full]
        while stack:
            cur = stack.pop()
            for child in self.children.get(cur, ()):
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
        self._expand[full] = seen
        return seen


class ApiIndex(object):
    """Member/type name sets from the public index and the BCL allowlist."""

    def __init__(self, public_path=None, internal_path=None):
        self.public_path, self.internal_path = find_index_files(public_path)
        self.loaded = False
        self.load_error = None
        self.public = {}                    # member name -> min effective version ((0,0,0) = always)
        self.version_example = {}           # member name -> "Type.Member" of the oldest definition
        self.obsolete = {}                  # member name -> message, when every public definition is obsolete
        self.internal_public = set()        # public members of public Spotfire types, from the internal index
        self.bcl_index = set()              # members of BCL types (mscorlib, System) that the indexes carry
        self.internal_nonpublic = set()     # non-public members, or members of non-public types
        self.internal_all = set()
        self.bcl = set()
        self.bcl_namespaces = set()
        self.namespaces = set()             # every namespace (public Spotfire + BCL) and every prefix
        self.ns_types = defaultdict(dict)   # namespace -> {short type name: (full name, version)}
        self.internal_ns_types = defaultdict(dict)   # namespace -> {short: full} for non-public types
        self.internal_namespaces = set()
        self.type_names = set()             # CLR full names, public + internal
        self.type_names_dotted = {}         # Outer.Inner form -> CLR full name (Outer+Inner)
        self.where = defaultdict(set)       # short type name -> namespaces holding a public type of that name
        self.public_types = []
        self._graph = None
        self._ns_by_last = None
        self._suggest_pool = None
        self._suggest_cache = {}
        self._after_cache = {}
        self._load()

    # ---- loading -----------------------------------------------------------------------------
    def _load(self):
        for key, names in BCL_ALLOWLIST.items():
            self.bcl.update(names.split())
            outer = key.split("+")[0]
            if "+" in key:
                self.bcl.add(key.split("+")[1])
            ns, short = outer.rsplit(".", 1)
            self.bcl_namespaces.add(ns)
            if "+" not in key:
                self.ns_types[ns].setdefault(short, (key, None))
        for names in IRONPYTHON_ALLOWLIST.values():
            self.bcl.update(names.split())
        if self.public_path is None or not self.public_path.exists():
            self.load_error = "API index not found (%s): API checks skipped" % (
                self.public_path or "SFAPI_INDEX or $DXP_WORKSPACE/api/spotfire-api-*.json")
            self._finish_namespaces()
            return
        try:
            with open(self.public_path, encoding="utf-8") as fh:
                pub = json.load(fh)
        except (OSError, ValueError) as e:
            self.load_error = "cannot read API index %s: %s" % (self.public_path, e)
            self._finish_namespaces()
            return
        self._load_public(pub["types"])
        if False:                           # the internal index is never read
            try:
                with open(self.internal_path, encoding="utf-8") as fh:
                    self._load_internal(json.load(fh)["types"])
            except (OSError, ValueError) as e:
                self.load_error = "cannot read internal index %s: %s" % (self.internal_path, e)
        self._finish_namespaces()
        self.loaded = True

    def _finish_namespaces(self):
        for ns in list(self.ns_types.keys()) + list(self.bcl_namespaces):
            self.namespaces.update(_ns_prefixes(ns))

    def _add_type_name(self, full):
        self.type_names.add(full)
        if "+" in full:
            self.type_names_dotted[full.replace("+", ".")] = full

    def _load_public(self, types):
        self.public_types = types
        tver = {}
        for t in types:
            tver[t["fullName"]] = parse_version(t.get("apiVersion"))
        for t in types:                                  # nested types inherit the outer version
            if tver[t["fullName"]] is None and t.get("declaringType"):
                tver[t["fullName"]] = tver.get(t["declaringType"])
        defs = defaultdict(int)
        obs = defaultdict(int)
        obs_msg = {}

        def add(name, version, example, obsolete=None):
            v = version or _ZERO
            cur = self.public.get(name)
            if cur is None or v < cur:
                self.public[name] = v
                self.version_example[name] = example
            defs[name] += 1
            if obsolete is not None:
                obs[name] += 1
                obs_msg.setdefault(name, obsolete)

        for t in types:
            full = t["fullName"]
            short = _short(t["name"])
            ns = t.get("namespace") or ""
            tv = tver.get(full)
            self._add_type_name(full)
            if t.get("declaringType"):
                add(short, tv, full.rsplit(".", 1)[-1].replace("+", "."))
            else:
                self.ns_types[ns][short] = (full, tv)
                if not t.get("external"):
                    self.where[short].add(ns)
            label = full.rsplit(".", 1)[-1].replace("+", ".")
            label = re.sub(r"`\d+", "", label)
            bcl_type = not full.startswith("Spotfire.")
            for key in ("properties", "methods", "fields", "events"):
                for m in t.get(key, []):
                    add(m["name"], parse_version(m.get("apiVersion")) or tv, label + "." + m["name"],
                        (m.get("obsolete") or "obsolete") if "obsolete" in m else None)
                    if bcl_type:
                        self.bcl_index.add(m["name"])
            for v in (t.get("enum") or {}).get("values", []):
                add(v["name"], parse_version(v.get("apiVersion")) or tv, label + "." + v["name"])
        for name, n in obs.items():
            if n == defs[name]:
                self.obsolete[name] = obs_msg[name]

    def _load_internal(self, types):
        public_full = set(t["fullName"] for t in self.public_types)
        vis_by_full = {}
        for t in types:
            full = t["fullName"]
            vis = t.get("visibility")
            if vis is None:
                tpublic = full in public_full or not full.startswith("Spotfire.")
            else:
                tpublic = vis == "public"
            vis_by_full[full] = tpublic
        for t in types:
            full = t["fullName"]
            tpublic = vis_by_full[full]
            self._add_type_name(full)
            ns = t.get("namespace") or ""
            short = _short(t["name"])
            if not tpublic and not t.get("declaringType"):
                self.internal_ns_types[ns][short] = full
                self.internal_namespaces.add(ns)
            if t.get("declaringType"):
                outer_public = vis_by_full.get(t["declaringType"], False)
                self.internal_all.add(short)
                (self.internal_public if (tpublic and outer_public) else self.internal_nonpublic).add(short)
            for key in ("properties", "methods", "fields", "events"):
                for m in t.get(key, []):
                    name = m["name"]
                    self.internal_all.add(name)
                    if key == "properties":
                        mvis = (m.get("getVisibility") if m.get("canRead") else m.get("setVisibility")) or "public"
                    else:
                        mvis = m.get("visibility") or "public"
                    if tpublic and mvis == "public":
                        if full.startswith("Spotfire."):
                            self.internal_public.add(name)
                        else:
                            self.bcl_index.add(name)
                    else:
                        self.internal_nonpublic.add(name)
            for v in (t.get("enum") or {}).get("values", []):
                self.internal_all.add(v["name"])
                (self.internal_public if tpublic else self.internal_nonpublic).add(v["name"])

    # ---- queries -----------------------------------------------------------------------------
    def is_public_name(self, name):
        return name in self.public or self.version_free(name) or name in self.internal_public

    def version_free(self, name):
        """BCL / IronPython names: no Spotfire version constraint, not Spotfire-typed."""
        return name in self.bcl or name in self.bcl_index

    def is_any_member(self, name):
        return self.is_public_name(name) or name in self.internal_all

    def min_version(self, name):
        """Oldest [api] version among the public definitions of a member name; None = no constraint."""
        if self.version_free(name) or name not in self.public:
            return None
        v = self.public[name]
        return None if v == _ZERO else v

    def obsolete_message(self, name):
        if self.version_free(name):
            return None
        return self.obsolete.get(name)

    def ns_type(self, ns, short):
        """(full name, version) of a public/BCL type `short` directly in namespace `ns`, else None."""
        return self.ns_types.get(ns, {}).get(short)

    def namespaces_ending_with(self, last):
        if self._ns_by_last is None:
            self._ns_by_last = defaultdict(list)
            for ns in sorted(self.namespaces):
                self._ns_by_last[ns.rsplit(".", 1)[-1]].append(ns)
        return self._ns_by_last.get(last, ())

    def has_type(self, full):
        """'exact' (CLR name), 'dotted' (nested type written with '.'), or None."""
        if full in self.type_names:
            return "exact"
        if full in self.type_names_dotted:
            return "dotted"
        return None

    def suggest(self, name, n=3):
        if name in self._suggest_cache:
            return self._suggest_cache[name]
        if self._suggest_pool is None:
            self._suggest_pool = sorted(set(self.public) | self.bcl | self.bcl_index | self.internal_public)
        low = name.lower()
        exact_ci = [x for x in self._suggest_pool if x.lower() == low and x != name]
        out = exact_ci + [x for x in difflib.get_close_matches(name, self._suggest_pool, n=n, cutoff=0.8)
                          if x not in exact_ci]
        self._suggest_cache[name] = out[:n]
        return self._suggest_cache[name]

    def graph(self):
        if self._graph is None:
            self._graph = _TypeGraph(self.public_types)
        return self._graph

    def after(self, member, kind):
        """Member names available on the result of `.member` (kind 'attr') or `.member(...)` (kind
        'call'), over every type that a public member of that name returns, including subclasses.
        Returns (names, labels) or (None, ()) when that cannot be decided statically."""
        key = (member, kind)
        if key in self._after_cache:
            return self._after_cache[key]
        res = (None, ())
        g = self.graph()
        metas = g.results.get(member, [])
        if kind == "attr":
            if any(k == "event" for k, _ in metas):
                metas = []
            sel = [(k, r) for k, r in metas if k in ("property", "field", "enum", "nested")]
        else:
            sel = [(k, r) for k, r in metas if k == "method"]
        if sel:
            entries, ok = {}, True
            for k, r in sel:
                e = g.resolve(k, r)
                if e is None:
                    ok = False
                    break
                entries[e["fullName"]] = e
            if ok:
                names, labels = set(), set()
                for full in entries:
                    labels.add(re.sub(r"`\d+", "", full.rsplit(".", 1)[-1].replace("+", ".")))
                    for cand in g.expand(full):
                        av = g.available(cand)
                        if av is None:
                            ok = False
                            break
                        names |= av
                    if not ok:
                        break
                if ok:
                    res = (names, tuple(sorted(labels)))
        self._after_cache[key] = res
        return res


_API_CACHE = {}


def load_api(public=None, internal=None):
    """ApiIndex for the given (or newest) index files, cached per process."""
    pub, intl = find_index_files(public, internal)
    key = (str(pub), str(intl))
    if key not in _API_CACHE:
        _API_CACHE[key] = ApiIndex(pub, intl)
    return _API_CACHE[key]


# ------------------------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------------------------
def decode_persisted(text):
    """Spotfire's persisted-string escapes as found in decompiled DXPs: _x09 -> tab (control chars,
    _x5F -> '_', _x7F)."""
    return _PERSISTED_RE.sub(lambda m: chr(int(m.group(1), 16)), text)


def _is_dotted(node):
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name)


def _base_name(node):
    """The Name at the bottom of an expression made of attributes, calls and subscripts, else None."""
    cur = node
    while True:
        if isinstance(cur, ast.Attribute):
            cur = cur.value
        elif isinstance(cur, ast.Call):
            cur = cur.func
        elif isinstance(cur, ast.Subscript):
            cur = cur.value
        else:
            return cur if isinstance(cur, ast.Name) else None


def _pure_chain(node):
    """For a.b.c (Attribute nodes over a Name) -> (Name node, [Attribute nodes innermost first])."""
    nodes = []
    cur = node
    while isinstance(cur, ast.Attribute):
        nodes.append(cur)
        cur = cur.value
    if isinstance(cur, ast.Name):
        nodes.reverse()
        return cur, nodes
    return None, None


class _Bindings(ast.NodeVisitor):
    """Names bound in the file, imports, attributes assigned on self/cls/classes, string constants."""

    def __init__(self, tree):
        self.bound = set()
        self.imported = set()
        self.imports = []            # (kind 'import'|'from', module, name, asname, node)
        self.class_names = set()
        self._store_attrs = []
        self._instances = []         # (name, called name) for name = Callable(...)
        self.str_consts = {}
        self._const_count = defaultdict(int)
        self.visit(tree)
        self.self_attrs = set(a for base, a in self._store_attrs if base in ({"self", "cls"} | self.class_names))
        # instances of classes defined in this file are Python objects: their attributes are not .NET
        self.instance_names = set(n for n, c in self._instances if c in self.class_names)
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                name = stmt.targets[0].id
                if self._const_count[name] == 1:
                    val = _fold_str(stmt.value, self.str_consts)
                    if val is not None:
                        self.str_consts[name] = val

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.bound.add(node.id)
            self._const_count[node.id] += 1

    def _args(self, args):
        for a in list(getattr(args, "posonlyargs", [])) + list(args.args) + list(args.kwonlyargs):
            self.bound.add(a.arg)
        if args.vararg:
            self.bound.add(args.vararg.arg)
        if args.kwarg:
            self.bound.add(args.kwarg.arg)

    def visit_FunctionDef(self, node):
        self.bound.add(node.name)
        self._args(node.args)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        self._args(node.args)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.bound.add(node.name)
        self.class_names.add(node.name)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node):
        self.bound.update(node.names)

    visit_Nonlocal = visit_Global

    def visit_MatchAs(self, node):
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node):
        if node.name:
            self.bound.add(node.name)

    def visit_MatchMapping(self, node):
        if node.rest:
            self.bound.add(node.rest)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.ctx, ast.Store) and isinstance(node.value, ast.Name):
            self._store_attrs.append((node.value.id, node.attr))
        self.generic_visit(node)

    def visit_Assign(self, node):
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self._instances.append((t.id, node.value.func.id))
        self.generic_visit(node)

    def visit_Import(self, node):
        for a in node.names:
            name = a.asname or a.name.split(".")[0]
            self.imported.add(name)
            self.imports.append(("import", a.name, None, a.asname, a))

    def visit_ImportFrom(self, node):
        mod = ("." * node.level) + (node.module or "")
        for a in node.names:
            if a.name != "*":
                self.imported.add(a.asname or a.name)
            self.imports.append(("from", mod, a.name, a.asname, a))


def _fold_str(node, consts):
    """Value of a string expression built from literals, known constants and '+', else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold_str(node.left, consts), _fold_str(node.right, consts)
        if left is not None and right is not None:
            return left + right
    return None


# ------------------------------------------------------------------------------------------------
# the linter
# ------------------------------------------------------------------------------------------------
class _Linter(ast.NodeVisitor):

    def __init__(self, path, lines, api, min_version, document_script, script_globals, check_names):
        self.path = path
        self.lines = lines
        self.api = api
        self.min_version = min_version
        self.document_script = document_script
        self.script_globals = set(SCRIPT_GLOBALS) | set(script_globals or ())
        self.check_names = check_names
        self.findings = []
        self.handled = set()        # Attribute node ids already checked as part of a chain
        self.type_nodes = set()     # node ids that denote a namespace or a type (no pair check after them)
        self.nopair = set()         # Attribute node ids where the two-level check must not run
        self._fstring_depth = 0
        self.api_ok = api is not None and api.loaded

    # ---- reporting ---------------------------------------------------------------------------
    def _col(self, lineno, byte_col):
        """1-based character column from a UTF-8 byte offset."""
        if 1 <= lineno <= len(self.lines):
            text = self.lines[lineno - 1]
            try:
                return len(text.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore")) + 1
            except Exception:
                return byte_col + 1
        return byte_col + 1

    def add(self, line, col, severity, code, message):
        self.findings.append(Finding(self.path, line, col, severity, code, message))

    def add_node(self, node, severity, code, message):
        line = getattr(node, "lineno", 1) or 1
        self.add(line, self._col(line, getattr(node, "col_offset", 0) or 0), severity, code, message)

    def _attr_pos(self, node):
        line = getattr(node, "end_lineno", None) or node.lineno
        end = getattr(node, "end_col_offset", None)
        if end is None:
            return node.lineno, self._col(node.lineno, node.col_offset)
        return line, self._col(line, max(0, end - len(node.attr.encode("utf-8"))))

    def add_attr(self, node, severity, code, message):
        line, col = self._attr_pos(node)
        self.add(line, col, severity, code, message)

    def syntax(self, node, message):
        self.add_node(node, "error", R_SYNTAX, message)

    # ---- setup -------------------------------------------------------------------------------
    def run(self, tree):
        self.b = _Bindings(tree)
        self.defined_attrs = (self.b.bound - self.b.imported) | self.b.self_attrs
        self._classify_imports()
        self.visit(tree)
        if self.check_names:
            self._undefined_names(tree)
        return self.findings

    def _classify_imports(self):
        """Local names bound by imports: Python modules/objects and .NET namespaces or types we know
        nothing about are 'opaque' (their attributes are not checked); known .NET namespaces and
        types are resolved."""
        self.opaque_roots = set()
        self.ns_roots = {}           # local name -> namespace path
        self.type_roots = {}         # local name -> type path
        self.star = []
        api = self.api
        for kind, mod, name, asname, node in self.b.imports:
            if kind == "import":
                first = mod.split(".")[0]
                local = asname or first
                if first not in DOTNET_ROOTS:
                    if first != "clr":                     # clr members are in the allowlist
                        self.opaque_roots.add(local)
                    continue
                path = mod if asname else first
                if path in api.namespaces:
                    self.ns_roots[local] = path
                elif asname and "." in mod and api.ns_type(*mod.rsplit(".", 1)):
                    self.type_roots[local] = path          # import System.IO.Path as P (a type)
                else:
                    self.opaque_roots.add(local)           # e.g. import Microsoft.VisualBasic
            else:
                if mod.startswith("."):
                    if name != "*":
                        self.opaque_roots.add(asname or name)
                    continue
                first = mod.split(".")[0]
                if name == "*":
                    self.star.append(mod)
                    continue
                local = asname or name
                if first not in DOTNET_ROOTS:
                    if first != "clr" and mod != "__future__":
                        self.opaque_roots.add(local)
                    continue
                full = mod + "." + name
                if full in api.namespaces:
                    self.ns_roots[local] = full
                elif api.ns_type(mod, name) or first == "Spotfire":
                    self.type_roots[local] = full          # unknown Spotfire types: rule 3 reports them
                else:
                    self.opaque_roots.add(local)           # BCL type outside the allowlist

    def _root_kind(self, name, first_attr=None):
        if name in self.opaque_roots or name in self.b.instance_names:
            return ("opaque", None)
        if name in self.ns_roots:
            return ("ns", self.ns_roots[name])
        if name in self.type_roots:
            return ("type", self.type_roots[name])
        free = name not in self.b.bound and name not in self.b.imported and name not in self.script_globals
        if free and self.api is not None:
            for mod in self.star:
                if mod.split(".")[0] not in DOTNET_ROOTS:
                    continue
                if mod + "." + name in self.api.namespaces:
                    return ("ns", mod + "." + name)
                if self.api.ns_type(mod, name):
                    return ("type", mod + "." + name)
            # snippets (postScripts, doc examples) often use a namespace alias without its import:
            # Maps.MapChart, IO.Path - accept when the next segment resolves inside that namespace
            if first_attr is not None:
                for ns in self.api.namespaces_ending_with(name):
                    if self.api.ns_type(ns, first_attr) or ns + "." + first_attr in self.api.namespaces:
                        return ("ns", ns)
        return (None, None)

    # ---- rule 1: syntax subset ---------------------------------------------------------------
    def visit_JoinedStr(self, node):
        if self._fstring_depth == 0:
            self.syntax(node, "f-string is not IronPython 3.4 syntax: use '...{}'.format(...) or '%s' % (...)")
        self._fstring_depth += 1
        self.generic_visit(node)
        self._fstring_depth -= 1

    def visit_TemplateStr(self, node):
        self.syntax(node, "template string t'...' is not IronPython 3.4 syntax")
        self._fstring_depth += 1
        self.generic_visit(node)
        self._fstring_depth -= 1

    def visit_NamedExpr(self, node):
        self.syntax(node, "assignment expression ':=' (walrus) is not IronPython 3.4 syntax")
        self.generic_visit(node)

    def _check_function(self, node, is_lambda=False):
        args = node.args
        if getattr(args, "posonlyargs", None):
            self.syntax(args.posonlyargs[0], "positional-only parameters ('/') are Python 3.8+ syntax")
        if not is_lambda:
            for a in list(getattr(args, "posonlyargs", [])) + list(args.args) + list(args.kwonlyargs) + \
                    [x for x in (args.vararg, args.kwarg) if x is not None]:
                if a.annotation is not None:
                    self.syntax(a.annotation, "parameter annotation: annotations are not allowed in "
                                              "IronPython scripts for Spotfire (house rule)")
            if node.returns is not None:
                self.syntax(node.returns, "return annotation: annotations are not allowed in IronPython "
                                          "scripts for Spotfire (house rule)")
            if getattr(node, "type_params", None):
                self.syntax(node.type_params[0], "type parameters are Python 3.12+ syntax")
            self._check_decorators(node)

    def _check_decorators(self, node):
        for d in node.decorator_list:
            ok = _is_dotted(d) or (isinstance(d, ast.Call) and _is_dotted(d.func))
            if not ok:
                self.syntax(d, "decorator expression is Python 3.9+ syntax (3.4 allows a dotted name "
                               "with an optional call)")

    def visit_FunctionDef(self, node):
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.syntax(node, "async def is not IronPython 3.4 syntax")
        self._check_function(node)
        self.generic_visit(node)

    def visit_Lambda(self, node):
        self._check_function(node, is_lambda=True)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        if getattr(node, "type_params", None):
            self.syntax(node.type_params[0], "type parameters are Python 3.12+ syntax")
        self._check_decorators(node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self.syntax(node, "variable annotation is Python 3.6+ syntax")
        self.generic_visit(node)

    def visit_Await(self, node):
        self.syntax(node, "await is not IronPython 3.4 syntax")
        self.generic_visit(node)

    def visit_AsyncFor(self, node):
        self.syntax(node, "async for is not IronPython 3.4 syntax")
        self.generic_visit(node)

    def visit_AsyncWith(self, node):
        self.syntax(node, "async with is not IronPython 3.4 syntax")
        self.generic_visit(node)

    def visit_comprehension(self, node):
        if node.is_async:
            self.syntax(node.target, "async comprehension is not IronPython 3.4 syntax")
        self.generic_visit(node)

    def visit_Match(self, node):
        self.syntax(node, "match statement is Python 3.10+ syntax")
        self.generic_visit(node)

    def visit_TryStar(self, node):
        self.syntax(node, "except* is Python 3.11+ syntax")
        self._check_try(node)
        self.generic_visit(node)

    def visit_TypeAlias(self, node):
        self.syntax(node, "type alias statement is Python 3.12+ syntax")
        self.generic_visit(node)

    def visit_Try(self, node):
        self._check_try(node)
        self.generic_visit(node)

    def _check_try(self, node):
        for h in node.handlers:
            t = h.type
            if isinstance(t, ast.Tuple) and t.elts:
                line = t.lineno
                if 1 <= line <= len(self.lines):
                    text = self.lines[line - 1].encode("utf-8")
                    if text[t.col_offset:t.col_offset + 1] != b"(":
                        self.syntax(t, "'except A, B:' without parentheses is Python 3.14+ syntax: write except (A, B):")
        for stmt in node.finalbody:
            for c in self._continues(stmt):
                self.syntax(c, "'continue' inside 'finally' is Python 3.8+ syntax")

    def _continues(self, node):
        if isinstance(node, ast.Continue):
            yield node
            return
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            # a loop inside the finally block owns its continue (its else-branch does not)
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                for stmt in node.orelse:
                    for c in self._continues(stmt):
                        yield c
            return
        for child in ast.iter_child_nodes(node):
            for c in self._continues(child):
                yield c

    def visit_BinOp(self, node):
        if isinstance(node.op, ast.MatMult):
            self.syntax(node, "'@' matrix multiplication is Python 3.5+ syntax")
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        if isinstance(node.op, ast.MatMult):
            self.syntax(node, "'@=' matrix multiplication is Python 3.5+ syntax")
        self.generic_visit(node)

    def _starred_display(self, node):
        if isinstance(getattr(node, "ctx", ast.Load()), ast.Load):
            for e in node.elts:
                if isinstance(e, ast.Starred):
                    self.syntax(e, "'*' unpacking inside a list/tuple/set display is Python 3.5+ (PEP 448)")
                    break

    def visit_List(self, node):
        self._starred_display(node)
        self.generic_visit(node)

    visit_Tuple = visit_List
    visit_Set = visit_List

    def visit_Dict(self, node):
        for k, v in zip(node.keys, node.values):
            if k is None:
                self.syntax(v, "'**' unpacking inside a dict display is Python 3.5+ (PEP 448)")
                break
        self.generic_visit(node)

    def visit_Call(self, node):
        # PEP 448 relaxed the 3.4 call grammar: (args..., *one) and (keywords..., **one) last.
        # ('*' after '**' is rejected by CPython itself and surfaces as a parse error.)
        stars = [a for a in node.args if isinstance(a, ast.Starred)]
        if len(stars) > 1:
            self.syntax(stars[1], "several '*' unpackings in one call are Python 3.5+ (PEP 448)")
        elif stars:
            idx = node.args.index(stars[0])
            for a in node.args[idx + 1:]:
                self.syntax(a, "positional argument after '*' unpacking is Python 3.5+ (PEP 448)")
                break
        dstars = [k for k in node.keywords if k.arg is None]
        if len(dstars) > 1:
            self.syntax(dstars[1], "several '**' unpackings in one call are Python 3.5+ (PEP 448)")
        if dstars:
            first = (dstars[0].lineno, dstars[0].col_offset)
            for k in node.keywords:
                if k.arg is not None and (k.lineno, k.col_offset) > first:
                    self.syntax(k, "keyword argument after '**' unpacking is Python 3.5+ (PEP 448)")
                    break
        func = node.func
        if isinstance(func, ast.Name):
            if func.id == "print" and "print" not in self.b.bound:
                if self.document_script:
                    self.add_node(node, "error", R_PRINT, "print() in a document script: output goes "
                                  "nowhere in Spotfire; record diagnostics instead")
                else:
                    self.add_node(node, "warning", R_PRINT, "print() call: no print in IronPython for "
                                  "Spotfire")
        self.generic_visit(node)

    # ---- rule 3: imports ----------------------------------------------------------------------
    def visit_ImportFrom(self, node):
        mod = node.module or ""
        if self.api_ok and node.level == 0 and (mod == "Spotfire" or mod.startswith("Spotfire.")):
            for a in node.names:
                self._check_spotfire_import(mod, a)
        self.generic_visit(node)

    def visit_Import(self, node):
        if self.api_ok:
            for a in node.names:
                if a.name.split(".")[0] == "Spotfire" and a.name not in self.api.namespaces \
                        and not self.api.has_type(a.name):
                    self.add_node(a, "error", R_IMPORT, "unknown Spotfire namespace '%s' (not in the API index)%s"
                                  % (a.name, self._ns_hint(a.name)))
        self.generic_visit(node)

    def _ns_hint(self, ns):
        if ns in self.api.internal_namespaces:
            return "; it holds only non-public (internal) types, which the builders do not use"
        close = difflib.get_close_matches(ns, sorted(self.api.namespaces), n=1, cutoff=0.8)
        return "; did you mean %s?" % close[0] if close else ""

    def _check_spotfire_import(self, mod, alias):
        api = self.api
        name = alias.name
        if mod not in api.namespaces:
            self.add_node(alias, "error", R_IMPORT, "unknown Spotfire namespace '%s' (not in the API index)%s"
                          % (mod, self._ns_hint(mod)))
            return
        if name == "*":
            return
        info = api.ns_type(mod, name)
        if info is not None:
            ver = info[1]
            if ver is not None and ver > self.min_version:
                self.add_node(alias, "warning", R_VERSION, "%s.%s requires Spotfire %s (target %s)"
                              % (mod, name, format_version(ver), format_version(self.min_version)))
            return
        if mod + "." + name in api.namespaces:
            return
        if name in api.internal_ns_types.get(mod, {}):
            self.add_node(alias, "error", R_IMPORT, "%s.%s is a non-public (internal) type: IronPython cannot "
                          "import it, and the builders use Spotfire's public API only" % (mod, name))
            return
        hint = ""
        homes = sorted(api.where.get(name, ()))
        if homes:
            hint = "; it is in " + " / ".join(homes[:3])
        else:
            pool = sorted(api.ns_types.get(mod, {}).keys())
            close = difflib.get_close_matches(name, pool, n=2, cutoff=0.75)
            if close:
                hint = "; did you mean " + " or ".join(close) + "?"
        self.add_node(alias, "error", R_IMPORT, "namespace %s has no public type '%s'%s" % (mod, name, hint))

    # ---- rule 2 + 4: attributes ----------------------------------------------------------------
    def visit_Attribute(self, node):
        holder = node.value
        if node.attr == "NonPublic" and (getattr(holder, "id", None) == "BindingFlags"
                                         or getattr(holder, "attr", None) == "BindingFlags"):
            self.add_node(node, "error", R_NONPUBLIC, "BindingFlags.NonPublic reaches non-public Spotfire members "
                          "through reflection; the builders and scripts use the public API only")
        if id(node) in self.handled or not self.api_ok:
            self.generic_visit(node)
            return
        root, chain = _pure_chain(node)
        if root is None:
            base = _base_name(node.value)        # json.loads(s).X, DriveInfo.GetDrives()[0].X, ...
            if base is not None and self._root_kind(base.id)[0] == "opaque":
                self.generic_visit(node)
                return
        if root is not None:
            kind, path = self._root_kind(root.id, chain[0].attr)
            if kind == "opaque":
                for n in chain:
                    self.handled.add(id(n))
                self.generic_visit(node)
                return
            if kind == "ns":
                self._namespace_chain(root, chain, path)
                self.generic_visit(node)
                return
            if kind == "type":
                self.type_nodes.add(id(root))
                if not path.startswith("Spotfire."):
                    for n in chain:
                        self.nopair.add(id(n))     # BCL objects: result types are not in the index
        self.check_member(node)
        self.generic_visit(node)

    def _namespace_chain(self, root, chain, path):
        api = self.api
        for n in chain:
            self.handled.add(id(n))
        self.type_nodes.add(id(root))
        cur, typ = path, None
        for n in chain:
            seg = n.attr
            if typ is None:
                nxt = cur + "." + seg
                if nxt in api.namespaces:
                    cur = nxt
                    self.type_nodes.add(id(n))
                    continue
                info = api.ns_type(cur, seg)
                if info is not None:
                    typ = info[0]
                    self.type_nodes.add(id(n))
                    if info[1] is not None and info[1] > self.min_version:
                        self.add_attr(n, "warning", R_VERSION, "%s requires Spotfire %s (target %s)"
                                      % (nxt, format_version(info[1]), format_version(self.min_version)))
                    if not nxt.startswith("Spotfire."):
                        for m in chain:
                            self.nopair.add(id(m))
                    continue
                if seg in self.defined_attrs or not cur.startswith("Spotfire"):
                    return      # the BCL allowlist does not enumerate every .NET namespace/type
                self.add_attr(n, "warning", R_UNKNOWN, "unknown member '%s': no public type or namespace %s "
                              "in the API index" % (seg, nxt))
                return
            self.check_member(n)

    def check_member(self, node):
        name = node.attr
        if not name[:1].isupper() or name in self.defined_attrs:
            return
        api = self.api
        if api.is_public_name(name):
            v = api.min_version(name)
            if v is not None and v > self.min_version:
                self.add_attr(node, "warning", R_VERSION,
                              "'%s' requires Spotfire %s (every member of that name is [api %s] or newer, "
                              "e.g. %s; target %s)" % (name, format_version(v), format_version(v),
                                                       api.version_example.get(name, name),
                                                       format_version(self.min_version)))
            msg = api.obsolete_message(name)
            if msg:
                self.add_attr(node, "warning", R_OBSOLETE, "'%s' is obsolete: %s" % (name, msg))
        elif name in api.internal_nonpublic:
            self.add_attr(node, "warning", R_INTERNAL,
                          "'%s' exists only as a non-public (internal) member: IronPython cannot reach it, "
                          "and the builders use Spotfire's public API only" % name)
            return
        else:
            sug = api.suggest(name)
            self.add_attr(node, "warning", R_UNKNOWN,
                          "unknown member '%s' (not in the Spotfire API index or the BCL allowlist)%s"
                          % (name, "; did you mean " + " / ".join(sug) + "?" if sug else ""))
            return
        if id(node) not in self.nopair:
            self._pair_check(node)

    def _pair_check(self, node):
        v = node.value
        if isinstance(v, ast.Attribute):
            kind, prev = "attr", v
        elif isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute):
            kind, prev = "call", v.func
        else:
            return
        if id(prev) in self.type_nodes or id(prev) in self.nopair:
            return
        b = prev.attr
        api = self.api
        if not b[:1].isupper() or b in self.defined_attrs or api.version_free(b) or b not in api.public:
            return
        c = node.attr
        if c in IRONPYTHON_ALLOWLIST["method objects"].split():
            return
        names, labels = api.after(b, kind)
        if names is not None and c not in names:
            shown = ", ".join(labels[:6]) + (", ..." if len(labels) > 6 else "")
            self.add_attr(node, "warning", R_RESULT,
                          "'%s' is not a member of any type returned by '.%s%s' (%s)"
                          % (c, b, "()" if kind == "call" else "", shown))

    # ---- undefined names (document scripts) ------------------------------------------------------
    def _undefined_names(self, tree):
        known = self.b.bound | self.b.imported | self.script_globals | set(dir(builtins)) | EXTRA_BUILTINS
        uncertain = False
        api = self.api
        for mod in self.star:
            if api is not None and api.loaded and mod.startswith("Spotfire") and mod in api.namespaces:
                known |= set(api.ns_types.get(mod, {}).keys())
                prefix = mod + "."
                known |= set(ns[len(prefix):].split(".")[0] for ns in api.namespaces if ns.startswith(prefix))
            else:
                uncertain = True                   # System.* / Python star imports: not enumerable here
        if uncertain:
            return
        first = {}                                 # name -> earliest Name node (reported once per name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in known:
                cur = first.get(node.id)
                if cur is None or (node.lineno, node.col_offset) < (cur.lineno, cur.col_offset):
                    first[node.id] = node
        for name, node in first.items():
            self.add_node(node, "warning", R_UNDEFINED,
                          "undefined name '%s' (missing import or assignment; script parameters: --globals)" % name)


# ------------------------------------------------------------------------------------------------
# text and token passes
# ------------------------------------------------------------------------------------------------
def _tab_findings(path, lines):
    out = []
    for i, text in enumerate(lines, 1):
        pos = text.find("\t")
        if pos < 0:
            continue
        indent = len(text) - len(text.lstrip(" \t"))
        if pos < indent:
            msg = "tab character in indentation: indent with 4 spaces"
        else:
            msg = "tab character: use spaces (write \\t inside strings)"
        out.append(Finding(path, i, pos + 1, "error", R_TAB, msg))
    return out


def _token_pass(path, source):
    """(findings, patched source, noqa map). Patches X.None/True/False so the file still parses."""
    findings = []
    noqa = {}
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError, ValueError):
        for i, text in enumerate(source.split("\n"), 1):
            m = _NOQA_RE.search(text)
            if m:
                noqa[i] = _noqa_codes(m)
        return findings, source, noqa
    lines = source.split("\n")
    patches = []
    prev = None
    for tok in tokens:
        ttype = tok.type
        if ttype == tokenize.COMMENT:
            m = _NOQA_RE.search(tok.string)
            if m:
                noqa[tok.start[0]] = _noqa_codes(m)
            continue
        if ttype in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING):
            if ttype == tokenize.NEWLINE:
                prev = None
            continue
        if ttype == tokenize.NUMBER and "_" in tok.string:
            findings.append(Finding(path, tok.start[0], tok.start[1] + 1, "error", R_SYNTAX,
                                    "numeric literal with '_' (%s) is Python 3.6+ syntax: write %s"
                                    % (tok.string, tok.string.replace("_", ""))))
        if ttype == tokenize.NAME and tok.string in _KEYWORD_ATTRS and prev is not None \
                and prev.type == tokenize.OP and prev.string == ".":
            findings.append(Finding(path, tok.start[0], tok.start[1] + 1, "error", R_NONE_ATTR,
                                    "'.%s' is a syntax error in IronPython 3: use getattr(<object>, \"%s\")"
                                    % (tok.string, tok.string)))
            patches.append((tok.start[0], tok.start[1], tok.string))
        prev = tok
    for row, col, word in patches:
        text = lines[row - 1]
        lines[row - 1] = text[:col] + word.lower() + text[col + len(word):]
    return findings, ("\n".join(lines) if patches else source), noqa


def _noqa_codes(match):
    if not match.group(1):
        return None                                  # every rule
    return set(c.strip().lower() for c in re.split(r"[,\s]+", match.group(1)) if c.strip())


def _suppressed(f, noqa):
    if f.line not in noqa:
        return False
    codes = noqa[f.line]
    return codes is None or f.code in codes


# ------------------------------------------------------------------------------------------------
# public API
# ------------------------------------------------------------------------------------------------
def lint_source(source, path="<string>", min_version=DEFAULT_MIN_VERSION, document_script=False,
                script_globals=(), check_names=None, persisted=False, api=None):
    """Lint IronPython source text. Returns findings sorted by position."""
    if isinstance(min_version, str) or min_version is None:
        target = parse_version(min_version or DEFAULT_MIN_VERSION)
    else:
        target = tuple(min_version)
    if check_names is None:
        check_names = document_script
    if api is None:
        api = load_api()
    if source.startswith("\ufeff"):
        source = source[1:]
    if persisted:
        source = decode_persisted(source)
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = source.split("\n")
    findings = _tab_findings(path, lines)
    tok_findings, patched, noqa = _token_pass(path, source)
    findings.extend(tok_findings)
    tree = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")              # e.g. SyntaxWarning for "\d": harmless in 3.4
        try:
            tree = ast.parse(patched, filename=path)
        except SyntaxError as e:
            line = e.lineno or 1
            col = e.offset or 1
            if isinstance(e, TabError):
                findings.append(Finding(path, line, col, "error", R_PARSE,
                                        "inconsistent use of tabs and spaces in indentation (TabError)"))
                try:
                    patched = patched.expandtabs(8)      # keep analysing; columns after tabs shift
                    tree = ast.parse(patched, filename=path)
                except (SyntaxError, ValueError):
                    tree = None
            else:
                findings.append(Finding(path, line, col, "error", R_PARSE, "syntax error: %s" % e.msg))
        except ValueError as e:                      # e.g. NUL bytes
            findings.append(Finding(path, 1, 1, "error", R_PARSE, "cannot parse: %s" % e))
    if tree is not None:
        linter = _Linter(path, patched.split("\n"), api, target, document_script, script_globals, check_names)
        findings.extend(linter.run(tree))
    findings = [f for f in findings if not _suppressed(f, noqa)]
    uniq, seen = [], set()
    for f in sorted(findings, key=lambda f: (f.line, f.col, f.code, f.message)):
        key = (f.line, f.col, f.code, f.message)
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq


def read_source(path):
    """(text, findings) - UTF-8 (BOM tolerated); falls back to cp1252 with a warning."""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), [
            Finding(str(path), 1, 1, "warning", R_ENCODING, "file is not UTF-8 (decoded as cp1252)")]


def lint_file(path, **options):
    try:
        text, extra = read_source(path)
    except OSError as e:
        return [Finding(str(path), 1, 1, "error", R_PARSE, "cannot read file: %s" % e)]
    return extra + lint_source(text, path=str(path), **options)


def format_finding(f):
    return "%s:%d:%d: %s: %s [%s]" % (f.path, f.line, f.col, f.severity, f.message, f.code)


def _expand_args(paths):
    """Expand wildcards (cmd.exe does not) and directories (their *.py files, not recursive)."""
    out = []
    for p in paths:
        if p != "-" and any(ch in p for ch in "*?[") and not os.path.exists(p):
            hits = sorted(glob.glob(p))
            out.extend(hits if hits else [p])
        elif p != "-" and os.path.isdir(p):
            out.extend(sorted(str(x) for x in Path(p).glob("*.py")))
        else:
            out.append(p)
    return out


def main(argv=None):
    doc = __doc__ or ""
    ap = argparse.ArgumentParser(prog="lint_ipy", description=doc.split("\n\n")[0],
                                 epilog=doc[doc.find("Rules"):doc.find("Python API")].rstrip(),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="IronPython files, directories (their *.py) or wildcards; '-' reads stdin")
    ap.add_argument("--min-version", default=DEFAULT_MIN_VERSION,
                    help="oldest Spotfire the code must run on (default %(default)s)")
    ap.add_argument("--document-script", action="store_true",
                    help="the file is a document script: print() is an error, undefined names are reported")
    ap.add_argument("--globals", default="",
                    help="comma-separated extra names in scope (script parameters, postScript names)")
    ap.add_argument("--check-names", action="store_true", help="report undefined names (implied by --document-script)")
    ap.add_argument("--persisted", action="store_true",
                    help="decode Spotfire persisted-string escapes (_x09 = tab) before linting")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    ap.add_argument("--index", default=None, help="public API index (default: $SFAPI_INDEX, else the newest "
                                                  "$DXP_WORKSPACE/api/spotfire-api-*.json)")
    args = ap.parse_args(argv)
    try:
        target = parse_version(args.min_version)
    except ValueError as e:
        ap.error(str(e))
    api = load_api(args.index)
    script_globals = tuple(x.strip() for x in args.globals.split(",") if x.strip())
    options = dict(min_version=target, document_script=args.document_script, script_globals=script_globals,
                   check_names=True if args.check_names else None, persisted=args.persisted, api=api)
    files = _expand_args(args.files)
    findings = []
    notes = []
    if api.load_error:
        notes.append("lint_ipy: note: " + api.load_error)
    for p in files:
        if p == "-":
            findings.extend(lint_source(sys.stdin.read(), path="<stdin>", **options))
        else:
            findings.extend(lint_file(p, **options))
    errors = sum(1 for f in findings if f.severity == "error")
    warns = len(findings) - errors
    if args.json:
        print(json.dumps({"files": files, "errors": errors, "warnings": warns, "notes": notes,
                          "findings": [f._asdict() for f in findings]}, indent=1))
    else:
        for n in notes:
            print(n)
        for f in findings:
            print(format_finding(f))
        print("lint_ipy: %d file(s), %d error(s), %d warning(s) (min version %s%s)"
              % (len(files), errors, warns, format_version(target),
                 ", document script" if args.document_script else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
