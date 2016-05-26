from setuptools import setup
setup(
	name='dirpy',
	version='0.0.1',
	description='dynamic image resizing tool',
	url='http://github.com/redfin/dirpy',
	author='Redfin',
	author_email='open-source@redfin.com',
	license='Apache 2',
	classifiers=[
		# How mature is this project? Common values are
		#   3 - Alpha
		#   4 - Beta
		#   5 - Production/Stable
		'Development Status :: 3 - Alpha',

		# Indicate who your project is intended for
		'Intended Audience :: Developers',
		'Topic :: Software Development :: Build Tools',

		# Pick your license as you wish (should match 'license' above)
		'License :: OSI Approved :: Apache 2 License',

		# Specify the Python versions you support here. In particular, ensure
		# that you indicate whether you support Python 2, Python 3 or both.
		'Programming Language :: Python :: 2',
		'Programming Language :: Python :: 2.6',
		'Programming Language :: Python :: 2.7',
	],
	keywords='image resizing dynamic',
	install_requires=['pillow']
)
