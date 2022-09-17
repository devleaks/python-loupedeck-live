import setuptools

with open("VERSION", 'r') as f:
    version = f.read().strip()

with open("README.md", 'r') as f:
    long_description = f.read()

setuptools.setup(
   name='loupedeck',
   version=version,
   description='Library to control Loupedeck LoupedeckLive devices.',
   author='Pierre M',
   author_email='pierre@devleaks.be',
   url='https://github.com/devleaks/python-loupedeck-live',
   package_dir={'': 'src'},
   packages=setuptools.find_packages(where='src'),
   install_requires=[],
   license="MIT",
   long_description=long_description,
   long_description_content_type="text/markdown",
   include_package_data=True,
   python_requires='>=3.8',
)
