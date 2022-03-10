import re

from docutils import nodes
from docutils.parsers.rst import Directive, directives
from pygments import highlight
from pygments.formatters.html import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.lexers.shell import BashSessionLexer
from pygments.lexers.special import TextLexer

#: Monkey patch Bash Session lexer to gobble up initial space after prompt
BashSessionLexer._ps1rgx = re.compile(
    r"^((?:(?:\[.*?\])|(?:\(\S+\))?(?:| |sh\S*?|\w+\S+[@:]\S+(?:\s+\S+)"
    r"?|\[\S+[@:][^\n]+\].+))\s*[$#%] )(.*\n?)"
)

# Options
# ~~~~~~~

#: Set to True if you want inline CSS styles instead of classes
INLINESTYLES = False

#: The default formatter
DEFAULT = HtmlFormatter(cssclass="highlight code-block", noclasses=INLINESTYLES)

#: Add name -> formatter pairs for every variant you want to use
VARIANTS = {
    # 'linenos': HtmlFormatter(noclasses=INLINESTYLES, linenos=True),
}


class CodeBlock(Directive):
    """Source code syntax hightlighting."""

    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = True
    option_spec = dict([(key, directives.flag) for key in VARIANTS])
    has_content = True

    def run(self):
        self.assert_has_content()
        try:
            lexer_name = self.arguments[0]
            lexer = get_lexer_by_name(lexer_name)
        except ValueError:
            # no lexer found - use the text one instead of an exception
            lexer = TextLexer()
        # take an arbitrary option if more than one is given
        formatter = self.options and VARIANTS[list(self.options)[0]] or DEFAULT
        parsed = highlight("\n".join(self.content), lexer, formatter)
        return [nodes.raw("", parsed, format="html")]
