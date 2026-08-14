class CorpusError(Exception):
    """Raised whenever a corpus fails validation.

    Every raiser is expected to produce a message that names the offending
    file/observation and explains what would need to change to fix it -- these
    messages are the primary interface CI and human authors see when
    `validate`/`generate` reject a corpus.
    """
