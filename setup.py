from setuptools import setup, find_packages
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

if path.isfile('README.md'):
    try:
        import pypandoc
        long_description = pypandoc.convert('README.md', 'rst')
    except (IOError, ImportError):
        long_description = open('README.md').read()
else:
    long_description=""

setup(
    name='dirpy',
    version='1.2.3',

    description='A dynamic image modification proxy',
    long_description=long_description,
    url='https://github.com/redfin/dirpy',

    author='Eric Schwimmer',
    author_email='git@nerdvana.org',

    license='Apache 2.0',

    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: System Administrators',
        'Topic :: Multimedia :: Graphics :: Graphics Conversion',
        'Topic :: Multimedia :: Graphics :: Presentation',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],

    keywords='sprite generator',

    packages=find_packages(exclude=['contrib', 'docs', 'tests']),

    scripts=['bin/dirpy'],
)
