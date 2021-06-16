"""libtmux lives at <https://github.com/tmux-python/libtmux>.

libtmux
-------

Manage tmux workspaces from JSON and YAML, pythonic API, shell completion.

"""
import sys

from setuptools import setup

about = {}
with open("libtmux/__about__.py") as fp:
    exec(fp.read(), about)

with open('requirements/test.txt') as f:
    tests_reqs = [line for line in f.read().split('\n') if line]

if sys.version_info[0] > 2:
    readme = open('README.md', encoding='utf-8').read()
else:
    readme = open('README.md').read()

history = open('CHANGES').read().replace('.. :changelog:', '')


setup(
    name=about['__title__'],
    version=about['__version__'],
    url=about['__github__'],
    download_url=about['__pypi__'],
    project_urls={
        'Documentation': about['__docs__'],
        'Code': about['__github__'],
        'Issue tracker': about['__tracker__'],
    },
    license=about['__license__'],
    author=about['__author__'],
    author_email=about['__email__'],
    description=about['__description__'],
    long_description=readme,
    long_description_content_type="text/markdown",
    packages=['libtmux'],
    include_package_data=True,
    tests_require=tests_reqs,
    zip_safe=False,
    keywords=about['__title__'],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX",
        "Operating System :: MacOS :: MacOS X",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Topic :: Utilities",
        "Topic :: System :: Shells",
    ],
)
