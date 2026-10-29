# Go To Page
# Opens the page whose title is given in the script parameter pageTitle
# (String). The title is matched exactly first, then without regard to case
# and outer spaces. When no page matches, StatusMessage lists the pages and
# the page shown stays.
# Prefer a native link or button with a go-to-page action; use this script
# when a button must do something else before it changes the page.

wanted = (pageTitle or "").strip()
target = None
for page in Document.Pages:
    if page.Title == wanted:
        target = page
        break
if target is None:
    for page in Document.Pages:
        if page.Title.strip().lower() == wanted.lower():
            target = page
            break

if target is None:
    titles = ", ".join([page.Title for page in Document.Pages])
    Document.Properties["StatusMessage"] = (
        "There is no page named '%s'. The pages are: %s." % (wanted, titles))
elif Document.ActivePageReference is None or \
        Document.ActivePageReference.Title != target.Title:
    Document.ActivePageReference = target
