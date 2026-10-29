# Hosts and wiring

An action-mod script runs when a user clicks something that is wired to it. The wiring stores the
script id, the argument values and a configuration name in the analysis.

## Hosts

| Host | Shows | Facts from Analyst 15.0 |
|---|---|---|
| text-area button or link | the control's own label | an action control can run an action-mod script instead of an IronPython script |
| visual floating button | the script's icon on the visual | the icon comes from the script in the manifest |
| visual title-bar button | the script's icon in the title bar | title-bar buttons render only for action-mod scripts, never for IronPython scripts |
| visual context-menu item | the configuration's name in the right-click menu | |

The configuration's name is the context-menu text and the button tooltip. Without a name, menu
items of one script differ only by their argument values, so name each configuration ("Find
similar events", "Open pump detail"). Named configurations and finding the menu items by those
names worked live.

Wire by hand (dialog labels can differ slightly between versions):

- Text-area button: edit the text area, select the button, and set its action to the action-mod
  script with values for its parameters.
- Visual button or menu item: the visual's properties, Action trigger, choose the trigger type
  (floating button, title-bar button, context-menu item), then select the action and its
  arguments.

Spotfire 15.0 has no public API to wire an action-mod script to a host, so a builder that cannot
do it lists these as manual steps. The `building-spotfire-dxps` skill says which hosts need them.

## Arguments

- Values are literals typed by the parameter's type. `Page`, `Visualization` and `DataTable`
  parameters take a page, visual or table of the analysis.
- Leave an optional argument out instead of passing an empty value: an empty optional argument
  stopped the action without an error.
- One script with several argument sets serves several buttons (Run preview, Run all), but all of
  them show the same icon.

## What runs where

| Need | Use |
|---|---|
| a button that changes properties, pages or markings | an action-mod script |
| a button on a visual (title bar, floating, menu) | an action-mod script (the only option) |
| work that reacts to a property change | an IronPython trigger script |
| work after a marking changes | a data function bound to the marking, which writes a property, whose trigger runs |
| heavy logic shared by several hosts | IronPython behind a property trigger; the action writes the property |

A proven split: the action scripts write document properties (a view setting, or a command as
JSON with a fresh id so every click changes the value), and property-trigger scripts do the heavy
work. The action stays small and testable; the IronPython keeps one code path.

Writing a property only when its value changes keeps its trigger from running for nothing
(`set-text-property` in the example). A command that must run on every click needs a value that
changes on every click (a timestamp or counter id inside the JSON).

## Compare with IronPython buttons

| | IronPython script | Action-mod script |
|---|---|---|
| language | IronPython 3.4 in the analysis | JavaScript in a signed mod |
| visual title-bar and floating buttons | no | yes |
| icons | no | one per script |
| reuse across analyses | copy the script | the same mod from the library |
| trust | approved per user when created in Analyst | signed with a code-trust certificate; other users trust the signer |
| tests outside Spotfire | lint only | type check with the official typings, scenarios against a mock |

An app can ship both variants (IronPython buttons and action-mod buttons) from one design and
compare them; the property-trigger scripts stay IronPython in both.
