"""Tests for two validation rules of dxpgen validate:

- scripts/textlint.py, the customer-ready text check of `dxpgen validate` (Validator.v_customer_text):
  internal language (release tags, "verbatim", "legacy", "prototype", TODO, tool and assistant names,
  Req* property names in prose, app.bannedTerms) is an error in visible text and a warning in the
  comments, docstrings and strings of embedded code; app.textLint sets the levels and allowed rules;
- scripts/sfexpr.py value_kind / date_call_properties and Validator.v_reference_types: a reference line
  must evaluate to the type of its axis (for example no DateAdd over a LongInteger property on a date
  axis).

Run: python -m unittest tests/test_customer_text.py
Nothing starts Spotfire.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))
import dxpgen  # noqa: E402
import sfexpr  # noqa: E402
import textlint  # noqa: E402
from test_dxpgen import AppTestCase  # noqa: E402


def lint_texts(text, scope=textlint.VISIBLE, app=None):
    rules = textlint.app_rules(app or {})
    return sorted(set(r.id for r in rules if scope in r.scopes and r.regex.search(text)))


class RuleTests(unittest.TestCase):
    def test_default_rules_hit_internal_language(self):
        self.assertEqual(lint_texts("the R2.0 copy"), ["release-tag"])
        self.assertEqual(lint_texts("R6.x grid"), ["release-tag"])
        self.assertEqual(lint_texts("r53 checker"), ["release-tag"])
        self.assertEqual(lint_texts("the verbatim solver"), ["verbatim"])
        self.assertEqual(lint_texts("GIS_PUMPS_LEGACY"), ["legacy"])
        self.assertEqual(lint_texts("from the prototype"), ["prototype"])
        self.assertEqual(lint_texts("TODO: wire it"), ["dev-note"])
        self.assertEqual(lint_texts("needs-live-test"), ["dev-note"])
        self.assertEqual(lint_texts("written by Claude"), ["assistant"])
        self.assertEqual(lint_texts("see skill 12"), ["skill"])
        self.assertEqual(lint_texts("run dxpgen build"), ["tool-name"])
        self.assertEqual(lint_texts("the builder makes it"), ["builder"])
        self.assertEqual(lint_texts("copied into ReqOpsDays"), ["property-name"])
        self.assertEqual(lint_texts("new in v1.2"), ["version-tag"])

    def test_default_rules_leave_customer_language_alone(self):
        for text in ("Request a new run", "useLegacy", "R2 of the fit", "Build Pipeline Assets",
                     "StringBuilder", "MAOP 1,440 psig", "todo list", "Station Operations v2",
                     "SEG-05 and SEG-08 at 16 in", "Spotfire 14.6"):
            self.assertEqual(lint_texts(text), [], text)

    def test_scopes(self):
        self.assertEqual(lint_texts("ReqOpsDays", textlint.NAME), [])       # a property name is a name
        self.assertEqual(lint_texts("ReqOpsDays", textlint.CODE), [])
        self.assertEqual(lint_texts("v1.2", textlint.CODE), [])             # library versions in bundles
        self.assertEqual(lint_texts("R2.0", textlint.CODE), ["release-tag"])

    def test_allow_and_banned_terms(self):
        app = {"textLint": {"allow": ["builder"]}, "bannedTerms": ["Kestrel", "re:Project\\s+Falcon"]}
        self.assertEqual(lint_texts("the report builder", app=app), [])
        self.assertEqual(lint_texts("ask Kestrel", app=app), ["banned-term"])
        self.assertEqual(lint_texts("KESTREL's data", app=app), ["banned-term"])
        self.assertEqual(lint_texts("Kestrel-Two", app=app), ["banned-term"])
        self.assertEqual(lint_texts("Kestrels", app=app), [])
        self.assertEqual(lint_texts("Project  Falcon", app=app), ["banned-term"])

    def test_config_problems(self):
        self.assertEqual(textlint.config_problems({}), [])
        probs = dict(textlint.config_problems({"textLint": {"visible": "loud", "allow": ["nope"], "x": 1},
                                               "bannedTerms": ["", "re:("]}))
        self.assertIn("app.textLint.visible", probs)
        self.assertIn("app.textLint.allow[0]", probs)
        self.assertIn("app.textLint.x", probs)
        self.assertIn("app.bannedTerms[0]", probs)
        self.assertIn("app.bannedTerms[1]", probs)


class SegmentTests(unittest.TestCase):
    def test_python_comments_docstrings_strings(self):
        code = ('"""Module doc: verbatim port."""\n'
                'import numpy as np  # legacy stream\n'
                'def f():\n'
                '    """Docstring."""\n'
                '    msg = "R2.0 story"\n'
                '    legacy_value = 1\n'
                '    return msg\n')
        segs = textlint.python_segments(code)
        kinds = [(line, kind) for line, kind, _ in segs]
        self.assertIn((1, "docstring"), kinds)
        self.assertIn((2, "comment"), kinds)
        self.assertIn((4, "docstring"), kinds)
        self.assertIn((5, "string"), kinds)
        self.assertFalse(any("legacy_value" in text for _, _, text in segs))   # identifiers are not scanned

    def test_python_fallback_on_bad_code(self):
        segs = textlint.hash_segments('x = "a # b"  # TODO fix\n')
        self.assertEqual([k for _, k, _ in segs], ["comment", "string"])
        self.assertTrue(segs[0][2].startswith("# TODO"))

    def test_js_segments(self):
        code = ('// prototype helper\n'
                'var css = `\n.a { color: red; } // inside the template\n`;\n'
                'Foo.prototype.bar = function () { return "legacy"; };\n'
                '/* multi\nline TODO */\n')
        segs = textlint.js_segments(code)
        self.assertEqual(segs[0], (1, "comment", "// prototype helper"))
        self.assertEqual(segs[1][1], "string")
        self.assertIn("inside the template", segs[1][2])
        self.assertEqual(segs[2], (5, "string", '"legacy"'))
        self.assertEqual(segs[3][0], 6)
        self.assertFalse(any("Foo.prototype" in t for _, _, t in segs))

    def test_html_segments(self):
        items = textlint.html_segments('<div title="R2.0 view">The {{control:r6}} line<!-- TODO -->'
                                       '<a title="Details">&#9432;</a></div>')
        scopes = [(scope, kind) for _, scope, kind, _ in items]
        self.assertIn((textlint.VISIBLE, "attribute"), scopes)
        self.assertIn((textlint.CODE, "comment"), scopes)
        texts = [t for _, s, k, t in items if k == "text"]
        self.assertFalse(any("control" in t for t in texts))


SPEC_FILES = {
    "data/FLOWS.csv": "Date,Flow (bbl/d)\n2026-01-01,100\n",
    "html/steps.html": ('<div><p>Run the builder, then read the R2.0 notes.</p>'
                        '<!-- TODO: shorten --></div>'),
    "datafunctions/score.py": '"""Scores the run."""\n# verbatim port of the old model\nScore = 1.0\n',
    "scripts/run_scenario.py": ('# Runs the scenario\n'
                                'Document.Properties["Msg"] = "Scenario finished"\n'),
}


def text_spec(**app):
    spec = {
        "specVersion": 1,
        "app": dict({"name": "Flow Monitor", "description": "Flow and cost per barrel."}, **app),
        "tables": [{"name": "FLOWS", "source": {"type": "csv", "path": "data/FLOWS.csv",
                                                "columns": {"Date": "DateTime", "Flow (bbl/d)": "Real"}},
                    "description": "Daily flow; Kestrel's export"}],
        "properties": [{"name": "Score", "type": "Real", "default": 0.0},
                       {"name": "Msg", "type": "String", "default": ""}],
        "dataFunctions": [{"name": "Score Run", "script": "datafunctions/score.py", "description": "Scores the run",
                           "outputs": [{"name": "Score", "type": "value", "target": {"property": "Score"}}]}],
        "scripts": [{"name": "Run Scenario", "file": "scripts/run_scenario.py",
                     "description": "Runs the scenario"}],
        "pages": [{"title": "Overview", "visuals": [
            {"id": "steps", "type": "textArea", "title": "Steps", "html": "html/steps.html"},
            {"id": "trend", "type": "lineChart", "title": "Throughput (R2.0 copy)", "table": "FLOWS",
             "x": "[Date]", "y": "Sum([Flow (bbl/d)])"}],
            "layout": {"row": [{"visual": "steps"}, {"visual": "trend"}]}}],
    }
    return spec


def text_findings(report, level):
    return [i for i in getattr(report, level) if i["message"].startswith("customer-ready text:")]


class CustomerTextValidateTests(AppTestCase):
    def check(self, spec):
        return self.validate(spec, SPEC_FILES, lint=False, sanitize=False)

    def test_visible_text_is_an_error_code_comments_a_warning(self):
        report = self.check(text_spec())
        self.assertHasError(report, "pages[0].visuals[1].title", "'R2.0' (internal release tag)")
        self.assertHasError(report, "pages[0].visuals[0].html", "'builder' (internal tool word)")
        self.assertHasError(report, "pages[0].visuals[0].html", "'R2.0'")
        self.assertHasWarning(report, "pages[0].visuals[0].html", "'TODO' (development note) in comments")
        self.assertHasWarning(report, "dataFunctions[0].script", "'verbatim' (design-history word) in comments")
        self.assertFalse(any("scripts[0]" in i["path"] for i in text_findings(report, "errors")
                             + text_findings(report, "warnings")))

    def test_levels_allow_and_banned_terms(self):
        report = self.check(text_spec(textLint={"code": "error", "allow": ["release-tag"]},
                                      bannedTerms=["Kestrel"]))
        self.assertHasError(report, "dataFunctions[0].script", "'verbatim'")
        self.assertHasError(report, "tables[0].description", "banned term of this app")
        self.assertFalse(any("release tag" in i["message"] for i in text_findings(report, "errors")))
        report = self.check(text_spec(textLint={"visible": "off", "code": "off"}))
        self.assertEqual(text_findings(report, "errors") + text_findings(report, "warnings"), [])

    def test_bad_config_is_an_error(self):
        report = self.check(text_spec(textLint={"visible": "loud"}, bannedTerms=["re:("]))
        self.assertHasError(report, "app.textLint.visible", "must be one of")
        self.assertHasError(report, "app.bannedTerms[0]", "not a valid regular expression")

    def test_validate_only_keys_never_reach_the_builder(self):
        spec = text_spec(textLint={"allow": ["builder"]}, bannedTerms=["Kestrel"])
        app = self.make_app(spec, SPEC_FILES)
        resolved = dxpgen.resolve_spec(spec, app)
        self.assertNotIn("textLint", resolved["app"])
        self.assertNotIn("bannedTerms", resolved["app"])


class ValueKindTests(unittest.TestCase):
    TYPES = {"ViewDayShown": "LongInteger", "ViewDate": "DateTime", "Limit": "Real", "Name": "String"}

    def kind(self, text):
        cols = {"Date": "date", "Flow (bbl/d)": "number"}
        return sfexpr.value_kind(text, self.TYPES.get, cols.get)[0]

    def test_kinds(self):
        self.assertEqual(self.kind('DateAdd("day", DocumentProperty("ViewDayShown") - 1, Min([Date])) as [V]'),
                         "date")
        self.assertEqual(self.kind('DocumentProperty("ViewDate") as [View Day]'), "date")
        self.assertEqual(self.kind("[$ViewDate]"), "date")
        self.assertEqual(self.kind('DocumentProperty("ViewDayShown") - 1'), "number")
        self.assertEqual(self.kind('-1.0 * DocumentProperty("Limit") as [Low]'), "number")
        self.assertEqual(self.kind("1440.0 as [MAOP]"), "number")
        self.assertEqual(self.kind("Max([Date])"), "date")
        self.assertEqual(self.kind("Sum([Flow (bbl/d)])"), "number")
        self.assertEqual(self.kind('(DocumentProperty("Name"))'), "string")
        self.assertIsNone(self.kind('Avg(If([Day] = DocumentProperty("ViewDayShown"), [Flow (bbl/d)]))'))
        self.assertIsNone(self.kind('DocumentProperty("Unknown")'))

    def test_date_call_properties(self):
        self.assertEqual(sfexpr.date_call_properties(
            'DateAdd("day", DocumentProperty("ViewDayShown") - 1, Min([Date (x)]))'), [("DateAdd", "ViewDayShown")])
        self.assertEqual(sfexpr.date_call_properties('AddDays([$ViewDate], 1)'), [("AddDays", "ViewDate")])
        self.assertEqual(sfexpr.date_call_properties('DocumentProperty("ViewDate")'), [])


def ref_spec(layers, columns_meta=None):
    spec = text_spec(textLint={"visible": "off", "code": "off"})
    spec["properties"] += [{"name": "ViewDayShown", "type": "LongInteger", "default": 1},
                           {"name": "ViewDate", "type": "DateTime", "default": "2026-01-01T00:00:00"},
                           {"name": "Limit", "type": "Real", "default": 5.0}]
    spec["pages"][0]["visuals"][1]["referenceLayers"] = layers
    return spec


class ReferenceTypeTests(AppTestCase):
    def refs(self, *layers):
        report = self.validate(ref_spec(list(layers)), SPEC_FILES, lint=False, sanitize=False)
        return report, [i for i in report.errors + report.warnings if ".referenceLayers[" in i["path"]]

    def test_b1_dateadd_over_a_number_property(self):
        report, _ = self.refs({"kind": "verticalLine",
                               "value": 'DateAdd("day", DocumentProperty("ViewDayShown") - 1, Min([Date]))'})
        item = self.assertHasError(report, "referenceLayers[0].value", "Invalid type for function call 'DateAdd'")
        self.assertIn("ViewDate", item["message"])                     # the hint names the DateTime property

    def test_number_on_a_date_axis(self):
        report, _ = self.refs({"kind": "verticalLine", "value": 'DocumentProperty("ViewDayShown") - 1'})
        self.assertHasError(report, "referenceLayers[0].value", "holds dates but this verticalLine evaluates to "
                            "a number (arithmetic on DocumentProperty(\"ViewDayShown\")")

    def test_date_on_a_number_axis(self):
        report, _ = self.refs({"kind": "horizontalLine", "value": "[$ViewDate]"})
        self.assertHasError(report, "referenceLayers[0].value", "holds numbers but this horizontalLine")

    def test_correct_lines_are_clean(self):
        _, found = self.refs({"kind": "verticalLine", "value": 'DocumentProperty("ViewDate") as [View Day]'},
                             {"kind": "verticalLine", "value": 'Date("2026-05-31")'},
                             {"kind": "horizontalLine", "value": '-1.0 * DocumentProperty("Limit") as [Low]'},
                             {"kind": "horizontalLine", "value": "1440.0 as [MAOP]"})
        self.assertEqual(found, [])

    def test_column_kind_sources(self):
        spec = {"specVersion": 1, "app": {"name": "T"},
                "tables": [{"name": "T", "source": {"type": "dataFunction", "function": "F", "output": "T"},
                            "columns": {"Day Start": {"format": "yyyy-MM-dd"}, "Flow": {"format": "#,##0"}}}]}
        v = dxpgen.Validator(spec, self.tmp)
        v.collect()
        self.assertEqual(v.column_kind("T", "Day Start"), ("date", "format"))
        self.assertEqual(v.column_kind("T", "Flow"), ("number", "format"))
        self.assertEqual(v.column_kind("T", "Timestamp"), ("date", "name"))
        self.assertEqual(v.column_kind("T", "Start Date"), ("date", "name"))
        self.assertEqual(v.column_kind("T", "Segment ID"), (None, None))


if __name__ == "__main__":
    unittest.main()
