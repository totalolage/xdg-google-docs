"""Explicit supported formats; never claim generic text or ZIP files."""

DOC = "application/vnd.google-apps.document"
SHEET = "application/vnd.google-apps.spreadsheet"
SLIDES = "application/vnd.google-apps.presentation"

# extension: (upload MIME type, conversion target)
FORMATS = {
    ".doc": ("application/msword", DOC),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", DOC),
    ".odt": ("application/vnd.oasis.opendocument.text", DOC),
    ".rtf": ("application/rtf", DOC),
    ".xls": ("application/vnd.ms-excel", SHEET),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", SHEET),
    ".ods": ("application/vnd.oasis.opendocument.spreadsheet", SHEET),
    ".csv": ("text/csv", SHEET),
    ".ppt": ("application/vnd.ms-powerpoint", SLIDES),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", SLIDES),
    ".odp": ("application/vnd.oasis.opendocument.presentation", SLIDES),
}

# CSV stays in its existing editor unless explicitly requested at installation.
MIME_TYPES = sorted({mime for ext, (mime, _) in FORMATS.items() if ext != ".csv"})
